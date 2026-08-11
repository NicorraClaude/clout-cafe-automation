"""
Módulo 03 — Detección de respuestas.
Revisa Gmail IMAP y marca como 'respondio' los leads que contestaron.
Ejecutar cada hora via cron.
"""

import os, imaplib, email, psycopg2, datetime
from email.header import decode_header
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASSWORD"]
DB_HOST    = os.environ["SUPABASE_DB_HOST"]
DB_PASS    = os.environ["SUPABASE_DB_PASS"]
ART        = ZoneInfo("America/Argentina/Buenos_Aires")

# La secuencia completa dura ~9 días (email 1 → +4d → email 2 → +5d → email 3).
# 30 días da margen de sobra ante cualquier caída del sistema.
DEFAULT_LOOKBACK_DAYS = 30


def db_conn():
    return psycopg2.connect(
        host=os.environ.get("SUPABASE_DB_HOST", DB_HOST), port=int(os.environ.get("SUPABASE_DB_PORT", 5432)), dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"), password=DB_PASS, sslmode="require"
    )


def get_active_threads() -> dict[str, str]:
    """Devuelve {thread_id: lead_id} de leads que esperan respuesta."""
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT thread_id, id FROM leads
        WHERE estado IN ('email_1_enviado', 'email_2_enviado', 'email_3_enviado')
          AND thread_id IS NOT NULL
    """)
    result = {r[0]: str(r[1]) for r in cur.fetchall()}
    cur.close(); conn.close()
    return result


def get_contacted_emails() -> dict[str, str]:
    """
    Devuelve {email_en_minusculas: lead_id} de todo lead ya contactado.

    Segunda vía de detección, independiente de las cabeceras del hilo: si llega
    correo DESDE una dirección que contactamos, esa persona respondió — aunque su
    cliente de correo haya alterado los headers In-Reply-To/References.
    """
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT lower(email), id FROM leads
        WHERE estado IN ('email_1_enviado', 'email_2_enviado', 'email_3_enviado')
          AND email IS NOT NULL
    """)
    result = {r[0]: str(r[1]) for r in cur.fetchall()}
    cur.close(); conn.close()
    return result


BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "no-reply", "noreply")


def es_rebote(remitente: str, asunto: str) -> bool:
    """Un rebote no es una respuesta: la dirección es inválida, nadie leyó nada."""
    r = remitente.lower()
    a = (asunto or "").lower()
    if any(s in r for s in BOUNCE_SENDERS):
        return True
    return any(s in a for s in (
        "undelivered mail", "delivery status notification", "returned mail",
        "mail delivery failed", "address not found", "no se pudo entregar",
    ))


def mark_bounced(lead_id: str):
    """Email inválido — se descarta para no seguir gastando envíos en él."""
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE leads SET estado = 'descartado', updated_at = now()
        WHERE id = %s AND estado NOT IN ('respondio', 'cliente', 'descartado')
    """, (lead_id,))
    conn.commit()
    cur.close(); conn.close()


# Dominios de correo genéricos: pertenecer al mismo dominio NO implica misma empresa.
DOMINIOS_GENERICOS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.ar",
    "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com",
    "hotmail.com.ar", "outlook.com.ar", "yahoo.es", "gmail.com.ar",
}


def mark_replied(lead_id: str):
    """
    Marca al lead como respondido Y silencia al resto de su empresa.

    Si alguien de una empresa contesta ("ya tenemos proveedor"), esa respuesta vale
    para toda la empresa. Seguir escribiéndole a sus compañeros es spam y queda mal.
    La empresa se identifica por el dominio del email, salvo dominios genéricos.
    """
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE leads SET estado = 'respondio', respondio_at = now(), updated_at = now()
        WHERE id = %s AND estado NOT IN ('respondio', 'cliente', 'descartado')
        RETURNING email
    """, (lead_id,))
    row = cur.fetchone()

    if row and row[0] and "@" in row[0]:
        dominio = row[0].split("@")[-1].lower().strip()
        if dominio not in DOMINIOS_GENERICOS:
            # Silenciar a los colegas que todavía están en la secuencia
            cur.execute("""
                UPDATE leads
                SET estado = 'descartado', updated_at = now()
                WHERE lower(split_part(email, '@', 2)) = %s
                  AND id <> %s
                  AND estado IN ('nuevo', 'encolado', 'email_1_enviado',
                                 'email_2_enviado', 'email_3_enviado')
                RETURNING nombre_contacto, email
            """, (dominio, lead_id))
            colegas = cur.fetchall()
            for nc, em in colegas:
                print(f"      ↳ silenciado colega en {dominio}: {nc or '?'} <{em}>")

    conn.commit()
    cur.close(); conn.close()


def run(days: int = DEFAULT_LOOKBACK_DAYS):
    """
    days: cuántos días hacia atrás revisar la bandeja.

    La ventana debe ser MÁS LARGA que la secuencia completa de outreach (email 1 +
    4 días + email 2 + 5 días + email 3). Con una ventana corta, una respuesta vieja
    no se detecta y el contacto recibe follow-ups habiendo ya contestado.
    """
    active     = get_active_threads()
    por_email  = get_contacted_emails()
    if not active and not por_email:
        print("Sin leads activos esperando respuesta.")
        return

    print(f"Revisando inbox de los últimos {days} días... "
          f"({len(por_email)} contactos activos)")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    mail.select("INBOX")

    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
    _, msgs = mail.search(None, f'SINCE {since}')

    ids = msgs[0].split()
    print(f"  {len(ids)} mensajes en el rango")

    ya_marcados = set()
    replied = 0
    bounced = 0

    for num in ids:
        try:
            _, data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
        except Exception as e:
            print(f"  (no se pudo leer un mensaje: {e})")
            continue

        remitente = msg.get("From", "")
        lead_id   = None
        via       = ""

        # Vía 1 — cabeceras del hilo
        combined = f"{msg.get('In-Reply-To','')} {msg.get('References','')}"
        for thread_id, lid in active.items():
            if thread_id and thread_id in combined:
                lead_id, via = lid, "hilo"
                break

        # Vía 2 — dirección del remitente (funciona aunque falten las cabeceras)
        if not lead_id:
            _, addr = email.utils.parseaddr(remitente)
            lid = por_email.get(addr.lower().strip())
            if lid:
                lead_id, via = lid, "remitente"

        if lead_id and lead_id not in ya_marcados:
            fecha  = msg.get("Date", "")
            asunto = msg.get("Subject", "")
            if es_rebote(remitente, asunto):
                print(f"  ✗ REBOTE — email inválido, se descarta el lead")
                mark_bounced(lead_id)
                bounced += 1
            else:
                print(f"  ✓ Respuesta de {remitente[:45]} ({via}) — {fecha[:31]}")
                mark_replied(lead_id)
                replied += 1
            ya_marcados.add(lead_id)

    mail.logout()
    print(f"\n✅ {replied} respuestas reales · {bounced} rebotes descartados.")
    return replied


if __name__ == "__main__":
    import sys
    d = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOOKBACK_DAYS
    run(days=d)
