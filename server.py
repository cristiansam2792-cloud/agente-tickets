"""Servidor MCP de tickets TIC de Grupak.

Fuente de datos:
  - por defecto: tickets.json (datos de práctica, para pruebas y evals)
  - TICKETS_FUENTE=grupak: plataforma real vía fuente_grupak.py

TICKETS_AHORA=YYYY-MM-DDTHH:MM fija la hora "actual" (pruebas repetibles).
"""
import json
import os
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("tickets-tic")

CARPETA = Path(__file__).resolve().parent
CAMPOS_LISTA = ("id", "titulo", "planta", "estado", "responsable",
                "fecha_creacion", "fecha_compromiso", "solucionado")
MAX_LISTA = 150


# ---------------------------------------------------------------- datos
def cargar_tickets() -> list[dict]:
    if os.environ.get("TICKETS_FUENTE") == "grupak":
        from fuente_grupak import cargar_tickets_grupak
        return cargar_tickets_grupak()
    return json.loads((CARPETA / "tickets.json").read_text(encoding="utf-8"))


def ahora() -> datetime:
    fija = os.environ.get("TICKETS_AHORA")
    return datetime.fromisoformat(fija) if fija else datetime.now()


def _norm(texto: str) -> str:
    """Minúsculas, sin acentos y sin espacios extra: 'Jesús' == 'jesus'."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().split())


def _norm_estado(estado: str) -> str:
    # La plataforma real dice "Proceso"; los datos de práctica, "En proceso".
    return _norm(estado).replace("en proceso", "proceso")


def _sin_responsable(t: dict) -> bool:
    return _norm(t.get("responsable", "")) in ("", "sin asignar")


# ---------------------------------------------------------------- herramientas
@mcp.tool()
def listar_tickets(responsable: str = "", estado: str = "", planta: str = "") -> list[dict]:
    """Lista tickets TIC, del más reciente al más antiguo (máximo 150).
    Filtros opcionales, sin distinguir mayúsculas ni acentos:
    responsable (nombre o parte), estado (Abierto, Proceso, Cerrado),
    planta (nombre o parte, ej. 'Toluca', 'Hidalgo')."""
    res = cargar_tickets()
    if responsable:
        res = [t for t in res if _norm(responsable) in _norm(t.get("responsable", ""))]
    if estado:
        res = [t for t in res if _norm_estado(t["estado"]) == _norm_estado(estado)]
    if planta:
        res = [t for t in res if _norm(planta) in _norm(t.get("planta", ""))]
    res = sorted(res, key=lambda t: t["id"], reverse=True)
    return [{k: t.get(k) for k in CAMPOS_LISTA if k in t} for t in res[:MAX_LISTA]]


@mcp.tool()
def tickets_por_vencer(horas: int = 48) -> list[dict]:
    """Tickets no cerrados cuya fecha compromiso cae dentro de las próximas `horas`
    (incluye los ya vencidos). Ordenados del más urgente al menos urgente."""
    limite = ahora() + timedelta(hours=horas)
    res = [
        t for t in cargar_tickets()
        if _norm_estado(t["estado"]) != "cerrado"
        and t.get("fecha_compromiso")
        and datetime.fromisoformat(t["fecha_compromiso"]) <= limite
    ]
    for t in res:
        restante = datetime.fromisoformat(t["fecha_compromiso"]) - ahora()
        t["horas_restantes"] = round(restante.total_seconds() / 3600, 1)
    return sorted(res, key=lambda t: t["horas_restantes"])


@mcp.tool()
def tickets_sin_asignar() -> list[dict]:
    """Tickets en estado Abierto que nadie ha tomado (sin responsable).
    Ordenados del que más lleva esperando al más reciente."""
    res = [t for t in cargar_tickets()
           if _norm_estado(t["estado"]) == "abierto" and _sin_responsable(t)]
    for t in res:
        if t.get("fecha_creacion"):
            espera = ahora() - datetime.fromisoformat(t["fecha_creacion"])
            t["horas_esperando"] = round(espera.total_seconds() / 3600, 1)
    return sorted(res, key=lambda t: t.get("horas_esperando", 0), reverse=True)


@mcp.tool()
def solucionados_sin_cerrar() -> list[dict]:
    """Tickets marcados como solucionados pero que siguen en Abierto o Proceso:
    el trabajo ya se hizo, solo falta cerrarlos en la plataforma."""
    return [t for t in cargar_tickets()
            if t.get("solucionado") and _norm_estado(t["estado"]) != "cerrado"]


@mcp.tool()
def resumen_por_planta() -> dict:
    """Conteo de tickets no cerrados por planta y estado, más cuántos están vencidos
    (fecha compromiso ya pasada) y cuántos siguen sin asignar en cada planta."""
    resumen = defaultdict(lambda: {"total": 0, "por_estado": Counter(), "vencidos": 0, "sin_asignar": 0})
    for t in cargar_tickets():
        if _norm_estado(t["estado"]) == "cerrado":
            continue
        p = resumen[t.get("planta") or "Sin planta"]
        p["total"] += 1
        p["por_estado"][t["estado"]] += 1
        if t.get("fecha_compromiso") and datetime.fromisoformat(t["fecha_compromiso"]) < ahora():
            p["vencidos"] += 1
        if _sin_responsable(t):
            p["sin_asignar"] += 1
    ordenado = sorted(resumen.items(), key=lambda kv: kv[1]["total"], reverse=True)
    return {planta: {**d, "por_estado": dict(d["por_estado"])} for planta, d in ordenado}


@mcp.tool()
def detalle_ticket(ticket_id: int) -> dict:
    """Devuelve un ticket por su id, o un error si no existe."""
    for t in cargar_tickets():
        if t["id"] == ticket_id:
            return t
    return {"error": f"No existe el ticket {ticket_id}"}


if __name__ == "__main__":
    mcp.run()  # stdio por defecto
