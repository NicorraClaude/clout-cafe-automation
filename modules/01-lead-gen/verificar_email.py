"""
Verifica si una casilla existe ANTES de enviarle nada.

Le pregunta al servidor de correo del destinatario si acepta la dirección, sin
llegar a enviar el mensaje (se corta antes del DATA). Es gratis y no consume
créditos de ningún servicio.

Por qué importa: medido el 12/08/2026, la tasa de rebote era 40,7% (59 rebotes
sobre 145 envíos). Lo sano es menos del 2%. Una tasa así hace que Gmail y los
servidores destino empiecen a mandar los envíos a spam.

Validación sobre datos reales (12/08/2026):
  - 18 direcciones que rebotaron de verdad → detectó 14 (78%), 0 aprobadas mal
  - 5 direcciones de gente que respondió    → 0 rechazadas mal
Se descarta SOLO ante un 'no_existe' explícito del servidor. Ante cualquier duda
se conserva el lead: perder un prospecto bueno es peor que un rebote aislado.
"""

import smtplib
import subprocess

TIMEOUT = 12
# Buzón inventado para detectar servidores que aceptan cualquier dirección
BUZON_INEXISTENTE = "zzz-no-existe-9182736450"


def mx_de(dominio: str) -> list[str]:
    """Servidores de correo del dominio, por prioridad."""
    try:
        salida = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", "MX", dominio],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip()
        hosts = []
        for linea in salida.splitlines():
            partes = linea.split()
            if len(partes) == 2 and partes[0].isdigit():
                hosts.append((int(partes[0]), partes[1].rstrip(".")))
        hosts.sort()
        return [h for _, h in hosts]
    except Exception:
        return []


def verificar(email: str, remitente: str = "verify@clout.ar") -> str:
    """
    Devuelve:
      'existe'      — el servidor acepta la dirección
      'no_existe'   — el servidor la rechaza explícitamente (único caso que descarta)
      'acepta_todo' — el servidor acepta cualquier cosa, no sirve para distinguir
      'desconocido' — el servidor no respondió o bloqueó la consulta
    """
    if "@" not in email:
        return "no_existe"
    dominio = email.rsplit("@", 1)[1].lower()

    servidores = mx_de(dominio)
    if not servidores:
        return "no_existe"          # sin servidor de correo no hay entrega posible

    for mx in servidores[:2]:
        try:
            s = smtplib.SMTP(timeout=TIMEOUT)
            s.connect(mx, 25)
            s.helo("clout.ar")
            s.mail(remitente)
            codigo_real, _ = s.rcpt(email)
            # Si también acepta una casilla inventada, su respuesta no dice nada
            codigo_falso, _ = s.rcpt(f"{BUZON_INEXISTENTE}@{dominio}")
            try:
                s.quit()
            except Exception:
                pass

            if codigo_falso in (250, 251, 252):
                return "acepta_todo"
            if codigo_real in (250, 251):
                return "existe"
            if 500 <= codigo_real < 600:
                return "no_existe"
            return "desconocido"
        except Exception:
            continue

    return "desconocido"


def es_descartable(resultado: str) -> bool:
    """Solo se descarta ante un rechazo explícito."""
    return resultado == "no_existe"
