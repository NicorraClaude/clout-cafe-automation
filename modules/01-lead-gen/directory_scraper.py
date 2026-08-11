"""
Scraper de directorios para Clout Café — toda Argentina.
Fuente principal: OpenStreetMap Overpass API.
Cubre CABA por barrios, luego GBA y capitales de provincia.
"""

import os, re, time, psycopg2, ssl, urllib.request, urllib.parse, json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

DB_HOST = os.environ["SUPABASE_DB_HOST"]
DB_PASS = os.environ["SUPABASE_DB_PASS"]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EMAIL_RE   = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,6}")
MAILTO_RE  = re.compile(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,6})', re.I)
IMAGE_EXT  = re.compile(r'\.(png|jpg|jpeg|gif|svg|webp|ico|pdf|zip|mp4|mov|avi|woff|ttf|eot)$', re.I)

# Dominios genéricos que no son emails de contacto
SKIP_DOMAINS = {
    "wix.com","wordpress.com","gmail.com","hotmail.com","yahoo.com","outlook.com",
    "instagram.com","facebook.com","tiktok.com","example.com","sentry.io",
    "google.com","w3.org","schema.org","jquery.com","cloudflare.com","sentry-cdn.com",
    "maps.google","squarespace.com","mailchimp.com","godaddy.com","shopify.com",
    "wixpress.com","amazonaws.com","noreply","no-reply","donotreply",
}

# Palabras clave de competidores/tostaderos que NO queremos contactar
COMPETITOR_KEYWORDS = {
    "tostadero", "tostador", "roaster", "roastery", "specialty roast",
    "café de especialidad", "coffee roast", "single origin", "third wave",
    "tercera ola", "clout café", "clout cafe",
}

# ── Geografía Argentina completa ──────────────────────────────────────────────
# Formato: (nombre_display, provincia, bbox "lat_min,lon_min,lat_max,lon_max")

CABA_BARRIOS = [
    # Barrios CABA — bboxes aproximados por barrio
    ("Palermo",          "CABA", "-34.594,-58.444,-34.565,-58.405"),
    ("Recoleta",         "CABA", "-34.596,-58.400,-34.579,-58.368"),
    ("San Telmo",        "CABA", "-34.629,-58.378,-34.613,-58.355"),
    ("Puerto Madero",    "CABA", "-34.623,-58.376,-34.597,-58.348"),
    ("Belgrano",         "CABA", "-34.570,-58.474,-34.549,-58.443"),
    ("Villa Crespo",     "CABA", "-34.610,-58.448,-34.591,-58.424"),
    ("Caballito",        "CABA", "-34.628,-58.441,-34.606,-58.407"),
    ("Almagro",          "CABA", "-34.617,-58.420,-34.598,-58.394"),
    ("Flores",           "CABA", "-34.641,-58.468,-34.619,-58.432"),
    ("Colegiales",       "CABA", "-34.582,-58.455,-34.566,-58.430"),
    ("Chacarita",        "CABA", "-34.589,-58.464,-34.569,-58.445"),
    ("Villa del Parque", "CABA", "-34.615,-58.481,-34.597,-58.457"),
    ("Nuñez",            "CABA", "-34.561,-58.469,-34.547,-58.441"),
    ("Saavedra",         "CABA", "-34.560,-58.489,-34.543,-58.462"),
    ("Boedo",            "CABA", "-34.638,-58.420,-34.620,-58.396"),
    ("Barracas",         "CABA", "-34.650,-58.395,-34.630,-58.360"),
    ("La Boca",          "CABA", "-34.645,-58.378,-34.627,-58.352"),
    ("Monserrat",        "CABA", "-34.619,-58.381,-34.607,-58.362"),
    ("Retiro",           "CABA", "-34.596,-58.383,-34.582,-58.360"),
    ("Microcentro",      "CABA", "-34.612,-58.380,-34.597,-58.358"),
    ("Villa Urquiza",    "CABA", "-34.578,-58.493,-34.560,-58.465"),
    ("Balvanera",        "CABA", "-34.617,-58.407,-34.601,-58.383"),
    ("Liniers",          "CABA", "-34.646,-58.529,-34.626,-58.503"),
    ("Devoto",           "CABA", "-34.606,-58.512,-34.586,-58.484"),
    ("Paternal",         "CABA", "-34.602,-58.474,-34.587,-58.452"),
]

