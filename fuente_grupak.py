"""Conector a la plataforma de tickets TIC de Grupak (http://192.168.20.19:8080).

Inicia sesión como un navegador, recorre /tickets/index?page=N (50 tickets por
página, del más nuevo al más viejo) y se detiene al llegar a tickets anteriores
a la fecha `desde`. Devuelve una lista de dicts con el mismo formato que usa
server.py. Guarda un caché local para no pegarle a la plataforma en cada pregunta.

Variables de entorno:
  TICKETS_USUARIO    usuario de la plataforma (obligatorio)
  TICKETS_PASSWORD   contraseña; si no está, se busca en el Administrador de
                     credenciales de Windows: python -m keyring set tickets-grupak <usuario>
  TICKETS_URL        default http://192.168.20.19:8080
  TICKETS_MESES      meses hacia atrás, contando el actual; default 2 (desde el día 1 del mes pasado)
  TICKETS_DESDE      YYYY-MM-DD exacto; si está, manda sobre TICKETS_MESES
  TICKETS_CACHE_MIN  minutos de vigencia del caché; default 10 (0 = sin caché)

Prueba rápida:
  python fuente_grupak.py --html TIC.html   # solo el parser, sin red
  python fuente_grupak.py                   # login real + descarga
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = os.environ.get("TICKETS_URL", "http://192.168.20.19:8080").rstrip("/")
CACHE = Path(__file__).with_name("tickets_cache.json")
MAX_PAGINAS = 60  # tope de seguridad (~3,000 tickets)


class ErrorPlataforma(Exception):
    pass


# ---------------------------------------------------------------- sesión
def _token(html: str) -> str:
    m = re.search(r'name="_token"\s+value="([^"]+)"', html)
    if not m:
        raise ErrorPlataforma("No encontré el _token del formulario de login.")
    return m.group(1)


def _es_login(resp: requests.Response) -> bool:
    return resp.url.rstrip("/").endswith("/login") or 'name="password"' in resp.text


def iniciar_sesion() -> requests.Session:
    usuario = os.environ.get("TICKETS_USUARIO")
    password = os.environ.get("TICKETS_PASSWORD")
    if usuario and not password:
        # Respaldo: Administrador de credenciales de Windows (vía keyring).
        try:
            import keyring
            password = keyring.get_password("tickets-grupak", usuario)
        except ImportError:
            pass
    if not usuario or not password:
        raise ErrorPlataforma(
            "Faltan credenciales: define TICKETS_USUARIO y guarda la contraseña con "
            "'python -m keyring set tickets-grupak <usuario>' (o usa TICKETS_PASSWORD)."
        )

    s = requests.Session()
    s.headers["User-Agent"] = "agente-tickets-tic/1.0"
    r = s.get(f"{BASE}/login", timeout=15)
    r.raise_for_status()
    r = s.post(
        f"{BASE}/login",
        data={"_token": _token(r.text), "login": usuario, "password": password, "fdf": ""},
        timeout=15,
    )
    if _es_login(r):
        raise ErrorPlataforma("Login rechazado: revisa usuario y contraseña.")
    return s


# ---------------------------------------------------------------- parser
def _iso_compromiso(texto: str) -> str | None:
    # La plataforma solo da la fecha; tomamos el fin del día como límite.
    return f"{texto}T23:59:00" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto) else None


def parsear_tabla(html: str) -> list[dict]:
    """Convierte las filas de la tabla del listado en dicts."""
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table", class_="w3-table-all")
    if tabla is None:
        return []
    tickets = []
    for tr in tabla.find_all("tr"):
        celdas = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
        if len(celdas) < 12 or not celdas[0].isdigit():
            continue  # encabezado u otra fila
        (num, titulo, servicio, ubicacion, dueno, depto,
         sol, estado, _tiempo, responsable, creacion, compromiso) = celdas[:12]
        tickets.append({
            "id": int(num),
            "titulo": titulo,
            "servicio": servicio,
            "planta": ubicacion,
            "solicitante": dueno,
            "departamento": depto,
            "solucionado": sol == "Si",
            "estado": estado,                      # Abierto / Proceso / Cerrado
            "responsable": responsable or "Sin asignar",
            "fecha_creacion": creacion.replace(" ", "T"),
            "fecha_compromiso": _iso_compromiso(compromiso),
            "url": f"{BASE}/tickets/show/{num}",
        })
    return tickets


# ---------------------------------------------------------------- descarga
def _desde_default() -> date:
    """Día 1 de hace N meses (TICKETS_MESES, default 2 = mes actual + el anterior)."""
    meses = max(1, int(os.environ.get("TICKETS_MESES", "2")))
    hoy = date.today()
    total = hoy.year * 12 + (hoy.month - 1) - (meses - 1)
    return date(total // 12, total % 12 + 1, 1)


def descargar(desde: date) -> list[dict]:
    s = iniciar_sesion()
    limite = datetime.combine(desde, datetime.min.time())
    todos: dict[int, dict] = {}
    for pagina in range(1, MAX_PAGINAS + 1):
        r = s.get(f"{BASE}/tickets/index", params={"page": pagina}, timeout=20)
        if _es_login(r):  # la sesión expiró a media descarga
            s = iniciar_sesion()
            r = s.get(f"{BASE}/tickets/index", params={"page": pagina}, timeout=20)
        r.raise_for_status()
        filas = parsear_tabla(r.text)
        if not filas:
            break
        for t in filas:
            if datetime.fromisoformat(t["fecha_creacion"]) >= limite:
                todos[t["id"]] = t
        if min(datetime.fromisoformat(t["fecha_creacion"]) for t in filas) < limite:
            break
    return sorted(todos.values(), key=lambda t: t["id"], reverse=True)


def cargar_tickets_grupak() -> list[dict]:
    """Punto de entrada para server.py: usa caché si está vigente."""
    minutos = float(os.environ.get("TICKETS_CACHE_MIN", "10"))
    if minutos > 0 and CACHE.exists() and time.time() - CACHE.stat().st_mtime < minutos * 60:
        return json.loads(CACHE.read_text(encoding="utf-8"))

    desde_txt = os.environ.get("TICKETS_DESDE")
    desde = date.fromisoformat(desde_txt) if desde_txt else _desde_default()
    tickets = descargar(desde)
    if minutos > 0:
        CACHE.write_text(json.dumps(tickets, ensure_ascii=False, indent=1), encoding="utf-8")
    return tickets


# ---------------------------------------------------------------- prueba
if __name__ == "__main__":
    from collections import Counter

    if len(sys.argv) == 3 and sys.argv[1] == "--html":
        tickets = parsear_tabla(Path(sys.argv[2]).read_text(encoding="utf-8"))
    else:
        os.environ.setdefault("TICKETS_CACHE_MIN", "0")
        t0 = time.time()
        tickets = cargar_tickets_grupak()
        print(f"Descarga: {time.time() - t0:.1f} s")

    print(f"Tickets: {len(tickets)}")
    if tickets:
        print(f"Rango de ids: #{tickets[-1]['id']} – #{tickets[0]['id']}")
        print("Por estado:", dict(Counter(t["estado"] for t in tickets)))
        print("Sin fecha compromiso:", sum(1 for t in tickets if not t["fecha_compromiso"]))
        print("Ejemplo:", json.dumps(tickets[0], ensure_ascii=False, indent=1))
