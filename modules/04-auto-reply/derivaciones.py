"""
Módulo 04b — Derivaciones.

Cuando alguien contesta el outreach pasándonos el contacto de otra persona
("escribile a compras@empresa.com, él se encarga"), el sistema toma esa
dirección, la da de alta como lead y le manda el primer email de la secuencia
nombrando a quien lo derivó. A partir de ahí sigue el circuito normal: los
follow-ups 2 y 3 salen solos en los días que corresponden.

Reglas, en orden de importancia:
  1. Solo se deriva si quien escribe nos está pasando un contacto de verdad.
     Una dirección suelta en una firma o en un pie de página no alcanza: eso
     lo decide el modelo y después se vuelve a chequear acá.
  2. Nunca a una casilla nuestra, ni a la de quien escribe, ni a un no-reply.
  3. Nunca dos veces a la misma dirección: si ya está en la base, no se toca.
  4. Una derivación por mensaje. Si el mensaje trae tres contactos, se escala
     para que lo mire una persona.
"""

import os, re, datetime, importlib.util, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid

ROOT = os.path.join(os.path.dirname(__file__), "../..")

# Casillas propias: nunca nos escribimos a nosotros mismos.
PROPIAS = ("cafeclout@gmail.com", "nicorra@gmail.com", "pedidos@clout.ar", "@clout.ar")

NO_SIRVEN = ("no-reply", "noreply", "donotreply", "mailer-daemon", "postmaster",
             "notifications@", "notification@", "@sentry.", "@mailchimp")

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _mod(ruta: str, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, os.path.join(ROOT, ruta))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _send():
    return _mod("modules/02-email-outreach/send_emails.py", "_send_emails")


# ── Validaciones ─────────────────────────────────────────────────────────────

def direccion_valida(direccion: str, de_quien: str) -> str | None:
    """Devuelve el motivo por el que NO se puede derivar, o None si se puede."""
    d = (direccion or "").strip().lower()
    if not RE_EMAIL.match(d):
        return "la dirección no parece un email"
    if any(p in d for p in PROPIAS):
        return "es una casilla nuestra"
    if any(p in d for p in NO_SIRVEN):
        return "es una casilla que no recibe respuestas"
    if d == (de_quien or "").strip().lower():
        return "es la misma dirección de quien escribe"
    return None


def ya_en_la_base(conn, direccion: str):
    """El lead que ya existe con esa dirección, si existe."""
    cur = conn.cursor()
    cur.execute("SELECT id, estado FROM leads WHERE lower(email) = %s LIMIT 1",
                (direccion.strip().lower(),))
    fila = cur.fetchone()
    cur.close()
    return fila


# ── Alta del lead derivado ───────────────────────────────────────────────────

def crear_lead(conn, direccion: str, nombre: str | None, origen: dict) -> str:
    """
    Da de alta al contacto derivado, copiando los datos del comercio de quien
    lo derivó: es la misma empresa, así que el rubro y la zona son los mismos.
    """
    cur = conn.cursor()
    nota = (f"Derivado por {origen.get('nombre_contacto') or 'un contacto'} "
            f"<{origen['email']}> el {datetime.date.today().isoformat()}")
    cur.execute("""
        INSERT INTO leads (nombre_contacto, nombre_lugar, email, rubro, barrio, ciudad,
                           provincia, fuente, estado, notas, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'derivado','encolado',%s, now(), now())
        RETURNING id
    """, (nombre or "equipo", origen["nombre_lugar"], direccion.strip().lower(),
          origen.get("rubro"), origen.get("barrio"), origen.get("ciudad"),
          origen.get("provincia"), nota))
    nuevo = str(cur.fetchone()[0])
    conn.commit()
    cur.close()
    return nuevo


def datos_del_lead(conn, lead_id: str) -> dict:
    cur = conn.cursor()
    cur.execute("""SELECT id, nombre_contacto, nombre_lugar, email, rubro, barrio,
                          ciudad, provincia, thread_id
                   FROM leads WHERE id = %s""", (lead_id,))
    f = cur.fetchone()
    cur.close()
    if not f:
        return {}
    campos = ["id", "nombre_contacto", "nombre_lugar", "email", "rubro", "barrio",
              "ciudad", "provincia", "thread_id"]
    d = dict(zip(campos, f))
    d["id"] = str(d["id"])
    return d


# ── El primer email, con la derivación nombrada ──────────────────────────────

def cuerpo_con_derivacion(cuerpo: str, quien: str, empresa: str) -> str:
    """
    Mete una línea arriba de todo diciendo quién nos pasó el contacto.

    Va después del saludo para que se lea natural, y es lo primero que el
    destinatario tiene que entender: no es un email frío, lo mandó alguien de
    su propio equipo.
    """
    presentacion = (f"{quien} me pasó tu contacto para hablar del café de {empresa}."
                    if quien else f"Me pasaron tu contacto desde {empresa}.")
    lineas = cuerpo.split("\n")
    for i, l in enumerate(lineas):
        if l.strip().lower().startswith("hola"):
            return "\n".join(lineas[:i + 1] + ["", presentacion] + lineas[i + 1:])
    return f"{presentacion}\n\n{cuerpo}"


def enviar_primer_email(lead: dict, quien: str, empresa: str) -> str | None:
    """
    Manda el email 1 al contacto derivado y deja el estado como cualquier otro
    envío, para que los follow-ups sigan solos.
    """
    send = _send()
    plantilla = send.get_templates(lead.get("rubro") or "restaurante")[1]
    asunto, cuerpo = send.render(plantilla, lead)
    cuerpo = cuerpo_con_derivacion(cuerpo, quien, empresa)

    msg_id = make_msgid(domain="gmail.com")
    # Se reserva el cupo antes de mandar: si ya recibió el email 1, no se repite.
    if not send.reservar_envio(lead["id"], 1, msg_id):
        return None

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Belén · Clout Café", send.GMAIL_USER))
    msg["To"] = lead["email"]
    msg["Subject"] = asunto
    msg["Message-ID"] = msg_id
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    msg.attach(MIMEText(send.render_html(cuerpo, lead["id"], 1), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
            s.login(send.GMAIL_USER, send.GMAIL_PASS)
            s.sendmail(send.GMAIL_USER, lead["email"], msg.as_string())
    except Exception as e:
        send.marcar_fallido(lead["id"], 1, "fallido")
        print(f"    ✗ no se pudo escribirle a {lead['email']}: {e}")
        return None

    send.confirmar_envio(lead["id"], 1)
    send.update_lead(lead["id"], 1, msg_id)
    return msg_id


# ── Lo que usa el responder ──────────────────────────────────────────────────

def derivar(conn, direccion: str, nombre: str | None, origen: dict,
            dry_run: bool = False) -> tuple[bool, str]:
    """
    Alta y primer email al contacto derivado.
    Devuelve (si se hizo, qué pasó) para registrar y avisar.
    """
    motivo = direccion_valida(direccion, origen.get("email", ""))
    if motivo:
        return False, motivo

    existe = ya_en_la_base(conn, direccion)
    if existe:
        return False, f"ya estaba en la base ({existe[1]})"

    if dry_run:
        return True, f"[simulación] se le escribiría a {direccion}"

    lead_id = crear_lead(conn, direccion, nombre, origen)
    lead = datos_del_lead(conn, lead_id)
    quien = (origen.get("nombre_contacto") or "").split(" ")[0]
    if enviar_primer_email(lead, quien, origen["nombre_lugar"]):
        return True, f"primer email enviado a {direccion}"
    return False, f"no se pudo enviar el primer email a {direccion}"