GBA_CIUDADES = [
    ("San Isidro",    "Prov. Buenos Aires", "-34.486,-58.546,-34.454,-58.510"),
    ("Vicente López", "Prov. Buenos Aires", "-34.542,-58.503,-34.513,-58.469"),
    ("Tigre",         "Prov. Buenos Aires", "-34.433,-58.590,-34.397,-58.550"),
    ("Pilar",         "Prov. Buenos Aires", "-34.471,-58.942,-34.436,-58.904"),
    ("Olivos",        "Prov. Buenos Aires", "-34.519,-58.505,-34.496,-58.478"),
    ("Quilmes",       "Prov. Buenos Aires", "-34.735,-58.278,-34.705,-58.240"),
    ("Lomas de Zamora","Prov. Buenos Aires","-34.773,-58.418,-34.744,-58.380"),
    ("Avellaneda",    "Prov. Buenos Aires", "-34.679,-58.379,-34.652,-58.343"),
    ("Lanús",         "Prov. Buenos Aires", "-34.717,-58.407,-34.690,-58.371"),
    ("La Plata",      "Prov. Buenos Aires", "-34.940,-57.982,-34.887,-57.929"),
    ("Mar del Plata", "Prov. Buenos Aires", "-38.020,-57.580,-37.990,-57.535"),
    ("Bahía Blanca",  "Prov. Buenos Aires", "-38.738,-62.293,-38.698,-62.239"),
    ("Tandil",        "Prov. Buenos Aires", "-37.336,-59.153,-37.306,-59.112"),
    ("Rosario",       "Prov. Buenos Aires", "-32.990,-60.700,-32.940,-60.630"),  # es Santa Fe pero coloquialmente
]

INTERIOR_CIUDADES = [
    ("Rosario",       "Santa Fe",     "-32.990,-60.700,-32.940,-60.630"),
    ("Santa Fe",      "Santa Fe",     "-31.650,-60.730,-31.600,-60.680"),
    ("Córdoba",       "Córdoba",      "-31.440,-64.230,-31.390,-64.155"),
    ("Mendoza",       "Mendoza",      "-32.910,-68.870,-32.870,-68.820"),
    ("Tucumán",       "Tucumán",      "-26.850,-65.240,-26.800,-65.195"),
    ("Salta",         "Salta",        "-24.800,-65.440,-24.760,-65.395"),
    ("Neuquén",       "Neuquén",      "-38.960,-68.100,-38.920,-68.050"),
    ("Bariloche",     "Río Negro",    "-41.140,-71.330,-41.100,-71.275"),
    ("Posadas",       "Misiones",     "-27.395,-55.940,-27.360,-55.893"),
    ("Corrientes",    "Corrientes",   "-27.490,-58.850,-27.455,-58.808"),
    ("Resistencia",   "Chaco",        "-27.470,-59.010,-27.430,-58.963"),
    ("Paraná",        "Entre Ríos",   "-31.750,-60.520,-31.710,-60.474"),
    ("San Juan",      "San Juan",     "-31.555,-68.560,-31.515,-68.515"),
    ("San Luis",      "San Luis",     "-33.310,-66.360,-33.275,-66.315"),
    ("Jujuy",         "Jujuy",        "-24.200,-65.320,-24.170,-65.280"),
    ("Formosa",       "Formosa",      "-26.190,-58.200,-26.160,-58.163"),
    ("Catamarca",     "Catamarca",    "-28.480,-65.790,-28.445,-65.745"),
    ("La Rioja",      "La Rioja",     "-29.420,-66.870,-29.385,-66.825"),
    ("Santiago del Estero","Santiago del Estero","-27.800,-64.280,-27.765,-64.233"),
    ("Santa Rosa",    "La Pampa",     "-36.635,-64.300,-36.600,-64.255"),
    ("Viedma",        "Río Negro",    "-40.820,-63.010,-40.785,-62.963"),
    ("Ushuaia",       "Tierra del Fuego","-54.820,-68.360,-54.790,-68.285"),
    ("Comodoro Rivadavia","Chute",    "-45.880,-67.530,-45.855,-67.487"),
    ("Puerto Madryn", "Chubut",       "-42.790,-65.050,-42.760,-65.005"),
    ("Zárate",        "Prov. Buenos Aires", "-34.120,-59.050,-34.085,-59.005"),
    ("Luján",         "Prov. Buenos Aires", "-34.580,-59.120,-34.550,-59.075"),
]

