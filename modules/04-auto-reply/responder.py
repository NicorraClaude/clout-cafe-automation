"""
Módulo 04 — Respuestas automáticas a consultas de prospectos.

Lee las respuestas que llegan al outreach y contesta las que puede responder con
los datos que tenemos. Cuando hay cualquier duda, no improvisa: avisa por mail
para que la conteste una persona.

Reglas de seguridad, en orden de importancia:
  1. Nunca inventar. Si el dato no está en la base de conocimiento, se escala.
  2. Nunca responder dos veces al mismo mensaje.
  3. Nunca responder a rebotes, autorespuestas ni casillas no-reply.
  4. Nunca hablar de costos ni márgenes.
"""

import os, re, json, imaplib, smtplib, email, datetime, importlib.util
import urllib.request, ssl
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid, parseaddr
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASSWORD"]
CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# A dónde avisar cuando el sistema no sabe algo
AVISOS_A = ["nicorra@gmail.com", "cafeclout@gmail.com"]

MODELO = "claude-sonnet-4-5"
MAX_POR_CORRIDA = 15          # tope de respuestas por ejecución
DIAS_ATRAS = 3                # ventana de bandeja a revisar

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

REMITENTES_A_IGNORAR = (
    "mailer-daemon", "postmaster", "no-reply", "noreply", "donotreply",
    "notifications@", "notification@", "info@google", "@google.com",
)
ASUNTOS_A_IGNORAR = (
    "out of office", "fuera de la oficina", "auto", "automatic reply",
    "vacaciones", "undelivered", "delivery status", "no se pudo entregar",
)


class SinCredito(Exception):
    """Anthropic rechazó la consulta por falta de crédito."""


def _cargar_alertas():
    ruta = os.path.join(os.path.dirname(__file__), "alertas.py")
    spec = importlib.util.spec_from_file_location("_ale", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ.get("SUPABASE_DB_PORT", 5432)),
        dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"),
        password=os.environ["SUPABASE_DB_PASS"],
        sslmode="require", connect_timeout=20,
    )


def _cargar_conocimiento():
    ruta = os.path.join(os.path.dirname(__file__), "conocimiento.py")
    spec = importlib.util.spec_from_file_location("_con", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Registro de lo ya respondido ─────────────────────────────────────────────

def crear_tabla():
    """Guarda qué mensajes ya se procesaron, para no contestar dos veces."""
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS respuestas_auto (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gmail_msg_id    text UNIQUE NOT NULL,
            lead_id         uuid REFERENCES leads(id),
            de              text,
            asunto          text,
            accion          text,          -- 'respondido' | 'escalado' | 'ignorado'
            motivo          text,
            respuesta       text,
            creado_at       timestamptz DEFAULT now()
        )
    """)
    conn.commit(); cur.close(); conn.close()


def ya_procesado(msg_id: str) -> bool:
    conn = db_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM respuestas_auto WHERE gmail_msg_id = %s", (msg_id,))
    r = cur.fetchone() is not None
    cur.close(); conn.close()
    return r


def registrar(msg_id, lead_id, de, asunto, accion, motivo=None, respuesta=None):
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO respuestas_auto (gmail_msg_id, lead_id, de, asunto, accion, motivo, respuesta)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (gmail_msg_id) DO NOTHING
    """, (msg_id, lead_id, de, asunto, accion, motivo, respuesta))
    conn.commit(); cur.close(); conn.close()


# ── Decidir qué contestar ────────────────────────────────────────────────────

