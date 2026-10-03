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
    # Los que más responden van primero (respuesta medida al 03/10/2026:
    # coworking 13%, restaurante 6%, empresas 5%, hoteles 2%). "Oficinas
    # corporativas" sola traía siempre los mismos 60 lugares: se busca por tipo
    # de oficina, que es donde está la gente que toma café todo el día.
    ("coworking",           "espacio de coworking"),
    ("empresa_corporativo", "oficinas corporativas"),
    ("empresa_corporativo", "estudio contable"),
    ("empresa_corporativo", "estudio jurídico"),
    ("empresa_corporativo", "agencia de marketing"),
    ("empresa_corporativo", "empresa de software"),
    ("empresa_corporativo", "consultora"),
    ("empresa_corporativo", "inmobiliaria"),
    ("restaurante",         "restaurante"),
    ("hotel",               "hotel"),
    ("catering",            "empresa de catering"),
    ("salon_eventos",       "salón de eventos"),
    ("clinica_salud",       "clínica sanatorio"),
    ("educacion",           "universidad instituto"),
    ("club",                "club social deportivo"),
    ("panaderia",           "panadería pastelería"),
    ("cafe",                "cafetería"),
]


def fetch(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


# Places API (New): una sola consulta devuelve hasta 20 lugares CON su web
# (campo websiteUri), y nextPageToken para pedir hasta 3 páginas (60 lugares).
# La API vieja obligaba a pagar un Place Details por cada lugar para saber la
# web: unas 12 veces más caro por lugar revisado (medido 03/10/2026).
CAMPOS = "places.id,places.displayName,places.websiteUri,nextPageToken"


def places_search(query: str, page_token: str = "") -> dict:
    body = {"textQuery": query, "languageCode": "es", "regionCode": "AR", "pageSize": 20}
    if page_token:
        body["pageToken"] = page_token
    req = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": MAPS_KEY,
                 "X-Goog-FieldMask": CAMPOS},
    )
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read())


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


# ── Lugares ya revisados ─────────────────────────────────────────────────────
# Cada zona vuelve a buscarse cada ~2 semanas. Sin esta memoria se volvían a
# visitar las mismas webs (lento) y se terminaba encontrando casi nada nuevo.
REVISITAR_DIAS = 120

def _vistos(conn, ids: list) -> set:
    if not ids:
        return set()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS maps_vistos (
            place_id text PRIMARY KEY, visto_at timestamptz NOT NULL DEFAULT now())
    """)
    cur.execute("SELECT place_id FROM maps_vistos WHERE place_id = ANY(%s) "
                "AND visto_at > now() - make_interval(days => %s)", (ids, REVISITAR_DIAS))
    r = {x[0] for x in cur.fetchall()}
    conn.commit(); cur.close()
    return r

def _marcar_vistos(conn, ids: list):
    if not ids:
        return
    cur = conn.cursor()
    cur.executemany("INSERT INTO maps_vistos (place_id) VALUES (%s) ON CONFLICT (place_id) "
                    "DO UPDATE SET visto_at = now()", [(i,) for i in ids])
    conn.commit(); cur.close()


def run(zonas: list | None = None, rubros: list | None = None,
        max_paginas: int = 3, minutos: float = 20) -> int:
    """Busca cada rubro en cada zona (hasta max_paginas × 20 lugares), lee las
    webs nuevas en paralelo y guarda los que publican email. Corta a los
    `minutos` para no pasarse del tiempo del job."""
    from concurrent.futures import ThreadPoolExecutor
    if not MAPS_KEY:
        print("⚠️  Falta GOOGLE_MAPS_API_KEY — se omite Google Maps.")
        return 0

    zonas  = zonas if zonas is not None else ZONAS
    rubros = rubros if rubros is not None else RUBROS
    fin = time.time() + minutos * 60
    total = consultas = revisados = 0
    conn = db_conn()

    try:
        for zona, provincia in zonas:
            print(f"\n📍 {zona} ({provincia})")
            for rubro_es, termino in rubros:
                if time.time() > fin:
                    print("⏱  Tiempo agotado: sigue en la próxima corrida.")
                    raise StopIteration
                lugares, token = [], ""
                try:
                    for _ in range(max_paginas):
                        data = places_search(f"{termino} en {zona}, Buenos Aires, Argentina", token)
                        consultas += 1
                        lugares += data.get("places", [])
                        token = data.get("nextPageToken", "")
                        if not token:
                            break
                except Exception as e:
                    print(f"  Error {zona}/{termino}: {str(e)[:90]}")

                vistos = _vistos(conn, [l["id"] for l in lugares])
                nuevos = [l for l in lugares if l["id"] not in vistos]
                candidatos = [l for l in nuevos
                              if (l.get("websiteUri") or "").startswith("http")
                              and not is_competitor(l.get("displayName", {}).get("text", ""))]
                with ThreadPoolExecutor(max_workers=12) as ex:
                    emails = list(ex.map(lambda l: _email_seguro(l["websiteUri"]), candidatos))
                n = 0
                for l, email in zip(candidatos, emails):
                    nombre = l.get("displayName", {}).get("text", "").strip()
                    if email and nombre and insert_lead(nombre, email, rubro_es, zona, provincia):
                        n += 1
                _marcar_vistos(conn, [l["id"] for l in nuevos])
                revisados += len(nuevos)
                total += n
                print(f"  {termino:<24} {len(lugares):>3} lugares · {len(nuevos):>3} nuevos · {n:>2} leads")
    except StopIteration:
        pass
    finally:
        conn.close()

    print(f"\n✅ Google Maps: {total} leads nuevos · {revisados} lugares revisados · "
          f"{consultas} consultas (≈ USD {consultas * 0.035:.2f})")
    return total


def _email_seguro(web: str) -> str | None:
    try:
        return email_desde_web(web)
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run(zonas=ZONAS[:n])
