"""
Importa leads desde Apollo.io a Supabase.
Busca dueños/encargados de restaurantes, bares y hoteles en Buenos Aires.

Flujo:
  1. search_people() — preview sin consumir créditos
  2. enrich_people()  — revela emails (1 crédito Apollo por contacto)
  3. insert_leads()   — guarda en Supabase con dedup por email
"""

import os, time, psycopg2
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

APOLLO_KEY  = os.environ["APOLLO_API_KEY"]
DB_HOST     = os.environ["SUPABASE_DB_HOST"]
DB_PASS     = os.environ["SUPABASE_DB_PASS"]
APOLLO_BASE = "https://api.apollo.io/api/v1"

HEADERS = {"Content-Type": "application/json", "X-Api-Key": APOLLO_KEY}

TITLES = [
    "owner", "dueño", "gerente", "manager", "food and beverage manager",
    "encargado", "director", "chef ejecutivo", "director general",
    "propietario", "administrador",
]

SEGMENTS = [
    {
        "rubro": "restaurante",
        "filters": {
            "q_organization_industries": ["restaurants", "food & beverages", "food production"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "bar",
        "filters": {
            "q_organization_industries": ["wine and spirits", "restaurants", "entertainment"],
            "q_organization_keyword_tags": ["bar", "cervecería", "brewpub", "cocktail"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "hotel",
        "filters": {
            "q_organization_industries": ["hospitality", "hotels and motels", "leisure travel & tourism"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "cafe",
        "filters": {
            "q_organization_industries": ["restaurants", "food & beverages"],
            "q_organization_keyword_tags": ["coffee", "cafe", "cafetería", "specialty coffee"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "coworking",
        "filters": {
            "q_organization_industries": ["commercial real estate", "facilities services"],
            "q_organization_keyword_tags": ["coworking", "shared office"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "gastronomia",
        "filters": {
            "q_organization_industries": ["food production", "food & beverages", "consumer goods"],
            "q_organization_keyword_tags": ["gastronomia", "catering", "delivery", "panaderia"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "catering",
        "filters": {
            "q_organization_industries": ["food & beverages", "events services", "food production"],
            "q_organization_keyword_tags": ["catering", "banquetes", "eventos", "lunch"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "salon_eventos",
        "filters": {
            "q_organization_industries": ["events services", "entertainment", "hospitality"],
            "q_organization_keyword_tags": ["salon de fiestas", "eventos", "wedding", "cumpleanos"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "club",
        "filters": {
            "q_organization_industries": ["sports", "entertainment", "leisure travel & tourism"],
            "q_organization_keyword_tags": ["club", "social", "deportivo", "atletico"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "museo_cultura",
        "filters": {
            "q_organization_industries": ["museums and institutions", "arts and crafts",
                                          "entertainment", "non-profit organization management"],
            "person_titles": TITLES,
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "empresa_corporativo",
        "filters": {
            "q_organization_industries": ["staffing and recruiting", "marketing and advertising",
                                          "financial services", "information technology and services",
                                          "law practice", "accounting", "insurance"],
            "person_titles": ["office manager", "facilities manager", "administrador",
                              "jefe administrativo", "procurement", "compras", "gerente general",
                              "director de operaciones", "resources manager"],
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "empresa_corporativo",
        "filters": {
            "q_organization_industries": ["pharmaceuticals", "construction", "automotive",
                                          "retail", "consumer goods", "telecommunications",
                                          "education management", "hospital & health care"],
            "person_titles": ["office manager", "facilities manager", "administrador",
                              "jefe administrativo", "procurement", "compras"],
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "clinica_salud",
        "filters": {
            "q_organization_industries": ["hospital & health care", "medical practice",
                                          "health wellness and fitness"],
            "person_titles": TITLES + ["director médico", "administrador", "jefe de compras"],
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
    {
        "rubro": "educacion",
        "filters": {
            "q_organization_industries": ["higher education", "education management", "e-learning"],
            "person_titles": ["director", "administrador", "rector", "decano", "jefe de compras"],
            "organization_locations": ["Buenos Aires, Argentina"],
        },
    },
]


def search_people(segment: dict, page: int = 1, per_page: int = 25) -> dict:
    """Preview — NO consume créditos. Devuelve candidatos con apollo_id."""
    payload = {"page": page, "per_page": per_page, **segment["filters"]}
    resp = httpx.post(f"{APOLLO_BASE}/mixed_people/api_search", headers=HEADERS, json=payload, timeout=40)
    resp.raise_for_status()
    data = resp.json()
    people = []
    for p in data.get("people", []):
        org = p.get("organization") or {}
        people.append({
            "apollo_id": p["id"],
            "nombre_contacto": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "nombre_lugar": org.get("name") or "",
            "ciudad": "Buenos Aires",
        })
    return {"people": people, "total": data.get("total_entries", 0)}


def enrich_people(apollo_ids: list[str]) -> list[dict]:
    """CONSUME 1 crédito Apollo por contacto. Devuelve emails reales."""
    out = []
    for i in range(0, len(apollo_ids), 10):
        chunk = apollo_ids[i:i+10]
        resp = httpx.post(
            f"{APOLLO_BASE}/people/bulk_match",
            headers=HEADERS,
            json={"details": [{"id": pid} for pid in chunk], "reveal_personal_emails": False},
            timeout=90,
        )
        if resp.status_code != 200:
            print(f"  enrich error {resp.status_code}: {resp.text[:100]}")
            continue
        for m in resp.json().get("matches", []) or []:
            if not m:
                continue
            email = m.get("email", "")
            if not email or "email_not_unlocked" in email:
                continue
            org = m.get("organization") or {}
            out.append({
                "apollo_id": m.get("id"),
                "email": email.lower().strip(),
                "nombre_contacto": f"{m.get('first_name','')} {m.get('last_name','')}".strip() or None,
                "nombre_lugar": org.get("name") or "Sin nombre",
                "ciudad": "Buenos Aires",
            })
        time.sleep(1)
    return out


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=5432, dbname="postgres",
        user="postgres", password=DB_PASS, sslmode="require"
    )


def insert_leads(leads: list[dict], rubro: str) -> tuple[int, int]:
    if not leads:
        return 0, 0
    inserted = skipped = 0
    conn = db_conn()
    cur = conn.cursor()
    for lead in leads:
        try:
            cur.execute("""
                INSERT INTO leads (nombre_contacto, nombre_lugar, email, rubro, ciudad, fuente)
                VALUES (%s, %s, %s, %s, %s, 'apollo')
                ON CONFLICT (email) DO NOTHING
            """, (lead.get("nombre_contacto"), lead["nombre_lugar"], lead["email"], rubro, lead.get("ciudad", "Buenos Aires")))
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
        except Exception as e:
            print(f"  DB error: {e}")
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    return inserted, skipped


def run(pages: int = 3, max_enrich: int = 50):
    """
    pages: páginas de búsqueda por segmento (25 candidatos/página)
    max_enrich: máx. créditos Apollo a consumir por segmento
    """
    total_in = total_sk = 0

    for seg in SEGMENTS:
        print(f"\n→ Segmento: {seg['rubro']}")
        all_ids = []

        for page in range(1, pages + 1):
            print(f"  Buscando página {page}...", end=" ")
            result = search_people(seg, page=page)
            people = result["people"]
            print(f"{len(people)} candidatos con email (total disponibles: {result['total']})")
            all_ids.extend([(p["apollo_id"], p) for p in people])
            if len(people) < 25:
                break
            time.sleep(1)

        # Enriquecer (consumir créditos) solo los primeros max_enrich
        to_enrich = all_ids[:max_enrich]
        if not to_enrich:
            print("  Sin candidatos para enriquecer.")
            continue

        print(f"  Enriqueciendo {len(to_enrich)} contactos (consume créditos Apollo)...")
        enriched = enrich_people([x[0] for x in to_enrich])
        print(f"  {len(enriched)} emails revelados")

        ins, sk = insert_leads(enriched, seg["rubro"])
        print(f"  → {ins} nuevos en Supabase, {sk} omitidos")
        total_in += ins
        total_sk += sk

    print(f"\n✅ Total final: {total_in} leads nuevos, {total_sk} omitidos")


if __name__ == "__main__":
    run(pages=5, max_enrich=50)
