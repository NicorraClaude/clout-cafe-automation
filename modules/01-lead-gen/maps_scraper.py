"""
Scraper de leads vía Google Maps Places API.

Ventaja clave sobre OpenStreetMap: la API de Google funciona desde cualquier IP,
incluidos los servidores de GitHub Actions (Overpass bloquea IPs de datacenter).
Es la fuente principal de leads cuando el sistema corre en la nube.

Reutiliza los filtros de calidad de directory_scraper (email válido, no competidor)
para no duplicar reglas: si se ajusta el filtro allá, acá se aplica solo.
"""

import os, re, time, json, ssl, urllib.request, urllib.parse, importlib.util
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

MAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EMAIL_RE  = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
MAILTO_RE = re.compile(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})')


# ── Filtros de calidad compartidos con directory_scraper ─────────────────────
def _cargar_filtros():
    ruta = os.path.join(os.path.dirname(__file__), "directory_scraper.py")
    spec = importlib.util.spec_from_file_location("_ds", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_ds = _cargar_filtros()
valid_email   = _ds.valid_email
is_competitor = _ds.is_competitor


def _cargar_extractor():
    ruta = os.path.join(os.path.dirname(__file__), "email_extractor.py")
    spec = importlib.util.spec_from_file_location("_ex", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_extractor = _cargar_extractor()


# ── Zonas: mismas que el scraper de directorios, sin bbox ────────────────────
ZONAS = [(n, p) for n, p, _bbox in _ds.ALL_LOCATIONS]

# Ordenados por rendimiento real medido (% de negocios con email publicado).
# Los primeros rinden 3x más que los últimos: las cafeterías chicas casi nunca
# publican email (usan Instagram), los hoteles y oficinas casi siempre sí.
RUBROS = [
    ("hotel",               "hotel"),                  # 64%
    ("empresa_corporativo", "oficinas corporativas"),  # 62%
    ("salon_eventos",       "salón de eventos"),       # 46%
    ("coworking",           "espacio de coworking"),   # 38%
    ("catering",            "empresa de catering"),    # 36%
    ("clinica_salud",       "clínica sanatorio"),
    ("educacion",           "universidad instituto"),
    ("club",                "club social deportivo"),
    ("restaurante",         "restaurante"),
    ("panaderia",           "panadería pastelería"),
    ("cafe",                "cafetería"),              # 20%
]


def fetch(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def places_search(query: str, page_token: str = "") -> dict:
    params = {"query": query, "key": MAPS_KEY, "language": "es", "region": "ar"}
    if page_token:
        params["pagetoken"] = page_token
    url = ("https://maps.googleapis.com/maps/api/place/textsearch/json?"
           + urllib.parse.urlencode(params))
    return json.loads(fetch(url))


def place_details(place_id: str) -> dict:
    params = {"place_id": place_id, "fields": "name,website", "key": MAPS_KEY,
              "language": "es"}
    url = ("https://maps.googleapis.com/maps/api/place/details/json?"
           + urllib.parse.urlencode(params))
    return json.loads(fetch(url)).get("result", {})


def email_desde_web(url: str) -> str | None:
    """
    Busca el email siguiendo los enlaces de contacto reales de la página
    (no rutas adivinadas) y desofuscando formatos tipo 'info [at] dominio'.
    """
    email, _origen = _extractor.extraer(url, valid_email)
    return email


def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ.get("SUPABASE_DB_PORT", 5432)),
        dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"),
        password=os.environ["SUPABASE_DB_PASS"],
        sslmode="require", connect_timeout=15,
    )


def insert_lead(nombre: str, email: str, rubro: str, zona: str, provincia: str) -> bool:
    if not valid_email(email) or is_competitor(nombre, email):
        return False
    barrio = zona if provincia == "CABA" else None
    ciudad = "Buenos Aires" if provincia == "CABA" else zona
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO leads (nombre_lugar, email, rubro, ciudad, barrio, provincia, fuente)
            VALUES (%s, %s, %s, %s, %s, %s, 'google_maps')
            ON CONFLICT (email) DO NOTHING
        """, (nombre[:120], email, rubro, ciudad, barrio, provincia))
        inserted = cur.rowcount > 0
        conn.commit()
        return inserted
    except Exception as e:
        print(f"    DB error: {e}")
        return False
    finally:
        cur.close(); conn.close()


def run(zonas: list | None = None, rubros: list | None = None,
        max_por_busqueda: int = 20) -> int:
    if not MAPS_KEY:
        print("⚠️  Falta GOOGLE_MAPS_API_KEY — se omite Google Maps.")
        return 0

    zonas  = zonas if zonas is not None else ZONAS
    rubros = rubros if rubros is not None else RUBROS
    total = 0

    for zona, provincia in zonas:
        print(f"\n📍 {zona} ({provincia})")
        for rubro_es, termino in rubros:
            try:
                data = places_search(f"{termino} en {zona}, Argentina")
                if data.get("status") not in ("OK", "ZERO_RESULTS"):
                    print(f"  API {data.get('status')}: {data.get('error_message','')[:60]}")
                    continue

                for place in data.get("results", [])[:max_por_busqueda]:
                    nombre = place.get("name", "").strip()
                    pid    = place.get("place_id")
                    if not nombre or not pid:
                        continue
                    if is_competitor(nombre):
                        continue

                    web = place_details(pid).get("website", "")
                    if not web or not web.startswith("http"):
                        continue

                    email = email_desde_web(web)
                    if email and insert_lead(nombre, email, rubro_es, zona, provincia):
                        print(f"    ✓ {nombre[:40]:<40} {email}")
                        total += 1
                    time.sleep(0.2)
            except Exception as e:
                print(f"  Error {zona}/{rubro_es}: {str(e)[:70]}")
            time.sleep(0.4)

    print(f"\n✅ Google Maps: {total} leads nuevos")
    return total


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run(zonas=ZONAS[:n])
