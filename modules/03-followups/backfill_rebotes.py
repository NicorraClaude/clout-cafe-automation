"""
Módulo 03 — Recuperar rebotes históricos (se corre una sola vez).

Hasta ahora check_replies descartaba los leads que rebotaban pero no guardaba
que había sido un rebote. Este script recorre los avisos de rebote de Gmail
(mailer-daemon / postmaster) desde el 01/07/2026, identifica a qué dirección no
se pudo entregar y completa leads.rebote_at y leads.rebote_motivo.

- Solo LEE Gmail (carpeta en modo lectura, BODY.PEEK): no marca nada como leído.
- Solo completa leads que todavía no tienen rebote_at. No toca el estado.
- Imprime solo cantidades, nunca la lista de emails.

Uso:  python modules/03-followups/backfill_rebotes.py [--dry]
"""

import os, re, imaplib, email, datetime, psycopg2
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, getaddresses
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASSWORD"]
DB_PASS    = os.environ["SUPABASE_DB_PASS"]

DESDE = "01-Jul-2026"
PATRON_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
PATRON_FINAL = re.compile(r"^(?:Final|Original)-Recipient:\s*(?:rfc822;)?\s*<?([^\s>;]+@[^\s>;]+)",
                          re.IGNORECASE | re.MULTILINE)
PATRON_ACCION = re.compile(r"^Action:\s*(\w+)", re.IGNORECASE | re.MULTILINE)


def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"], port=int(os.environ.get("SUPABASE_DB_PORT", 5432)),
        dbname="postgres", user=os.environ.get("SUPABASE_DB_USER", "postgres"),
        password=DB_PASS, sslmode="require"
    )


def carpeta_todos(mail: imaplib.IMAP4_SSL) -> str:
    """Busca la carpeta con el flag \\All ("Todos" o "All Mail" según el idioma)."""
    _, carpetas = mail.list()
    for linea in carpetas:
        linea = linea.decode(errors="replace")
        if "\\All" in linea:
            m = re.search(r'"([^"]+)"\s*$', linea) or re.search(r"(\S+)\s*$", linea)
            return m.group(1)
    return "[Gmail]/All Mail"


def texto_del_mensaje(msg) -> str:
    """Junta el texto de todas las partes, incluido el reporte técnico (DSN)."""
    trozos = []
    for parte in msg.walk():
        tipo = parte.get_content_type()
        if tipo == "message/delivery-status":
            # El reporte viene como una lista de bloques de cabeceras
            for bloque in parte.get_payload() or []:
                trozos.append(str(bloque))
        elif parte.get_content_maintype() == "text":
            try:
                datos = parte.get_payload(decode=True) or b""
                trozos.append(datos.decode(parte.get_content_charset() or "utf-8", errors="replace"))
            except Exception:
                pass
    return "\n".join(trozos)


def candidatos(msg, texto: str) -> list[str]:
    """Direcciones que podrían ser la que rebotó, de la más confiable a la menos."""
    lista = []
    for _, addr in getaddresses(msg.get_all("X-Failed-Recipients", [])):
        lista.append(addr)
    lista += PATRON_FINAL.findall(texto)
    lista += PATRON_EMAIL.findall(texto)
    return [a.lower().strip().strip(".") for a in lista if a]


def solo_demora(msg, texto: str) -> bool:
    """Avisos de "todavía intentando entregar": no son un rebote definitivo."""
    if msg.get("X-Failed-Recipients"):
        return False
    acciones = {a.lower() for a in PATRON_ACCION.findall(texto)}
    return bool(acciones) and acciones <= {"delayed"}


def run(dry_run: bool = False):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT lower(email), id FROM leads WHERE email IS NOT NULL")
    leads = {r[0].strip(): r[1] for r in cur.fetchall()}
    propio = GMAIL_USER.lower()

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    carpeta = carpeta_todos(mail)
    estado, _ = mail.select(f'"{carpeta}"', readonly=True)
    if estado != "OK":
        raise SystemExit(f"No se pudo abrir la carpeta {carpeta}")

    _, res = mail.search(None, f'(SINCE {DESDE} OR FROM "mailer-daemon" FROM "postmaster")')
    ids = res[0].split()

    # lead_id → (fecha, motivo); si un lead rebotó varias veces queda el más viejo
    rebotes: dict = {}
    demoras = sin_lead = 0
    for num in ids:
        try:
            _, data = mail.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(data[0][1])
        except Exception:
            continue
        texto = texto_del_mensaje(msg)
        if solo_demora(msg, texto):
            demoras += 1
            continue

        lead_id = next((leads[a] for a in candidatos(msg, texto)
                        if a != propio and a in leads), None)
        if not lead_id:
            sin_lead += 1
            continue

        try:
            fecha = parsedate_to_datetime(msg.get("Date", ""))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            fecha = datetime.datetime.now(datetime.timezone.utc)
        try:
            motivo = str(make_header(decode_header(msg.get("Subject", ""))))
        except Exception:
            motivo = msg.get("Subject", "")
        motivo = (motivo.strip() or "rebote")[:200]

        if lead_id not in rebotes or fecha < rebotes[lead_id][0]:
            rebotes[lead_id] = (fecha, motivo)
    mail.logout()

    actualizados = 0
    if not dry_run:
        for lead_id, (fecha, motivo) in rebotes.items():
            cur.execute("""
                UPDATE leads SET rebote_at = %s, rebote_motivo = %s
                WHERE id = %s AND rebote_at IS NULL
            """, (fecha, motivo, lead_id))
            actualizados += cur.rowcount
        conn.commit()
    cur.close(); conn.close()

    print(f"Avisos de rebote encontrados: {len(ids)}"
          f" (demoras sin rebote: {demoras}, sin lead asociado: {sin_lead})")
    print(f"Leads con rebote identificado: {len(rebotes)}")
    print(f"Leads actualizados: {actualizados}{' [DRY RUN]' if dry_run else ''}")


if __name__ == "__main__":
    import sys
    run(dry_run="--dry" in sys.argv)
