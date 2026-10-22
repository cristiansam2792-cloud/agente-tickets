"""Paso 1: prueba el servidor MCP sin LLM ni API key.

Levanta server.py por stdio (igual que lo haría Claude Code), lista las
herramientas y verifica que respondan lo esperado. Es tu primer "eval":
pruebas deterministas de las herramientas.
"""
import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters

SERVIDOR = StdioServerParameters(
    command=sys.executable,
    args=["server.py"],
    env={**os.environ, "TICKETS_AHORA": "2026-10-11T21:00"},  # hora fija = resultados repetibles
)


def datos(resultado):
    """Extrae el JSON que devolvió la herramienta."""
    if resultado.structured_content is not None:
        sc = resultado.structured_content
        return sc.get("result", sc)
    return json.loads(resultado.content[0].text)


async def main():
    fallas = 0

    def revisa(nombre, condicion):
        nonlocal fallas
        print(("  OK   " if condicion else "  FALLA ") + nombre)
        fallas += 0 if condicion else 1

    async with Client(SERVIDOR) as c:
        herramientas = await c.list_tools()
        print("Herramientas:", [h.name for h in herramientas.tools])

        por_vencer = datos(await c.call_tool("tickets_por_vencer", {"horas": 48}))
        ids = [t["id"] for t in por_vencer]
        print("Por vencer (48 h):", ids)
        revisa("incluye el vencido #104", 104 in ids)
        revisa("incluye el crítico #106", 106 in ids)
        revisa("excluye el cerrado #105", 105 not in ids)
        revisa("excluye #107 (vence en 9 días)", 107 not in ids)
        revisa("ordenado por urgencia (#104 primero)", ids[:1] == [104])

        de_ana = datos(await c.call_tool("listar_tickets", {"responsable": "ana"}))
        revisa("Ana tiene 3 tickets", len(de_ana) == 3)

        no_existe = datos(await c.call_tool("detalle_ticket", {"ticket_id": 999}))
        revisa("ticket inexistente devuelve error", "error" in no_existe)

    print(f"\n{'Todo bien' if fallas == 0 else f'{fallas} falla(s)'}")
    sys.exit(1 if fallas else 0)


asyncio.run(main())
