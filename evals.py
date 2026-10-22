"""Paso 3: evals del agente — medir si responde bien, no solo si "se ve bien".

Cada caso define una pregunta y qué debe pasar:
  - herramienta: qué herramienta esperamos que use
  - debe_mencionar / no_debe_mencionar: #ids que deben (o no) aparecer
Se corre cada caso varias veces porque el LLM no es determinista.

Uso:  python evals.py            (3 corridas por caso)
      python evals.py 5          (5 corridas por caso)
Requiere ANTHROPIC_API_KEY.
"""
import asyncio
import re
import sys

from agente import preguntar

AHORA = "2026-10-11T21:00"  # misma hora fija que probar_servidor.py

CASOS = [
    {
        "nombre": "Por vencer en 48 h",
        "pregunta": "¿Qué tickets vencen en las próximas 48 horas?",
        "herramienta": "tickets_por_vencer",
        "debe_mencionar": [104, 106, 101, 108, 102],
        "no_debe_mencionar": [105, 107],
    },
    {
        "nombre": "Pendientes de una persona",
        "pregunta": "¿Qué tiene pendiente Jorge?",
        "herramienta": "listar_tickets",
        "debe_mencionar": [104, 106, 108],
        "no_debe_mencionar": [101, 102],
    },
    {
        "nombre": "No inventar",
        "pregunta": "Dame el detalle del ticket 999",
        "herramienta": "detalle_ticket",
        "debe_mencionar": [],
        "no_debe_mencionar": [101, 104],
        "debe_decir": ["no existe", "no se encontr", "no hay"],
    },
]


def ids_en(texto: str) -> set[int]:
    return {int(n) for n in re.findall(r"\b(\d{3})\b", texto)}


def calificar(caso, respuesta, usadas) -> list[str]:
    errores = []
    if caso["herramienta"] not in usadas:
        errores.append(f"no usó {caso['herramienta']} (usó {usadas})")
    vistos = ids_en(respuesta)
    faltan = set(caso["debe_mencionar"]) - vistos
    sobran = set(caso["no_debe_mencionar"]) & vistos
    if faltan:
        errores.append(f"faltó mencionar {sorted(faltan)}")
    if sobran:
        errores.append(f"mencionó de más {sorted(sobran)}")
    if "debe_decir" in caso and not any(f in respuesta.lower() for f in caso["debe_decir"]):
        errores.append("no dijo que el ticket no existe")
    return errores


async def main(corridas: int):
    total = aprobadas = 0
    for caso in CASOS:
        ok = 0
        for i in range(corridas):
            respuesta, usadas = await preguntar(caso["pregunta"], AHORA, verbose=False)
            errores = calificar(caso, respuesta, usadas)
            ok += not errores
            if errores:
                print(f"    corrida {i + 1}: " + "; ".join(errores))
        total += corridas
        aprobadas += ok
        print(f"{'✅' if ok == corridas else '⚠️ '} {caso['nombre']}: {ok}/{corridas}")
    print(f"\nPuntaje: {aprobadas}/{total} ({100 * aprobadas // total}%)")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
