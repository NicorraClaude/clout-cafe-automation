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


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=5432, dbname="postgres",
        user="postgres", password=DB_PASS, sslmode="require"
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


def mark_replied(lead_id: str):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE leads SET estado = 'respondio', respondio_at = now(), updated_at = now()
        WHERE id = %s AND estado NOT IN ('respondio', 'cliente', 'descartado')
    """, (lead_id,))
    conn.commit()
    cur.close(); conn.close()


def run():
    active = get_active_threads()
    if not active:
        print("Sin leads activos esperando respuesta.")
        return

    print(f"Revisando inbox... ({len(active)} leads activos)")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    mail.select("INBOX")

    # Buscar emails de las últimas 24h
    since = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
    _, msgs = mail.search(None, f'SINCE {since}')

    replied = 0
    for num in msgs[0].split():
        _, data = mail.fetch(num, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        # Buscar In-Reply-To o References que matcheen nuestros thread_ids
        in_reply_to = msg.get("In-Reply-To", "")
        references  = msg.get("References", "")
        combined    = f"{in_reply_to} {references}"

        for thread_id, lead_id in active.items():
            if thread_id and thread_id in combined:
                sender = msg.get("From", "")
                print(f"  ✓ Respuesta de {sender} → lead {lead_id}")
                mark_replied(lead_id)
                replied += 1
                break

    mail.logout()
    print(f"\n✅ {replied} respuestas detectadas y marcadas.")


if __name__ == "__main__":
    run()