ALL_LOCATIONS = CABA_BARRIOS + GBA_CIUDADES + INTERIOR_CIUDADES

# ─────────────────────────────────────────────────────────────────────────────

def fetch(url: str, method: str = "GET", data: bytes = None, timeout: int = 15,
          content_type: str = "") -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
    }
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def valid_email(email: str) -> bool:
    if IMAGE_EXT.search(email):
        return False
    if len(email) > 80 or len(email) < 6:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain:
        return False
    # Domain must have at least one dot and a TLD of 2-6 chars
    if not re.match(r'^[a-z0-9\-]+(\.[a-z0-9\-]+)+$', domain.lower()):
        return False
    tld = domain.split(".")[-1].lower()
    if len(tld) < 2 or len(tld) > 6 or not tld.isalpha():
        return False
    if any(d in domain.lower() for d in SKIP_DOMAINS):
        return False
    # Local part can't look like a filename (contain @ before an extension)
    if re.search(r'[@x]\d+\.(png|jpg|svg|webp)', local.lower()):
        return False
    return True


def is_competitor(nombre: str) -> bool:
    nombre_lower = nombre.lower()
    return any(kw in nombre_lower for kw in COMPETITOR_KEYWORDS)


def extract_email_from_website(url: str) -> str | None:
    try:
        html = fetch(url, timeout=12).decode("utf-8", errors="ignore")

        # mailto: links primero — los más confiables
        for em in MAILTO_RE.findall(html):
            if valid_email(em):
                return em.lower()

        # Texto plano — filtrar con más cuidado
        for em in EMAIL_RE.findall(html):
            if valid_email(em):
                return em.lower()

        # Páginas de contacto
        base = url.rstrip("/").split("?")[0]
        for suffix in ["/contacto", "/contact", "/contactanos", "/sobre-nosotros"]:
            try:
                html2 = fetch(base + suffix, timeout=8).decode("utf-8", errors="ignore")
                for em in MAILTO_RE.findall(html2):
                    if valid_email(em):
                        return em.lower()
                for em in EMAIL_RE.findall(html2):
                    if valid_email(em):
                        return em.lower()
            except Exception:
                pass

    except Exception:
        pass
    return None


def db_conn():
    return psycopg2.connect(
        host=os.environ.get("SUPABASE_DB_HOST", DB_HOST), port=int(os.environ.get("SUPABASE_DB_PORT", 5432)), dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"), password=DB_PASS, sslmode="require"
    )


def insert_lead(nombre: str, email: str, rubro: str, fuente: str,
                ciudad: str, barrio: str | None, provincia: str) -> bool:
    if not valid_email(email):
        return False
    if is_competitor(nombre):
        return False

    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO leads (nombre_lugar, email, rubro, ciudad, barrio, provincia, fuente)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
        """, (nombre, email, rubro, ciudad, barrio, provincia, fuente))
        inserted = cur.rowcount > 0
        conn.commit()
        return inserted
    except Exception as e:
        print(f"    DB error: {e}")
        return False
    finally:
        cur.close(); conn.close()


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

OSM_RUBROS = [
    ("restaurante", 'amenity"="restaurant'),
    ("bar",         'amenity"="bar'),
    ("cafe",        'amenity"="cafe'),
    ("hotel",       'tourism"="hotel'),
    ("coworking",   'amenity"="coworking_space'),
]

def scrape_osm_location(display_name: str, provincia: str, bbox: str) -> int:
    """Scrape OSM for a single geographic area."""
    total = 0

    for rubro, osm_tag in OSM_RUBROS:
        query = f"""[out:json][timeout:25];