INSTRUCCIONES = """Sos Belén, de Clout Café, un tostadero de Buenos Aires. Respondés
por email a consultas de comercios y empresas que recibieron nuestro mensaje.

REGLA PRINCIPAL, POR ENCIMA DE TODO: no inventes NADA. Solo podés afirmar lo que
está textualmente en la INFORMACIÓN DISPONIBLE de abajo. Si la consulta pide un
dato que no está ahí —un precio que no figura, un plazo, un descuento especial,
una condición distinta, disponibilidad de stock, algo de facturación, el precio de
los extras, un envío al interior— NO respondas: escalá.

Ante la más mínima duda, escalá. Es mucho peor mandar un dato equivocado a un
cliente que demorar la respuesta unas horas.

NO DES POR SENTADA LA SITUACIÓN DEL CLIENTE. Antes de responder, preguntate:
¿estoy suponiendo algo que el mensaje no dice? Si la respuesta depende de si
tienen o no una máquina, de cuántas sucursales manejan, de qué consumo tienen o
de con quién trabajan hoy, y el mensaje no lo aclara sin lugar a dudas, ESCALÁ.

Ejemplo real de un error a evitar: un cliente escribió que "una empresa nos
provee máquinas Bunn en concesión". Eso significa que NO son dueños de las
máquinas: se las da un proveedor, y para cambiarse necesitarían que nosotros
hiciéramos lo mismo. Responder "como ya tienen las máquinas, les vendemos el
café" es leer al revés y perder el negocio.

ESCALÁ SIEMPRE, sin excepción, cuando:
· piden que proveamos máquinas, sobre todo si son varias o hay sucursales
· hoy trabajan con otro proveedor y evalúan cambiarse
· el pedido no encaja exactamente en alguno de los esquemas de comodato tal
  como están definidos
Esas son negociaciones que cierra Nico, no consultas de precio.

También escalá si:
· quieren cerrar una compra, coordinar una entrega o hablar de un contrato
· hay un reclamo, una queja o algo que suene delicado
· piden hablar por teléfono o reunirse
· la consulta es confusa o no se entiende qué necesitan
· responden algo que no es una consulta comercial
· es un acuse de recibo automático ("confirmamos recepción de su correo",
  "su mensaje fue recibido", "le responderemos a la brevedad"). Contestarle a
  un contestador automático no sirve para nada y puede generar un ida y vuelta
  entre robots. Esto vale SIEMPRE, aunque la consulta sea vieja: la disculpa
  por demora no es motivo para responderle a una máquina.

NUNCA menciones costos internos, márgenes ni cuánto nos cuesta el café.

Si la persona dice que no le interesa o que ya tiene proveedor: agradecé en una
línea, dejá la puerta abierta y no insistas. Eso se responde, no se escala.

TONO: rioplatense natural, directo y cordial. Sin exclamaciones de más, sin sonar
a robot ni a vendedor. Respuestas cortas: 2 a 5 líneas. Firmá siempre:

Belén · Clout Café
wa.me/5491163729303

Devolvé SOLO un objeto JSON, sin nada alrededor:
{"accion": "responder", "respuesta": "el texto del email"}
o
{"accion": "escalar", "motivo": "en una línea, qué dato falta o por qué no podés"}"""


# Rubros que reciben la propuesta gastronómica; el resto, la corporativa.
RUBROS_GASTRO = {"restaurante", "bar", "hotel", "cafe", "catering", "salon_eventos",
                 "club", "museo_cultura", "panaderia", "gimnasio", "clinica_salud",
                 "educacion"}


def tipo_de_cliente(rubro: str | None) -> str:
    """Determina qué versión de la propuesta recibió, para poder responder por ella."""
    if not rubro:
        return "sin dato — si la respuesta depende del rubro, escalá"
    if rubro in RUBROS_GASTRO:
        return f"COMERCIO GASTRONÓMICO (rubro: {rubro}) — recibió la propuesta gastronómica"
    return f"OFICINA / EMPRESA (rubro: {rubro}) — recibió la propuesta corporativa"


def dias_de_demora(msg) -> int:
    """Cuántos días pasaron desde que el cliente escribió."""
    from email.utils import parsedate_to_datetime
    try:
        fecha = parsedate_to_datetime(msg.get("Date"))
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - fecha).days
    except Exception:
        return 0


def decidir(consulta: str, de: str, empresa: str, contexto: str,
            rubro: str | None = None, demora_dias: int = 0) -> dict:
    # Si la consulta lleva más de una semana sin respuesta, se pide disculpas.
    # Sin exagerar: una línea al principio y seguir con la respuesta.
    nota_demora = ""
    if demora_dias >= 7:
        nota_demora = (
            f"\n\nATENCIÓN: esta consulta llegó hace {demora_dias} días y todavía no "
            "se respondió. Empezá el mail con una disculpa breve y sobria por la "
            "demora —una sola línea, sin dramatizar ni dar explicaciones— y seguí "
            "con la respuesta normal."
        )
    prompt = (
        f"INFORMACIÓN DISPONIBLE (esto es TODO lo que sabés):\n{contexto}\n\n"
        f"---\nConsulta recibida\nDe: {de}\nEmpresa: {empresa or 'sin dato'}\n"
        f"Tipo de cliente: {tipo_de_cliente(rubro)}\n\n"
        f"{consulta[:3000]}"
        + nota_demora
    )
    cuerpo = json.dumps({
        "model": MODELO,
        "max_tokens": 900,
        "system": INSTRUCCIONES,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=cuerpo,
        headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=90, context=CTX))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="ignore")[:500]
        # Anthropic devuelve 400 con "credit balance is too low" cuando se acaba
        if "credit balance" in detalle.lower() or "insufficient" in detalle.lower():
            raise SinCredito(detalle) from e
        raise
    texto = "".join(b.get("text", "") for b in resp.get("content", []))

    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        return {"accion": "escalar", "motivo": "no se pudo interpretar la respuesta del modelo"}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"accion": "escalar", "motivo": "respuesta del modelo mal formada"}

    if d.get("accion") == "responder" and not (d.get("respuesta") or "").strip():
        return {"accion": "escalar", "motivo": "el modelo devolvió una respuesta vacía"}
    return d


