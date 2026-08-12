"""
Módulo 02 — Email outreach automatizado.
Envía emails desde cafeclout@gmail.com a leads en estado 'encolado'.
Respeta límite de 50/día, solo L-V 09:00-17:00 ART.
"""

import os, smtplib, time, psycopg2, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

GMAIL_USER   = os.environ["GMAIL_USER"]
GMAIL_PASS   = os.environ["GMAIL_APP_PASSWORD"]
DB_HOST      = os.environ["SUPABASE_DB_HOST"]
DB_PASS      = os.environ["SUPABASE_DB_PASS"]

ART = ZoneInfo("America/Argentina/Buenos_Aires")
MAX_PER_DAY  = 50
MAX_FOLLOWUPS_PER_DAY = 20   # el resto del cupo queda libre para prospectos nuevos
DELAY_SECS   = 45   # pausa entre emails para evitar spam scoring
MAX_REINTENTOS = 3  # reintentos ante caída de conexión (no cuenta errores de dirección)

# Rubros que reciben oferta gastronómica (comodato de máquina)
RUBROS_GASTRO = {"restaurante", "bar", "hotel", "cafe", "catering", "salon_eventos",
                 "club", "museo_cultura", "panaderia", "gimnasio", "clinica_salud", "educacion"}

# Rubros que reciben oferta corporativa (vending)
RUBROS_CORP = {"empresa_corporativo", "coworking", "oficina"}


class ConexionCaida(Exception):
    """La conexión SMTP se cortó — hay que reconectar, no descartar el lead."""


# Fallos que indican conexión rota (no un problema con la dirección destino)
ERRORES_DE_CONEXION = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    TimeoutError,
    OSError,
)


def is_corp(rubro: str) -> bool:
    return rubro in RUBROS_CORP


TEMPLATES_GASTRO = {
    1: {
        "subject": "Café de especialidad y comercial para {nombre_lugar} — dos opciones sin vueltas",
        "body": """Hola {nombre_contacto},

Soy Belén, de Clout Café. Somos un tostadero artesanal de Buenos Aires — nos dedicamos exclusivamente al café, y eso se nota en el producto y en el servicio.

Te escribo porque creemos que {nombre_lugar} puede tomar mejor café y pagar menos por él.

Tenemos dos opciones:

OPCIÓN A — SOLO EL CAFÉ
Si ya tienen máquina, nosotros proveemos el café — de especialidad o comercial, según lo que necesiten. Entrega semanal, tostado fresco, trato directo. A mayor volumen, mejor precio.

OPCIÓN B — MÁQUINA EN COMODATO + CAFÉ
Comprando 30 kg o más por mes, instalamos una máquina de espresso sin costo adicional. Ustedes solo pagan el café, nosotros nos encargamos del resto.

En clout.ar vas a poder ver las opciones disponibles. Si alguna te interesa, podemos hablar 5 minutos para adaptar la propuesta a lo que necesiten y contarte sobre los precios mayoristas.

Belén · Clout Café
wa.me/5491163729303
cafeclout@gmail.com""",
    },
    2: {
        "subject": "Re: Clout Café — propuesta para {nombre_lugar}",
        "body": """{nombre_contacto}, quería asegurarme de que llegó mi mensaje.

Sé que un {rubro} no para, así que lo resumo en dos líneas:

— Solo el café: precio mayorista, entrega semanal, sin contrato. A mayor volumen, mejor precio.
— Café + máquina: 30 kg/mes y les dejamos una máquina de espresso en comodato.

No cobramos lo que no vale. Si hoy están pagando más por menos calidad, tiene sentido que lo comparemos.

Puedo mandar muestras sin cargo para que lo prueben antes de decidir cualquier cosa.

Belén · Clout Café
wa.me/5491163729303""",
    },
    3: {
        "subject": "Última consulta — {nombre_lugar}",
        "body": """{nombre_contacto}, este es mi último mensaje para no saturarte.

Si en algún momento quieren optimizar el café — ya sea bajando costos, mejorando la calidad, o ambas — saben dónde encontrarnos.

Una sola pregunta antes de cerrar: ¿qué es lo que hoy les frena para cambiar de proveedor? Precio, logística, la máquina actual... Me ayuda saberlo.

Belén · Clout Café
cafeclout@gmail.com · wa.me/5491163729303""",
    },
}

