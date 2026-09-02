"""
Avisos de salud del sistema.

Nacieron de un problema concreto: entre el 21/08 y el 02/09/2026 el outreach
estuvo doce días parado y nadie se enteró, porque el fallo quedaba tapado en los
logs. La regla acá es que todo lo que deje el sistema sin funcionar tiene que
llegar por mail a una persona.

Cada tipo de aviso se manda UNA VEZ POR DÍA, para que un problema que se repite
en cada corrida no llene la casilla.
"""

import os, smtplib, datetime
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASSWORD"]
AVISOS_A = ["nicorra@gmail.com", "cafeclout@gmail.com"]


def db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ.get("SUPABASE_DB_PORT", 5432)),
        dbname="postgres",
        user=os.environ.get("SUPABASE_DB_USER", "postgres"),
        password=os.environ["SUPABASE_DB_PASS"],
        sslmode="require", connect_timeout=20,
    )


def _crear_tabla(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alertas_enviadas (
            tipo   text NOT NULL,
            dia    date NOT NULL,
            PRIMARY KEY (tipo, dia)
        )
    """)


def _marcar(tipo: str) -> bool:
    """True si es la primera vez hoy que se avisa de esto."""
    try:
        conn = db_conn(); cur = conn.cursor()
        _crear_tabla(cur)
        cur.execute(
            "INSERT INTO alertas_enviadas (tipo, dia) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING", (tipo, datetime.date.today()))
        primera = cur.rowcount > 0
        conn.commit(); cur.close(); conn.close()
        return primera
    except Exception:
        return True     # ante la duda, avisar


def avisar(tipo: str, titulo: str, detalle: str, que_hacer: str) -> bool:
    """Manda el aviso salvo que ya se haya mandado hoy uno del mismo tipo."""
    if not _marcar(tipo):
        return False

    cuerpo = f"""{titulo}

QUÉ PASÓ
{detalle}

QUÉ HAY QUE HACER
{que_hacer}

—
Aviso automático de Clout Café · {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}
Se manda una sola vez por día por cada tipo de problema.
"""
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("Clout Café · Avisos", GMAIL_USER))
    msg["To"] = ", ".join(AVISOS_A)
    msg["Subject"] = f"⚠️ {titulo}"
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, AVISOS_A, msg.as_string())
        print(f"  📨 Aviso enviado: {titulo}")
        return True
    except Exception as e:
        print(f"  ✗ No se pudo enviar el aviso: {e}")
        return False


# ── Avisos concretos ─────────────────────────────────────────────────────────

def sin_credito_claude(detalle: str):
    avisar(
        "credito_claude",
        "Se acabó el crédito de Claude — las respuestas automáticas están paradas",
        f"La API de Claude rechazó la consulta por falta de crédito.\n\n{detalle[:400]}\n\n"
        "Mientras tanto, las consultas de clientes NO se están respondiendo solas.\n"
        "Quedan en la bandeja de cafeclout@gmail.com esperando respuesta manual.",
        "Cargar crédito en platform.claude.com → Facturación.\n"
        "Conviene activar la recarga automática para que no vuelva a cortarse.",
    )


def credito_bajo(restante_usd: float, umbral: float):
    avisar(
        "credito_bajo",
        f"Queda poco crédito de Claude: US$ {restante_usd:.2f}",
        f"El crédito bajó de US$ {umbral:.2f}. Cada respuesta automática cuesta "
        f"entre 1 y 2 centavos, así que quedan unas "
        f"{int(restante_usd / 0.015)} respuestas aproximadamente.",
        "Cargar crédito en platform.claude.com → Facturación, o activar la "
        "recarga automática.",
    )


def gmail_rechazado(detalle: str):
    avisar(
        "gmail_credenciales",
        "Gmail rechaza las credenciales — el outreach está parado",
        f"No se pudo iniciar sesión en {GMAIL_USER}.\n\n{detalle[:300]}\n\n"
        "No se está enviando ningún email ni leyendo respuestas.",
        "Generar una contraseña de aplicación nueva EN LA CUENTA cafeclout@gmail.com\n"
        "(no en la personal) desde myaccount.google.com/apppasswords, y actualizar\n"
        "el secret GMAIL_APP_PASSWORD del repositorio clout-cafe-automation.",
    )


def cola_vacia(quedan: int):
    avisar(
        "cola_baja",
        f"Quedan pocos prospectos sin contactar: {quedan}",
        f"La cola tiene {quedan} leads, menos de {quedan // 30 if quedan >= 30 else 0} "
        f"días de envíos. El sistema busca contactos nuevos todos los días, pero "
        f"está consumiendo más rápido de lo que encuentra.",
        "Revisar que Google Maps siga trayendo leads (la API de Google tiene un "
        "crédito mensual de US$200), o recargar créditos de Apollo.",
    )
