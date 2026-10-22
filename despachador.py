"""Despachador de recordatorios de tickets TIC (multi-agente).

Reparto del trabajo:
  - El DESPACHADOR es código normal (determinista): consulta el servidor MCP,
    filtra a los responsables del equipo y agrupa los tickets por persona.
    Esto no necesita un LLM: es filtrar y agrupar, y así no se equivoca ni gasta.
  - Por cada responsable lanza un SUBAGENTE (una llamada a Claude, en paralelo)
    que redacta el recordatorio de WhatsApp con sus tickets.
  - Un subagente más redacta el resumen para el grupo, con los tickets sin asignar.

Uso:
  python despachador.py            # plataforma real (TICKETS_FUENTE=grupak)
  python despachador.py --prueba   # tickets.json con hora fija, sin filtro de equipo

Escribe recordatorios_<fecha>.md con todos los mensajes listos para copiar.
Requiere ANTHROPIC_API_KEY (y las credenciales de la plataforma en modo real).
"""
import asyncio
import json
import os
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import anthropic
from mcp import Client

from agente import servidor

MODELO = "claude-haiku-5-5"  # redactar mensajes cortos: el modelo pequeño basta
HORAS = 48
AHORA_PRUEBA = "2026-10-11T21:00"

# Responsables que reciben recordatorio (mismo filtro que el reporte de las 3:00 pm).
EQUIPO = [
    "Luis Antonio Rodríguez Olvera", "Jesús García Lozada", "Mario Rodrigo Arévalo Téllez",
    "Abel Lira", "Mariano González Barrientos", "Marcos Eduardo Licona Rodríguez",
    "Edith López", "Jesús Xavier Romero Piña", "Yoselin González", "Israel Samperio",
    "José Alberto Franco", "Cristian Carrera",
]

INSTRUCCIONES_PERSONA = """Redactas recordatorios de WhatsApp para el equipo TIC de Grupak.
Escribe UN mensaje para la persona indicada sobre sus tickets. Reglas:
- Español de México, tono cordial y directo, de compañero de trabajo. Sin formalismos.
- Formato WhatsApp: *negritas* con un asterisco, listas con guion. Nada de tablas ni Markdown.
- Separa en dos bloques, omitiendo el que no aplique:
  1. *Ya solucionados, solo falta cerrarlos* (solucionado = true): pide cerrarlos en la plataforma.
  2. *Pendientes*: los vencidos primero, luego los que vencen pronto.
- Cada ticket en una línea: #número, título corto, planta y si está vencido o cuándo vence.
- Usa solo los datos recibidos. No inventes tickets, fechas ni causas.
- Máximo 15 líneas. Responde solo con el texto del mensaje."""

INSTRUCCIONES_GRUPO = """Redactas un aviso de WhatsApp para el grupo del equipo TIC de Grupak.
Lista los tickets abiertos que nadie ha tomado (sin responsable) y pide que alguien los tome.
Reglas: español de México, tono directo; formato WhatsApp (*negritas*, guiones, sin tablas);
cada ticket en una línea con #número, título corto, planta y cuánto lleva esperando;
usa solo los datos recibidos. Máximo 15 líneas. Responde solo con el texto del mensaje."""


# ------------------------------------------------------------ despachador
def _tokens(nombre: str) -> set[str]:
    sin_acentos = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return set(sin_acentos.lower().split())


def del_equipo(responsable: str) -> str | None:
    """Devuelve el nombre del EQUIPO que corresponde, ignorando acentos y nombres extra.
    'Jesus Garcia Lozada' -> 'Jesús García Lozada'; 'Edith López Pérez' -> 'Edith López'."""
    r = _tokens(responsable)
    for nombre in EQUIPO:
        if _tokens(nombre) <= r:
            return nombre
    return None


def agrupar(tickets: list[dict], filtrar_equipo: bool) -> dict[str, list[dict]]:
    grupos = defaultdict(list)
    for t in tickets:
        nombre = del_equipo(t["responsable"]) if filtrar_equipo else t["responsable"]
        if nombre:
            grupos[nombre].append(t)
    return dict(grupos)


def _datos(resultado):
    if resultado.structured_content is not None:
        sc = resultado.structured_content
        return sc.get("result", sc)
    return json.loads(resultado.content[0].text)


async def consultar(prueba: bool):
    """Llama a las herramientas del servidor MCP, igual que lo haría el agente."""
    async with Client(servidor(AHORA_PRUEBA if prueba else None)) as c:
        por_vencer = _datos(await c.call_tool("tickets_por_vencer", {"horas": HORAS}))
        sin_asignar = _datos(await c.call_tool("tickets_sin_asignar", {}))
    return por_vencer, sin_asignar


# ------------------------------------------------------------ subagentes
CAMPOS = ("id", "titulo", "planta", "estado", "solucionado", "fecha_compromiso", "horas_restantes")


async def subagente(cliente, instrucciones: str, encabezado: str, tickets: list[dict], campos) -> str:
    compactos = [{k: t.get(k) for k in campos} for t in tickets]
    r = await cliente.messages.create(
        model=MODELO,
        max_tokens=800,
        system=instrucciones,
        messages=[{"role": "user", "content": f"{encabezado}\n\n{json.dumps(compactos, ensure_ascii=False)}"}],
    )
    return "".join(b.text for b in r.content if b.type == "text").strip()


async def main(prueba: bool):
    if not prueba:
        os.environ["TICKETS_FUENTE"] = "grupak"

    por_vencer, sin_asignar = await consultar(prueba)
    grupos = agrupar(por_vencer, filtrar_equipo=not prueba)
    print(f"Por vencer/vencidos: {len(por_vencer)} · del equipo: {sum(map(len, grupos.values()))} "
          f"en {len(grupos)} personas · sin asignar: {len(sin_asignar)}")

    cliente = anthropic.AsyncAnthropic()
    tareas = {
        nombre: subagente(cliente, INSTRUCCIONES_PERSONA, f"Persona: {nombre}", ts, CAMPOS)
        for nombre, ts in sorted(grupos.items())
    }
    if sin_asignar:
        tareas["Grupo (sin asignar)"] = subagente(
            cliente, INSTRUCCIONES_GRUPO, "Tickets sin asignar:", sin_asignar,
            ("id", "titulo", "planta", "fecha_creacion", "horas_esperando"),
        )
    mensajes = dict(zip(tareas, await asyncio.gather(*tareas.values())))

    fecha = datetime.now().strftime("%Y-%m-%d")
    salida = Path(__file__).with_name(f"recordatorios_{fecha}.md")
    partes = [f"# Recordatorios de tickets TIC · {fecha}\n"]
    for nombre, texto in mensajes.items():
        ids = ", ".join(f"#{t['id']}" for t in grupos.get(nombre, sin_asignar))
        partes.append(f"## {nombre}\n_{ids}_\n\n{texto}\n")
        print(f"\n===== {nombre} =====\n{texto}")
    salida.write_text("\n".join(partes), encoding="utf-8")
    print(f"\nGuardado en {salida.name}")


if __name__ == "__main__":
    asyncio.run(main(prueba="--prueba" in sys.argv))
