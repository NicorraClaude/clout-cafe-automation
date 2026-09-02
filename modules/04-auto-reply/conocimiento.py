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


def leer_precios() -> list[dict]:
    """Devuelve [{cafe, min250, minkg, maykg}] leyendo solo columnas de venta."""
    raw = urllib.request.urlopen(CSV_URL, timeout=30, context=CTX).read().decode("utf-8")
    filas = list(csv.reader(io.StringIO(raw)))

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


# Condiciones comerciales. Van acá y no en la planilla porque son texto fijo;
# si cambian, se editan en este archivo.
COMODATO = """MÁQUINAS EN COMODATO — dos esquemas:

OFICINAS — máquina Necta Koro (vending automática)
· Costo de la máquina: $200.000 por mes
· El café se factura a PRECIO MAYORISTA
· Consumo mínimo: 15 kg por mes

COMERCIOS GASTRONÓMICOS — máquina espresso de 1 o 2 grupos (modelo a definir con el cliente)
· La máquina va SIN COSTO mensual
· El café se factura a PRECIO MINORISTA
· Consumo mínimo: 30 kg por mes

EXTRAS disponibles en ambos esquemas: chocolate en polvo, leche en polvo, azúcar,
edulcorante, revolvedores y vasos. El precio de los extras NO está definido: si
preguntan por eso, hay que escalar."""

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
    lineas += [
        "",
        "El precio mayorista aplica a comercios y empresas, por volumen.",
        "El kilo rinde bastante más por gramo que los 250 g.",
        "Todos los cafés se despachan en grano entero o molido, al mismo precio.",
        "", COMODATO, "", ENVIOS, "", PAGOS, "", CONTACTO,
    ]
    return "\n".join(lineas)
