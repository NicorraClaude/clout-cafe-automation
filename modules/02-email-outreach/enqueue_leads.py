"""Mueve leads de 'nuevo' a 'encolado' (listos para enviar email 1)."""
import os, psycopg2
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"], port=int(os.environ.get("SUPABASE_DB_PORT", 5432)), dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"), password=os.environ["SUPABASE_DB_PASS"], sslmode="require"
    )

# Dominios genéricos: compartirlos no implica ser la misma empresa.
DOMINIOS_GENERICOS = (
    'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com', 'yahoo.com.ar',
    'live.com', 'icloud.com', 'me.com', 'aol.com', 'protonmail.com',
    'hotmail.com.ar', 'outlook.com.ar', 'yahoo.es',
)


def silenciar_empresas_que_respondieron(cur) -> int:
    """
    Descarta leads de empresas donde alguien ya respondió.

    Corre todos los días porque las fuentes de leads (Apollo, Google Maps) siguen
    importando colegas de empresas que ya dijeron que no. Silenciarlos solo en el
    momento de detectar la respuesta no alcanza: los que se importan después
    quedarían contactables.
    """
    cur.execute("""
        UPDATE leads SET estado = 'descartado', updated_at = now()
        WHERE estado IN ('nuevo', 'encolado')
          AND lower(split_part(email, '@', 2)) IN (
              SELECT lower(split_part(email, '@', 2)) FROM leads
              WHERE (estado = 'respondio' OR respondio_at IS NOT NULL)
                AND email IS NOT NULL
                AND lower(split_part(email, '@', 2)) NOT IN %s
          )
        RETURNING nombre_lugar, email
    """, (DOMINIOS_GENERICOS,))
    silenciados = cur.fetchall()
    for nombre, email in silenciados:
        print(f"  🔇 {nombre[:34]:<34} {email}  (un colega ya respondió)")
    return len(silenciados)


def verificar_direcciones(candidatos: list) -> tuple[list, list]:
    """
    Comprueba con el servidor destino que cada casilla exista, antes de encolar.

    Evita quemar la reputación del remitente: una tasa alta de rebotes hace que
    los servidores empiecen a mandar todos los envíos a spam. Se descarta solo
    ante un rechazo explícito; ante la duda el lead se conserva.
    """
    import importlib.util
    from concurrent.futures import ThreadPoolExecutor

    ruta = os.path.join(os.path.dirname(__file__),
                        "../01-lead-gen/verificar_email.py")
    spec = importlib.util.spec_from_file_location("_ver", ruta)
    ver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ver)

    emails = [e for _, e in candidatos]
    print(f"  Verificando {len(emails)} casillas...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        resultados = list(ex.map(ver.verificar, emails))

    buenos, descartados = [], []
    for (lead_id, email), r in zip(candidatos, resultados):
        if ver.es_descartable(r):
            descartados.append((lead_id, email))
            print(f"    ✗ {email[:44]:<44} casilla inexistente")
        else:
            buenos.append(lead_id)
    return buenos, descartados


def run(limit: int = 50):
    conn = db_conn()
    cur = conn.cursor()

    n = silenciar_empresas_que_respondieron(cur)
    if n:
        print(f"  {n} leads silenciados por respuesta de un colega")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM leads WHERE estado = 'nuevo'")
    total = cur.fetchone()[0]

    # Candidatos a encolar, que se verifican antes de dejarlos pasar
    cur.execute("""
        SELECT id, email FROM leads WHERE estado = 'nuevo'
        ORDER BY created_at LIMIT %s
    """, (limit,))
    candidatos = cur.fetchall()

    if not candidatos:
        print(f"✅ 0 leads encolados (de {total} disponibles)")
        cur.close(); conn.close()
        return

    buenos, descartados = verificar_direcciones(candidatos)

    if descartados:
        cur.execute("""
            UPDATE leads SET estado = 'descartado', updated_at = now()
            WHERE id = ANY(%s::uuid[])
        """, ([str(i) for i, _ in descartados],))
    if buenos:
        cur.execute("""
            UPDATE leads SET estado = 'encolado', updated_at = now()
            WHERE id = ANY(%s::uuid[])
        """, ([str(i) for i in buenos],))
    conn.commit()

    print(f"✅ {len(buenos)} leads encolados · {len(descartados)} descartados "
          f"por casilla inexistente (de {total} disponibles)")
    cur.close(); conn.close()

if __name__ == "__main__":
    run()
