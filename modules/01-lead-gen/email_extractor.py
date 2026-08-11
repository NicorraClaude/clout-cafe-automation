"""Extractor mejorado: sigue enlaces reales de contacto y desofusca emails."""
import re, ssl, urllib.request, urllib.parse, html as htmlmod

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EMAIL_RE  = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
MAILTO_RE = re.compile(r'mailto:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})')
# Emails escondidos: "info [at] dominio [dot] com", "info (arroba) dominio"
OFUSCADO_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s+at\s+|\[arroba\]|\(arroba\))\s*"
    r"([a-zA-Z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\[punto\]|\(punto\))\s*([a-zA-Z]{2,})",
    re.I)
LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)

PALABRAS_CONTACTO = ("contacto", "contact", "nosotros", "about", "quienes",
                     "institucional", "empresa", "info")


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "es-AR,es;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", errors="ignore")


def emails_en(texto):
    """Saca emails del HTML, incluyendo los ofuscados y los HTML-escapados."""
    encontrados = []
    texto = htmlmod.unescape(texto)
    encontrados += MAILTO_RE.findall(texto)          # los más confiables
    encontrados += EMAIL_RE.findall(texto)
    for local, dom, tld in OFUSCADO_RE.findall(texto):
        encontrados.append(f"{local}@{dom}.{tld}")
    return encontrados


def paginas_de_contacto(url_base, html):
    """Enlaces reales de contacto que aparecen en la página, no rutas adivinadas."""
    urls = []
    for href in LINK_RE.findall(html):
        h = href.lower()
        if any(p in h for p in PALABRAS_CONTACTO) and not h.startswith(("mailto:", "tel:", "#")):
            urls.append(urllib.parse.urljoin(url_base, href))
    # sin duplicados, preservando orden
    vistos, out = set(), []
    for u in urls:
        if u not in vistos:
            vistos.add(u); out.append(u)
    return out[:4]


def extraer(url, validar):
    """Devuelve (email, de_donde) o (None, motivo)."""
    try:
        home = fetch(url)
    except Exception as e:
        return None, f"home inaccesible: {str(e)[:35]}"

    for em in emails_en(home):
        if validar(em.lower()):
            return em.lower(), "home"

    for pagina in paginas_de_contacto(url, home):
        try:
            h = fetch(pagina, timeout=8)
        except Exception:
            continue
        for em in emails_en(h):
            if validar(em.lower()):
                return em.lower(), pagina.split("/")[-1][:18] or "contacto"

    return None, "sin email publicado"