(
  node["{osm_tag}"]["website"]({bbox});
  way["{osm_tag}"]["website"]({bbox});
);
out tags;"""
        try:
            data_enc = urllib.parse.urlencode({"data": query}).encode()
            # Probar varios mirrors — el primero que responda gana
            raw = None
            for mirror in OVERPASS_MIRRORS:
                try:
                    raw = fetch(mirror, method="POST", data=data_enc, timeout=30,
                                content_type="application/x-www-form-urlencoded")
                    break
                except Exception:
                    continue
            if raw is None:
                raise RuntimeError("todos los mirrors de Overpass fallaron")
            elements = json.loads(raw).get("elements", [])

            for el in elements:
                tags = el.get("tags", {})
                nombre = tags.get("name", "").strip()
                website = (tags.get("website") or tags.get("contact:website") or "").strip()
                if not nombre or not website:
                    continue
                if is_competitor(nombre):
                    continue
                if not website.startswith("http"):
                    website = "https://" + website

                # Extract barrio from OSM tags
                barrio = (
                    tags.get("addr:suburb") or
                    tags.get("addr:neighbourhood") or
                    tags.get("is_in:suburb") or
                    display_name  # fallback to the location name
                )

                email = extract_email_from_website(website)
                if email:
                    inserted = insert_lead(nombre, email, rubro, "osm",
                                          display_name, barrio, provincia)
                    if inserted:
                        print(f"    ✓ {nombre[:40]:<40} {email}")
                        total += 1
                time.sleep(0.4)

        except Exception as e:
            print(f"  Error OSM {display_name}/{rubro}: {e}")
        time.sleep(2)

    return total


def scrape_guia_oleo(barrio: str, provincia: str) -> int:
    """Scrape Guía Oleo for a CABA barrio."""
    total = 0
    slug = barrio.lower().replace(" ", "-").replace("ñ", "n").replace("é", "e").replace("ó", "o")
    url = f"https://www.guiaoleo.com.ar/restaurantes/buenos-aires/{slug}/"
    try:
        html = fetch(url, timeout=10).decode("utf-8", errors="ignore")
        # Extract restaurant page links from Oleo
        biz_urls = re.findall(
            r'href="(https?://(?!(?:www\.)?(?:guiaoleo|facebook|instagram|twitter|google|maps|wa\.me))[^"]{5,100})"',
            html
        )
        names = re.findall(r'"name"\s*:\s*"([^"]{3,60})"', html)
        biz_urls = list(dict.fromkeys(biz_urls))[:15]  # deduplicate, max 15

        for i, biz_url in enumerate(biz_urls):
            nombre = names[i].strip() if i < len(names) else f"Restaurante {barrio}"
            if is_competitor(nombre):
                continue
            email = extract_email_from_website(biz_url)
            if email:
                inserted = insert_lead(nombre, email, "restaurante", "guia_oleo",
                                       "Buenos Aires", barrio, provincia)
                if inserted:
                    print(f"    ✓ {nombre[:40]:<40} {email}")
                    total += 1
            time.sleep(0.5)
    except Exception as e:
        print(f"  Error Oleo {barrio}: {e}")
    return total


def run(locations=None, max_locations: int = None):
    """
    Run scraper for a set of locations.
    If locations is None, cycles through ALL_LOCATIONS.
    max_locations limits how many to process (for daily partial runs).
    """
    targets = locations or ALL_LOCATIONS
    if max_locations:
        targets = targets[:max_locations]

    grand_total = 0
    for display_name, provincia, bbox in targets:
        print(f"\n📍 {display_name} ({provincia})")

        # OSM for all locations
        n = scrape_osm_location(display_name, provincia, bbox)

        # Guía Oleo only for CABA barrios
        if provincia == "Buenos Aires" and display_name in [b[0] for b in CABA_BARRIOS]:
            n += scrape_guia_oleo(display_name, provincia)

        print(f"   → {n} nuevos en {display_name}")
        grand_total += n
        time.sleep(3)

    print(f"\n✅ Total directorios: {grand_total} nuevos leads")
    return grand_total


if __name__ == "__main__":
    import sys
    # Usage: python directory_scraper.py [max_locations]
    max_loc = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(max_locations=max_loc)