# ── Envío ────────────────────────────────────────────────────────────────────

def enviar(destino: str, asunto: str, cuerpo: str, in_reply_to: str | None = None) -> bool:
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Belén · Clout Café", GMAIL_USER))
    msg["To"] = destino
    msg["Subject"] = asunto if asunto.lower().startswith("re:") else f"Re: {asunto}"
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, destino, msg.as_string())
        return True
    except Exception as e:
        print(f"    ✗ no se pudo enviar a {destino}: {e}")
        return False


def resumen_de_lo_respondido(respuestas: list[dict]):
    """
    Copia a Nico de todo lo que el sistema contestó, con la consulta original
    al lado.

    No es para que apruebe nada —ya salió— sino para que pueda detectar a tiempo
    una respuesta mal interpretada y corregirla con el cliente el mismo día.
    """
    if not respuestas:
        return
    partes = [
        f"El sistema respondió {len(respuestas)} consulta(s) hoy.",
        "Si alguna quedó mal, todavía estás a tiempo de escribirle vos.",
        "",
    ]
    for i, r in enumerate(respuestas, 1):
        partes += [
            "=" * 62,
            f"{i}. {r['empresa'] or r['de']}  <{r['de']}>",
            "=" * 62,
            "",
            "LO QUE PREGUNTÓ",
            r["consulta"][:900].strip(),
            "",
            "LO QUE CONTESTÓ EL SISTEMA",
            r["respuesta"].strip(),
            "",
        ]
    cuerpo = "\n".join(partes)

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Clout Café · Avisos", GMAIL_USER))
    msg["To"] = ", ".join(AVISOS_A)
    msg["Subject"] = f"Respuestas enviadas hoy ({len(respuestas)})"
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, AVISOS_A, msg.as_string())
        print(f"  📋 Resumen de {len(respuestas)} respuestas enviado a Nico")
    except Exception as e:
        print(f"  ✗ No se pudo enviar el resumen: {e}")


def avisar(de: str, empresa: str, asunto: str, consulta: str, motivo: str):
    """Aviso a Nico cuando el sistema no sabe algo. Va a las dos casillas."""
    cuerpo = f"""Llegó una consulta que el sistema no puede responder solo.

POR QUÉ NO LA RESPONDIÓ
{motivo}

DE
{de}{f'  ({empresa})' if empresa else ''}

ASUNTO
{asunto}

CONSULTA
{'-' * 55}
{consulta[:2500]}
{'-' * 55}

Respondé directamente desde cafeclout@gmail.com: el mensaje original está en la
bandeja. El sistema no le contestó nada a esta persona.
"""
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Clout Café · Avisos", GMAIL_USER))
    msg["To"] = ", ".join(AVISOS_A)
    msg["Subject"] = f"[Responder a mano] {empresa or de}"
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, AVISOS_A, msg.as_string())
        print(f"    📨 aviso enviado a {', '.join(AVISOS_A)}")
    except Exception as e:
        print(f"    ✗ no se pudo avisar: {e}")


# ── Lectura de la bandeja ────────────────────────────────────────────────────