TEMPLATES_CORP = {
    1: {
        "subject": "Café para {nombre_lugar} — dos opciones sin vueltas",
        "body": """Hola {nombre_contacto},

Soy Belén, de Clout Café. Somos un tostadero artesanal de Buenos Aires — nos dedicamos exclusivamente al café, y sabemos lo que significa dar un buen servicio.

Te escribo porque {nombre_lugar} puede tomar mejor café, pagar menos por él, y no tener que gestionar nada. Las tres cosas a la vez.

Tenemos dos opciones:

OPCIÓN A — SOLO EL CAFÉ
Si ya tienen máquina o cafetera, les proveemos café de especialidad o comercial a precio mayorista. Tostado fresco, entrega directa, sin intermediarios. A mayor volumen, mejor precio.

OPCIÓN B — SERVICIO DE VENDING COMPLETO
Instalamos una máquina de espresso automática, la mantenemos, y reponemos el café cada semana. El equipo toma buen café sin que nadie tenga que gestionar nada.

En nuestra web vas a poder ver todas las opciones disponibles y los precios de referencia: clout.ar

Si alguna opción te interesa, podemos hablar 5 minutos y nos adaptamos a lo que necesiten.

Belén · Clout Café
wa.me/5491163729303
cafeclout@gmail.com""",
    },
    2: {
        "subject": "Re: Café para {nombre_lugar} — retomo la propuesta",
        "body": """{nombre_contacto}, te escribí la semana pasada, quería retomar.

Dos opciones para {nombre_lugar}:

— Solo el café a precio mayorista, con entrega directa. A mayor volumen, mejor precio. Sin compromiso, sin contrato.
— Vending completo: máquina instalada + café + mantenimiento + reposición semanal.

La diferencia respecto al proveedor actual: café tostado en Buenos Aires esa semana, no importado con meses de viaje. Y precios sin el margen inflado de las marcas grandes.

¿Charlamos?

Belén · Clout Café
wa.me/5491163729303""",
    },
    3: {
        "subject": "Última consulta — {nombre_lugar}",
        "body": """{nombre_contacto}, este es mi último mensaje.

Si en algún momento buscan optimizar el café de {nombre_lugar} — mejor calidad, menor costo, o las dos — ya saben dónde estamos.

Antes de cerrar: ¿cómo resuelven hoy el café en la oficina? Me ayuda para la próxima propuesta.

Belén · Clout Café
cafeclout@gmail.com · wa.me/5491163729303""",
    },
}


def get_templates(rubro: str) -> dict:
    return TEMPLATES_CORP if is_corp(rubro) else TEMPLATES_GASTRO


TEMPLATES = TEMPLATES_GASTRO  # default para compatibilidad


def db_conn():
    return psycopg2.connect(
        host=os.environ.get("SUPABASE_DB_HOST", DB_HOST), port=int(os.environ.get("SUPABASE_DB_PORT", 5432)), dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"), password=DB_PASS, sslmode="require"
    )


# ── Candado global de envío ──────────────────────────────────────────────────
# Impide que dos procesos envíen a la vez. Sin esto, dos schedulers corriendo en
# paralelo leen el mismo cupo diario, toman los mismos leads y el contacto recibe
# el email duplicado (pasó el 12/08/2026: 32 duplicados con GitHub + cron local).
# El candado vive en Postgres, así que funciona aunque los procesos estén en
# máquinas distintas. Se libera solo al cerrar la conexión (o si el proceso muere).
LOCK_KEY = 918273645

_lock_conn = None


