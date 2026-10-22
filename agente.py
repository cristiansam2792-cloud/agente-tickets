"""Paso 2: tu propio agente con la API de Claude + el servidor MCP.

Es el "tool use manual": tú escribes el ciclo que el producto hace por ti.
  1. Se conecta a server.py y convierte sus herramientas al formato de la API.
  2. Manda la pregunta a Claude con esas herramientas.
  3. Si Claude pide una herramienta, la ejecuta en el servidor MCP y le
     devuelve el resultado. Repite hasta que Claude responde en texto.

Uso:  python agente.py "¿Qué tickets vencen en las próximas 48 horas?"
Requiere la variable de entorno ANTHROPIC_API_KEY.
"""
import asyncio
import json
import os
import sys

import anthropic
from mcp import Client, StdioServerParameters

MODELO = "claude-sonnet-5-5"
SISTEMA = (
    "Eres el asistente del área TIC de Grupak. Responde en español, breve y "
    "directo. Usa las herramientas para consultar tickets; nunca inventes datos. "
    "Menciona siempre el número de ticket (#id) y su responsable."
)


def servidor(ahora_fija: str | None = None) -> StdioServerParameters:
    env = dict(os.environ)
    if ahora_fija:
        env["TICKETS_AHORA"] = ahora_fija
    carpeta = os.path.dirname(os.path.abspath(__file__))
    return StdioServerParameters(command=sys.executable, args=[os.path.join(carpeta, "server.py")], env=env)


def texto_resultado(resultado) -> str:
    if resultado.structured_content is not None:
        return json.dumps(resultado.structured_content, ensure_ascii=False)
    return "\n".join(getattr(b, "text", "") for b in resultado.content)


async def preguntar(pregunta: str, ahora_fija: str | None = None, verbose: bool = True):
    """Devuelve (respuesta_final, lista_de_herramientas_usadas)."""
    claude = anthropic.AsyncAnthropic()
    usadas = []

    async with Client(servidor(ahora_fija)) as mcp:
        # 1) Herramientas MCP -> formato de la API de Claude
        herramientas = [
            {"name": h.name, "description": h.description or "", "input_schema": h.input_schema}
            for h in (await mcp.list_tools()).tools
        ]

        mensajes = [{"role": "user", "content": pregunta}]
        for _ in range(10):  # tope de vueltas para que nunca se cicle
            r = await claude.messages.create(
                model=MODELO, max_tokens=1500, system=SISTEMA,
                tools=herramientas, messages=mensajes,
            )
            mensajes.append({"role": "assistant", "content": r.content})

            if r.stop_reason != "tool_use":
                return "".join(b.text for b in r.content if b.type == "text"), usadas

            # 2) Ejecutar cada herramienta que pidió Claude
            resultados = []
            for b in r.content:
                if b.type == "tool_use":
                    if verbose:
                        print(f"  → {b.name}({json.dumps(b.input, ensure_ascii=False)})")
                    usadas.append(b.name)
                    res = await mcp.call_tool(b.name, b.input)
                    resultados.append({
                        "type": "tool_result", "tool_use_id": b.id,
                        "content": texto_resultado(res), "is_error": bool(res.is_error),
                    })
            mensajes.append({"role": "user", "content": resultados})

    return "(El agente no terminó en 10 vueltas)", usadas


if __name__ == "__main__":
    pregunta = " ".join(sys.argv[1:]) or "¿Qué tickets vencen en las próximas 48 horas?"
    respuesta, _ = asyncio.run(preguntar(pregunta))
    print("\n" + respuesta)