def texto_plano(msg) -> str:
    """Cuerpo del mensaje, sin la parte citada del email anterior."""
    cuerpo = ""
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain":
                try:
                    cuerpo += parte.get_payload(decode=True).decode(
                        parte.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        try:
            cuerpo = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            cuerpo = ""
    # Cortar la cita del mensaje original
    for marca in ("\nEl ", "\n>", "\nOn ", "\n-----", "\n________"):
        i = cuerpo.find(marca)
        if i > 60:
            cuerpo = cuerpo[:i]
    return cuerpo.strip()


def hay_que_ignorar(de: str, asunto: str) -> str | None:
    d, a = de.lower(), (asunto or "").lower()
    if any(x in d for x in REMITENTES_A_IGNORAR):
        return "remitente automático"
    if any(x in a for x in ASUNTOS_A_IGNORAR):
        return "autorespuesta o rebote"
    return None


def leads_por_email() -> dict:
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""SELECT lower(email), id, nombre_lugar, rubro
                   FROM leads WHERE email IS NOT NULL""")
    d = {e: (str(i), n, r) for e, i, n, r in cur.fetchall()}
    cur.close(); conn.close()
    return d


def run(dry_run: bool = False, dias: int = DIAS_ATRAS):
    if not CLAUDE_KEY:
        print("⚠️  Falta ANTHROPIC_API_KEY — no se pueden generar respuestas.")
        return

    crear_tabla()
    contexto = _cargar_conocimiento().armar_contexto()
    conocidos = leads_por_email()

    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(GMAIL_USER, GMAIL_PASS)
    m.select("INBOX")
    desde = (datetime.date.today() - datetime.timedelta(days=dias)).strftime("%d-%b-%Y")
    _, res = m.search(None, f"SINCE {desde}")
    ids = res[0].split()
    print(f"Revisando {len(ids)} mensajes de los últimos {dias} días"
          f"{' [SIMULACIÓN]' if dry_run else ''}")

    respondidos = escalados = 0
    enviadas = []
    for num in ids:
        if respondidos + escalados >= MAX_POR_CORRIDA:
            print(f"  Tope de {MAX_POR_CORRIDA} alcanzado; el resto queda para la próxima.")
            break
        try:
            _, data = m.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(data[0][1])
        except Exception:
            continue

        msg_id = msg.get("Message-ID", "")
        de_crudo = msg.get("From", "")
        _, de = parseaddr(de_crudo)
        asunto = msg.get("Subject", "") or "(sin asunto)"
        if not msg_id or not de:
            continue

        # Solo se contesta a gente a la que nosotros escribimos
        lead = conocidos.get(de.lower())
        if not lead:
            continue
        lead_id, empresa, rubro = lead

        motivo_ignorar = hay_que_ignorar(de_crudo, asunto)
        if motivo_ignorar:
            if not dry_run and not ya_procesado(msg_id):
                registrar(msg_id, lead_id, de, asunto, "ignorado", motivo_ignorar)
            continue

        if ya_procesado(msg_id):
            continue

        consulta = texto_plano(msg)
        if len(consulta) < 5:
            continue

        demora = dias_de_demora(msg)
        etiqueta = f"  ({demora} días sin responder)" if demora >= 7 else ""
        print(f"\n  → {empresa or de} <{de}>{etiqueta}")
        print(f"    {consulta[:110].replace(chr(10), ' ')}...")

        try:
            d = decidir(consulta, de, empresa, contexto, rubro,
                        dias_de_demora(msg))
        except SinCredito as e:
            # Sin crédito no se puede responder ninguna: se corta y se avisa.
            print("    ✗ Sin crédito de Claude — se detienen las respuestas")
            _cargar_alertas().sin_credito_claude(str(e))
            break
        except Exception as e:
            d = {"accion": "escalar", "motivo": f"error al consultar el modelo: {e}"}

        if d.get("accion") == "responder":
            print(f"    ✓ responde: {d['respuesta'][:90].replace(chr(10),' ')}...")
            if dry_run:
                respondidos += 1
            elif enviar(de, asunto, d["respuesta"], msg_id):
                registrar(msg_id, lead_id, de, asunto, "respondido",
                          respuesta=d["respuesta"])
                respondidos += 1
                enviadas.append({"de": de, "empresa": empresa,
                                 "consulta": consulta, "respuesta": d["respuesta"]})
        else:
            motivo = d.get("motivo", "sin motivo")
            print(f"    ⚠️  escala: {motivo}")
            if not dry_run:
                avisar(de, empresa, asunto, consulta, motivo)
                registrar(msg_id, lead_id, de, asunto, "escalado", motivo)
            escalados += 1

    m.logout()
    if not dry_run:
        resumen_de_lo_respondido(enviadas)
    print(f"\n✅ {respondidos} respondidas · {escalados} escaladas a Nico")
    return respondidos, escalados


if __name__ == "__main__":
    import sys
    run(dry_run="--dry" in sys.argv)