def adquirir_lock() -> bool:
    """True si tomamos el candado; False si ya hay otro envío en curso."""
    global _lock_conn
    try:
        _lock_conn = db_conn()
        _lock_conn.autocommit = True
        cur = _lock_conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        obtenido = cur.fetchone()[0]
        cur.close()
        if not obtenido:
            _lock_conn.close()
            _lock_conn = None
        return obtenido
    except Exception as e:
        print(f"  No se pudo tomar el candado: {e}")
        _lock_conn = None
        return False


def liberar_lock():
    global _lock_conn
    if _lock_conn is not None:
        try:
            _lock_conn.close()   # cerrar la sesión libera el candado
        except Exception:
            pass
        _lock_conn = None


def conectar_smtp() -> smtplib.SMTP_SSL:
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45)
    smtp.login(GMAIL_USER, GMAIL_PASS)
    return smtp


def is_business_hours() -> bool:
    now = datetime.datetime.now(ART)
    return now.weekday() < 5 and 9 <= now.hour < 17


def emails_sent_today() -> int:
    conn = db_conn()
    cur = conn.cursor()
    today = datetime.date.today()
    cur.execute("""
        SELECT COUNT(*) FROM email_logs
        WHERE enviado_at::date = %s
    """, (today,))
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return count


def followups_sent_today() -> int:
    """Follow-ups (email #2 y #3) ya enviados hoy — para respetar su tope propio."""
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM email_logs
        WHERE enviado_at::date = %s AND email_num > 1
    """, (datetime.date.today(),))
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return count


def get_leads_to_contact(email_num: int, limit: int) -> list[dict]:
    """
    email_num=1 → estado='encolado'
    email_num=2 → estado='email_1_enviado' y email_1_at < ahora - 4 días
    email_num=3 → estado='email_2_enviado' y email_2_at < ahora - 5 días
    """
    conn = db_conn()
    cur = conn.cursor()

    # Empresas donde ALGUIEN ya respondió: no se contacta a nadie más de ahí.
    # Última línea de defensa por si la detección de respuestas falló.
    NO_CONTACTAR_DOMINIO = """
        AND lower(split_part(l.email, '@', 2)) NOT IN (
            SELECT lower(split_part(email, '@', 2)) FROM leads
            WHERE (estado = 'respondio' OR respondio_at IS NOT NULL)
              AND email IS NOT NULL
              AND lower(split_part(email, '@', 2)) NOT IN (
                  'gmail.com','hotmail.com','outlook.com','yahoo.com','yahoo.com.ar',
                  'live.com','icloud.com','me.com','aol.com','protonmail.com',
                  'hotmail.com.ar','outlook.com.ar','yahoo.es'
              )
        )
    """

    if email_num == 1:
        cur.execute(f"""
            SELECT l.id, l.nombre_contacto, l.nombre_lugar, l.email, l.rubro, l.thread_id
            FROM leads l WHERE l.estado = 'encolado'
              {NO_CONTACTAR_DOMINIO}
            ORDER BY l.created_at LIMIT %s
        """, (limit,))
    elif email_num == 2:
        # respondio_at IS NULL: red de seguridad extra por si check_replies falló
        # y el estado quedó desactualizado. Nunca follow-up a quien ya contestó.
        cur.execute(f"""
            SELECT l.id, l.nombre_contacto, l.nombre_lugar, l.email, l.rubro, l.thread_id
            FROM leads l
            WHERE l.estado = 'email_1_enviado'
              AND l.email_1_at < now() - interval '4 days'
              AND l.respondio_at IS NULL
              {NO_CONTACTAR_DOMINIO}
            ORDER BY l.email_1_at LIMIT %s
        """, (limit,))
    elif email_num == 3:
        cur.execute(f"""
            SELECT l.id, l.nombre_contacto, l.nombre_lugar, l.email, l.rubro, l.thread_id
            FROM leads l
            WHERE l.estado = 'email_2_enviado'
              AND l.email_2_at < now() - interval '5 days'
              AND l.respondio_at IS NULL
              {NO_CONTACTAR_DOMINIO}
            ORDER BY l.email_2_at LIMIT %s
        """, (limit,))

    rows = cur.fetchall()
    cur.close(); conn.close()
    return [
        {"id": r[0], "nombre_contacto": r[1] or "equipo",
         "nombre_lugar": r[2], "email": r[3],
         "rubro": r[4] or "negocio", "thread_id": r[5]}
        for r in rows
    ]


def render(template: dict, lead: dict) -> tuple[str, str]:
    ctx = {
        "nombre_contacto": (lead["nombre_contacto"] or "equipo").split()[0].capitalize(),
        "nombre_lugar": lead["nombre_lugar"],
        "rubro": lead["rubro"] or "negocio",
    }
    subject = template["subject"].format(**ctx)
    body    = template["body"].format(**ctx)
    return subject, body


def send_email(lead: dict, email_num: int, smtp: smtplib.SMTP_SSL) -> str | None:
    """Envía el email y devuelve el Message-ID para trackear el thread."""
    templates = get_templates(lead.get("rubro") or "restaurante")
    tmpl = templates[email_num]
    subject, body = render(tmpl, lead)

    msg = MIMEMultipart("alternative")
    msg["From"]    = formataddr(("Belén · Clout Café", GMAIL_USER))
    msg["To"]      = lead["email"]
    msg["Subject"] = subject
    msg_id = make_msgid(domain="gmail.com")
    msg["Message-ID"] = msg_id

    # Follow-ups van en el mismo hilo
    if email_num > 1 and lead.get("thread_id"):
        msg["In-Reply-To"] = lead["thread_id"]
        msg["References"]  = lead["thread_id"]

    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        smtp.sendmail(GMAIL_USER, lead["email"], msg.as_string())
        return msg_id
    except ERRORES_DE_CONEXION as e:
        # La conexión murió: no es culpa de este lead. Se propaga para que el
        # bucle reconecte y lo reintente, en vez de darlo por fallido.
        raise ConexionCaida(str(e)) from e
    except Exception as e:
        print(f"  ✗ Error enviando a {lead['email']}: {e}")
        return None


def update_lead(lead_id: str, email_num: int, msg_id: str | None):
    conn = db_conn()
    cur = conn.cursor()
    now = datetime.datetime.now(ART)

    estado_map = {1: "email_1_enviado", 2: "email_2_enviado", 3: "email_3_enviado"}
    at_col_map = {1: "email_1_at",      2: "email_2_at",      3: "email_3_at"}

    cur.execute(f"""
        UPDATE leads
        SET estado = %s, {at_col_map[email_num]} = %s,
            thread_id = COALESCE(thread_id, %s), updated_at = now()
        WHERE id = %s
    """, (estado_map[email_num], now, msg_id, lead_id))

    cur.execute("""
        INSERT INTO email_logs (lead_id, email_num, gmail_message_id, enviado_at)
        VALUES (%s, %s, %s, now())
    """, (lead_id, email_num, msg_id))

    conn.commit()
    cur.close(); conn.close()


def run(email_num: int = 1, dry_run: bool = False, force_hours: bool = False):
    """
    email_num:   1 = inicial, 2 = follow-up 1, 3 = follow-up 2
    dry_run:     True = simular sin enviar
    force_hours: True = ignorar chequeo de horario (para GitHub Actions)
    """
    if not force_hours and not is_business_hours() and not dry_run:
        print("⏰ Fuera de horario comercial (L-V 09:00-17:00 ART). Abortando.")
        return

    sent_today = emails_sent_today()
    remaining  = MAX_PER_DAY - sent_today
    if remaining <= 0 and not dry_run:
        print(f"🚫 Límite diario alcanzado ({MAX_PER_DAY}/día). Abortando.")
        return

    # Los follow-ups no pueden comerse todo el cupo: se les reserva como máximo
    # MAX_FOLLOWUPS_PER_DAY para que siempre queden lugares para prospectos nuevos.
    # Se descuentan los follow-ups ya enviados hoy (puede haber corridas previas).
    if email_num > 1:
        fu_restantes = MAX_FOLLOWUPS_PER_DAY - followups_sent_today()
        if fu_restantes <= 0 and not dry_run:
            print(f"📭 Tope de follow-ups alcanzado ({MAX_FOLLOWUPS_PER_DAY}/día). "
                  f"El cupo restante queda para prospectos nuevos.")
            return
        remaining = min(remaining, fu_restantes)

    limit  = min(remaining, MAX_PER_DAY) if not dry_run else 5
    leads  = get_leads_to_contact(email_num, limit)

    print(f"\n📧 Email #{email_num} — {len(leads)} leads a contactar {'[DRY RUN]' if dry_run else ''}")
    print(f"   Enviados hoy: {sent_today}/{MAX_PER_DAY}")

    if not leads:
        print("   Sin leads pendientes para este email.")
        return

    if dry_run:
        for lead in leads:
            tmpl = get_templates(lead.get("rubro") or "restaurante")[email_num]
            subj, body = render(tmpl, lead)
            print(f"\n  → {lead['email']} ({lead['nombre_lugar']}) [{lead.get('rubro','')}]")
            print(f"     Asunto: {subj}")
            print(f"     Primeras líneas: {body[:80].strip()}...")
        return

    sent = failed = 0
    sent_details = []
    failed_details = []

    smtp = conectar_smtp()
    try:
        for lead in leads:
            print(f"  → {lead['email']} ({lead['nombre_lugar']})...", end=" ", flush=True)

            msg_id = None
            for intento in range(1, MAX_REINTENTOS + 1):
                try:
                    msg_id = send_email(lead, email_num, smtp)
                    break
                except ConexionCaida as e:
                    print(f"\n     ⚠️  Conexión caída ({e}). Reconectando "
                          f"[{intento}/{MAX_REINTENTOS}]...", flush=True)
                    try:
                        smtp.quit()
                    except Exception:
                        pass
                    time.sleep(10 * intento)   # espera creciente
                    try:
                        smtp = conectar_smtp()
                        print("     ✓ Reconectado, reintentando", end=" ", flush=True)
                    except Exception as e2:
                        print(f"     ✗ No se pudo reconectar: {e2}", flush=True)

            if msg_id:
                update_lead(lead["id"], email_num, msg_id)
                print("✓", flush=True)
                sent += 1
                sent_details.append(lead)
            else:
                failed += 1
                failed_details.append(lead)
            time.sleep(DELAY_SECS)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    print(f"\n✅ Enviados: {sent} | Fallidos: {failed}")

    if sent > 0 or failed > 0:
        _send_report_to_self(email_num, sent_details, failed_details)


def _send_report_to_self(email_num: int, sent_list: list, failed_list: list):
    """Envía resumen del batch a cafeclout@gmail.com."""
    tipo = {1: "Email inicial", 2: "Follow-up 1", 3: "Follow-up 2"}.get(email_num, f"Email #{email_num}")
    now_str = datetime.datetime.now(ART).strftime("%d/%m/%Y %H:%M")

    lines = [f"REPORTE OUTREACH — {tipo}", f"Clout Café · {now_str}", "=" * 48, ""]
    lines.append(f"✅ Enviados: {len(sent_list)}")
    lines.append(f"❌ Fallidos: {len(failed_list)}")
    lines.append("")

    if sent_list:
        lines.append("ENVIADOS:")
        for l in sent_list:
            lines.append(f"  · {l['nombre_lugar']} — {l['email']}")
        lines.append("")

    if failed_list:
        lines.append("FALLIDOS:")
        for l in failed_list:
            lines.append(f"  · {l['nombre_lugar']} — {l['email']}")
        lines.append("")

    lines.append("Ver base completa en: panel.clout.ar")

    body = "\n".join(lines)
    subject = f"[Outreach] {tipo} — {len(sent_list)} enviados · {now_str}"

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Clout Café Bot", GMAIL_USER))
    msg["To"] = GMAIL_USER
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        print(f"  📩 Reporte enviado a {GMAIL_USER}")
    except Exception as e:
        print(f"  Reporte email error: {e}")


if __name__ == "__main__":
    import sys
    num     = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    dry     = "--dry" in sys.argv
    run(email_num=num, dry_run=dry)
