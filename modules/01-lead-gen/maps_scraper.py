"""
Scraper de leads via Google Maps Places API + extracción de email del sitio web.
Completamente gratis dentro del crédito mensual de USD 200 de Google.
Produce 100-400 leads por ejecución según disponibilidad.
"""

import os, re, time, psycopg2, ssl, urllib.request, urllib.parse, json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

MAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
DB_HOST  = os.environ["SUPABASE_DB_HOST"]
DB_PASS  = os.environ["SUPABASE_DB_PASS"]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SKIP_DOMAINS = {"wix.com","wordpress.com","gmail.com","hotmail.com","yahoo.com",
                "instagram.com","facebook.com","tiktok.com","example.com"}

# Barrios × rubros — genera búsquedas cruzadas
BARRIOS = [
    "Palermo Buenos Aires", "San Telmo Buenos Aires", "Recoleta Buenos Aires",
    "Belgrano Buenos Aires", "Villa Crespo Buenos Aires", "Caballito Buenos Aires",
    "Almagro Buenos Aires", "Flores Buenos Aires", "Núñez Buenos Aires",
    "Puerto Madero Buenos Aires", "San Nicolás Buenos Aires", "Microcentro Buenos Aires",
    "Colegiales Buenos Aires", "Chacarita Buenos Aires", "Villa del Parque Buenos Aires",
]
RUBROS = [
    ("restaurante",        "restaurant"),
    ("bar",                "bar"),
    ("hotel",              "boutique hotel"),
    ("cafe",               "cafeteria specialty coffee"),
    ("coworking",          "coworking space"),
    ("catering",           "empresa catering"),
    ("salon_eventos",      "salon de fiestas"),
    ("club",               "club deportivo social"),
    ("museo_cultura",      "museo centro cultural"),
    ("empresa_corporativo","empresa oficina corporativa"),
    ("clinica_salud",      "clinica hospital salud"),
    ("educacion",          "universidad colegio educacion"),
    ("panaderia",          "panaderia pasteleria"),
    ("gimnasio",           "gimnasio fitness"),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
        return r.read()


def places_search(query: str, page_token: str = "") -> dict:
    params = {"query": query, "key": MAPS_KEY, "language": "es"}
    if page_token:
        params["pagetoken"] = page_token
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urllib.parse.urlencode(params)
    return json.loads(fetch(url))


def place_details(place_id: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": "name,website,formatted_phone_number,formatted_address,types",
        "key": MAPS_KEY,
        "language": "es",
    }
    url = "https://maps.googleapis.com/maps/api/place/details/json?" + urllib.parse.urlencode(params)
    return json.loads(fetch(url)).get("result", {})


def scrape_email_from_website(url: str) -> str | None:
    """Intenta extraer email directamente del HTML del sitio."""
    try:
        html = fetch(url).decode("utf-8", errors="ignore")
        emails = EMAIL_RE.findall(html)
        for em in emails:
            domain = em.split("@")[1].lower()
            if domain not in SKIP_DOMAINS and not domain.startswith("sentry"):
                return em.lower()
    except Exception:
        pass
    return None


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=5432, dbname="postgres",
        user="postgres", password=DB_PASS, sslmode="require"
    )


def insert_lead(nombre_lugar: str, email: str, rubro: str, barrio: str) -> bool:
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO leads (nombre_lugar, email, rubro, barrio, ciudad, fuente)
            VALUES (%s, %s, %s, %s, 'Buenos Aires', 'google_maps')
            ON CONFLICT (email) DO NOTHING
        """, (nombre_lugar, email, rubro, barrio))
        inserted = cur.rowcount > 0
        conn.commit()
        return inserted
    except Exception:
        return False
    finally:
        cur.close(); conn.close()


def run_with_api(max_per_combo: int = 20):
    """Requiere GOOGLE_MAPS_API_KEY."""
    if not MAPS_KEY:
        print("⚠️  GOOGLE_MAPS_API_KEY no configurada. Usando modo alternativo.")
        run_without_api()
        return

    total = 0
    for rubro_es, rubro_en in RUBROS:
        for barrio in BARRIOS[:8]:  # primeros 8 barrios por rubro
            query = f"{rubro_en} in {barrio}"
            print(f"  🔍 {query}")
            try:
                data = places_search(query)
                places = data.get("results", [])[:max_per_combo]
                for place in places:
                    pid = place.get("place_id")
                    nombre = place.get("name", "")
                    if not pid or not nombre:
                        continue
                    details = place_details(pid)
                    website = details.get("website", "")
                    if not website:
                        continue
                    email = scrape_email_from_website(website)
                    if email:
                        inserted = insert_lead(nombre, email, rubro_es, barrio.split()[0])
                        if inserted:
                            print(f"    ✓ {nombre} → {email}")
                            total += 1
                    time.sleep(0.3)
            except Exception as e:
                print(f"    Error: {e}")
            time.sleep(0.5)

    print(f"\n✅ Google Maps: {total} leads nuevos")


def run_without_api():
    """
    Modo alternativo sin API key: scraping de Guía Oleo y páginas de contacto.
    Guía Oleo lista cientos de restaurantes en Buenos Aires con datos de contacto.
    """
    print("🍽️  Scrapeando Guía Oleo...")
    total = 0

    # Guía Oleo — páginas de búsqueda por zona
    zonas_oleo = [
        "palermo", "san-telmo", "recoleta", "belgrano",
        "villa-crespo", "caballito", "almagro", "microcentro",
    ]

    for zona in zonas_oleo:
        url = f"https://www.guiaoleo.com.ar/restaurantes/buenos-aires/{zona}/"
        print(f"  → {url}")
        try:
            html = fetch(url).decode("utf-8", errors="ignore")

            # Extraer emails directamente
            emails_found = EMAIL_RE.findall(html)
            emails_valid = [
                e.lower() for e in set(emails_found)
                if e.split("@")[1].lower() not in SKIP_DOMAINS
                and len(e) < 80
            ]

            # Extraer nombres de restaurantes (heurística por clase HTML)
            names = re.findall(r'class="[^"]*restaurante[^"]*"[^>]*>([^<]{3,60})<', html)
            if not names:
                names = re.findall(r'<h2[^>]*>([^<]{3,60})</h2>', html)

            for i, email in enumerate(emails_valid[:20]):
                nombre = names[i] if i < len(names) else f"Restaurante {zona.title()}"
                inserted = insert_lead(nombre.strip(), email, "restaurante", zona.replace("-", " ").title())
                if inserted:
                    print(f"    ✓ {nombre.strip()[:40]} → {email}")
                    total += 1

        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(1)

    print(f"\n✅ Guía Oleo: {total} leads nuevos")
    return total


def run():
    if MAPS_KEY:
        run_with_api()
    else:
        run_without_api()


if __name__ == "__main__":
    run()
