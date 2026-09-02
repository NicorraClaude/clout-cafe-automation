"""
Base de conocimiento para las respuestas automáticas.

Se lee del Google Sheet en cada ejecución, así los precios que responde el
sistema son siempre los vigentes: no hay una copia que se desactualice.

IMPORTANTE: de la planilla se toman ÚNICAMENTE las columnas de precio de venta.
Las de costo y margen no se leen nunca, para que no puedan filtrarse en una
respuesta a un cliente.
"""

import csv, io, re, ssl, urllib.request

SHEET_ID = "16vELUKxa6TYpPVMXvmd4iXwUPZEv5cVXd0reUj1zQb4"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"

# Solo estas columnas salen de la planilla. Cualquier otra queda afuera.
COLUMNAS_PERMITIDAS = {
    "CAFE",
    "PRECIO MINORISTA x 250gr",
    "PRECIO MINORISTA x kg",
    "PRECIO MAYORISTA x kg",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _num(txt: str):
    limpio = re.sub(r"[^\d,.-]", "", txt or "").replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def _pesos(valor) -> str:
    return f"${valor:,.0f}".replace(",", ".") if valor else "—"


_cache_filas = None


def _filas() -> list[list[str]]:
    """Baja la planilla una sola vez por ejecución."""
    global _cache_filas
    if _cache_filas is None:
        raw = urllib.request.urlopen(CSV_URL, timeout=30, context=CTX).read().decode("utf-8")
        _cache_filas = list(csv.reader(io.StringIO(raw)))
    return _cache_filas


def leer_precios() -> list[dict]:
    """Devuelve [{cafe, min250, minkg, maykg}] leyendo solo columnas de venta."""
    filas = _filas()

    encabezado = None
    for f in filas:
        if any(c.strip() == "CAFE" for c in f):
            encabezado = [c.strip() for c in f]
            break
    if not encabezado:
        raise RuntimeError("No se encontró la fila de encabezados en la planilla")

    idx = {c: i for i, c in enumerate(encabezado) if c in COLUMNAS_PERMITIDAS}
    if "CAFE" not in idx:
        raise RuntimeError("La planilla no tiene columna CAFE")

    salida = []
    empezo = False
    for f in filas:
        f = [c.strip() for c in f]
        if not f or len(f) <= idx["CAFE"]:
            continue
        nombre = f[idx["CAFE"]]
        if nombre == "CAFE":
            empezo = True
            continue
        if not empezo or not nombre:
            continue
        if nombre.upper() in ("COMERCIAL", "ESPECIALIDAD"):
            continue
        if any(p in nombre.upper() for p in ("COMODATO", "OFICINA", "GASTRONOM", "MAQUINA")):
            break
        fila = {
            "cafe": nombre,
            "min250": _num(f[idx["PRECIO MINORISTA x 250gr"]]) if "PRECIO MINORISTA x 250gr" in idx and idx["PRECIO MINORISTA x 250gr"] < len(f) else None,
            "minkg": _num(f[idx["PRECIO MINORISTA x kg"]]) if "PRECIO MINORISTA x kg" in idx and idx["PRECIO MINORISTA x kg"] < len(f) else None,
            "maykg": _num(f[idx["PRECIO MAYORISTA x kg"]]) if "PRECIO MAYORISTA x kg" in idx and idx["PRECIO MAYORISTA x kg"] < len(f) else None,
        }
        if fila["minkg"] or fila["maykg"]:
            salida.append(fila)
    return salida


def leer_comodato() -> list[dict]:
    """Esquemas de máquina en comodato, leídos de la planilla."""
    filas = _filas()
    inicio = None
    for i, f in enumerate(filas):
        if f and f[0].strip().upper().startswith("MAQUINAS COMODATO"):
            inicio = i + 1
            break
    if inicio is None:
        return []

    esquemas, tipo_actual = [], ""
    for f in filas[inicio:]:
        f = [c.strip() for c in f] + [""] * 6
        if f[0].upper().startswith("EXTRAS"):
            break
        if not any(f[:6]):
            continue
        if f[0]:
            tipo_actual = f[0]
        if not f[1]:
            continue
        esquemas.append({
            "tipo": tipo_actual,
            "maquina": f[1],
            "costo_maquina": f[2],
            "precio_cafe": f[3],
            "minimo": f[4],
            "extras": f[5],
        })
    return esquemas


def leer_extras() -> list[tuple[str, str]]:
    """Extras con su precio de venta. Solo nombre y precio: no hay costos acá."""
    filas = _filas()
    inicio = None
    for i, f in enumerate(filas):
        if f and f[0].strip().upper() == "EXTRAS":
            inicio = i + 1
            break
    if inicio is None:
        return []

    salida = []
    for f in filas[inicio:]:
        f = [c.strip() for c in f] + ["", ""]
        if not f[0]:
            continue
        if f[1]:
            salida.append((f[0], f[1]))
    return salida


ENVIOS = """ENVÍOS
· CABA y GBA: sin cargo en compras superiores a $200.000. Por debajo, con costo.
· Interior del país: disponible, pero el costo se cotiza según destino. Escalar.
· Plazo estimado: CABA/GBA 24-48 hs hábiles. Interior según provincia.
· El café se tuesta por encargo, así que puede haber 1-2 días antes del despacho."""

PAGOS = """PAGOS
MercadoPago (tarjeta de crédito y débito, transferencia, efectivo en puntos de
pago). No se aceptan otros medios. Para cuenta corriente o pago a plazo: escalar."""

CONTACTO = """CONTACTO
WhatsApp 11 6372-9303 · cafeclout@gmail.com · Instagram @clout.cafe · clout.ar"""


# Lo que decían los emails que enviamos. Sin esto, el sistema no entiende
# preguntas como "¿cuánto sale la opción B?" y las escala aunque sepa la
# respuesta: pasó con dos prospectos que estaban pidiendo precio.
QUE_LES_ESCRIBIMOS = """QUÉ DECÍA EL EMAIL QUE LE MANDAMOS A ESTA PERSONA

A todos se les ofrecieron DOS opciones. Según el rubro, así:

A COMERCIOS GASTRONÓMICOS (bares, restaurantes, cafeterías, hoteles, panaderías):
· OPCIÓN A — SOLO EL CAFÉ: si ya tienen máquina, les proveemos el café, de
  especialidad o comercial. Entrega semanal, tostado fresco. A mayor volumen,
  mejor precio.
· OPCIÓN B — MÁQUINA EN COMODATO + CAFÉ: comprando 30 kg o más por mes,
  instalamos una máquina de espresso sin costo adicional. Solo pagan el café.

A OFICINAS Y EMPRESAS (corporativo, coworking):
· OPCIÓN A — SOLO EL CAFÉ: si ya tienen máquina, café de especialidad o
  comercial a precio mayorista, tostado fresco y entrega directa.
· OPCIÓN B — SERVICIO DE VENDING COMPLETO: instalamos una máquina de espresso
  automática, la mantenemos y reponemos el café cada semana.

Si preguntan por "la opción A" o "la opción B", se refieren a esto. Respondé con
los precios y condiciones que figuran más arriba, según el tipo de cliente."""


def armar_contexto() -> str:
    """Texto con todo lo que el sistema sabe. Lo que no está acá, se escala."""
    precios = leer_precios()
    lineas = ["PRECIOS VIGENTES (los 250 g ya incluyen el 20% de descuento):", ""]
    for p in precios:
        partes = []
        if p["min250"]:
            partes.append(f"250 g {_pesos(p['min250'])}")
        if p["minkg"]:
            partes.append(f"1 kg {_pesos(p['minkg'])}")
        if p["maykg"]:
            partes.append(f"mayorista por kg {_pesos(p['maykg'])}")
        lineas.append(f"· {p['cafe']}: " + " · ".join(partes))
    # Comodato, tal como está cargado en la planilla
    lineas += ["", "MÁQUINAS EN COMODATO"]
    for e in leer_comodato():
        costo = e["costo_maquina"]
        costo_txt = ("sin costo mensual" if costo in ("-", "", "0")
                     else f"{costo} por mes")
        lineas.append(
            f"· {e['tipo']} — {e['maquina']}: {costo_txt}. "
            f"El café se factura a {e['precio_cafe'].lower()}. "
            f"Consumo mínimo: {e['minimo']}."
        )
    lineas.append(
        "\nCAFÉ FILTRADO / MÁQUINA BUNN — aplica a CUALQUIER cliente, sea oficina "
        "o comercio gastronómico. El esquema lo define la máquina, no el rubro:\n"
        "· Si ya tienen la cafetera: les proveemos solo el café molido para "
        "filtrado, a PRECIO MINORISTA por kg. Sin mínimo ni compromiso.\n"
        "· Si no la tienen: se les instala una Bunn o industrial de filtrado en "
        "comodato, SIN COSTO mensual, con un consumo mínimo de 30 kg por mes y "
        "el café a PRECIO MINORISTA.\n"
        "· Los filtros Bunn se venden aparte, al precio que figura en extras.\n"
        "Al recomendar la molienda para este método, es café molido para filtrado."
    )

    # Extras con precio de venta
    extras = leer_extras()
    if extras:
        lineas += ["", "EXTRAS (precio de venta)"]
        for nombre, precio in extras:
            lineas.append(f"· {nombre}: {precio}")

    lineas += [
        "",
        "El precio mayorista aplica a comercios y empresas, por volumen.",
        "El kilo rinde bastante más por gramo que los 250 g.",
        "Todos los cafés se despachan en grano entero o molido, al mismo precio.",
        "", QUE_LES_ESCRIBIMOS, "", ENVIOS, "", PAGOS, "", CONTACTO,
    ]
    return "\n".join(lineas)
