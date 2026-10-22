# Práctica: servidor MCP de tickets TIC + agente + evals

Mini-proyecto para llegar calentado al **Claude for AI Engineering** (Ibero, lunes 19 de oct, 16:30).
Cubre tres temas del evento: **MCP**, **tool use / agentes** y **evals**.
Usa datos de ejemplo (`tickets.json`) para no tocar la plataforma real.

| Archivo | Qué es |
|---|---|
| `server.py` | Servidor MCP con 3 herramientas: `listar_tickets`, `tickets_por_vencer`, `detalle_ticket` |
| `probar_servidor.py` | Paso 1 — pruebas deterministas del servidor (no requiere API key) |
| `agente.py` | Paso 2 — tu propio agente: API de Claude + MCP con el ciclo de tool use escrito a mano |
| `evals.py` | Paso 3 — evals del agente: corre cada caso varias veces y da un puntaje |
| `tickets.json` | 8 tickets ficticios (Hidalgo, Toluca, Cuernavaca, Corporativo) |

---

## 0. Preparar (≈15 min, en tu laptop)

En PowerShell, dentro de la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Necesitas Python 3.10 o superior. Ojo: esto usa **MCP SDK 2.x**, donde `FastMCP` se renombró a `MCPServer`. Muchos tutoriales en internet todavía usan la v1.

## 1. Probar el servidor (sin API key)

```powershell
python probar_servidor.py
```

Debe terminar con **"Todo bien"** y 7 checks en OK. Eso ya es un eval: pruebas fijas de que cada herramienta hace lo correcto.

## 2. Conectarlo a Claude Code

Instala Claude Code si aún no lo tienes (ver docs.claude.com). Luego registra tu servidor:

```powershell
claude mcp add tickets-tic -- python C:\ruta\a\practica-mcp-tickets\server.py
```

Abre `claude` y pregúntale: *"¿Qué tickets vencen en las próximas 48 horas?"*. Verás que llama a `tickets_por_vencer`.
Con `/mcp` dentro de Claude Code puedes ver que está conectado.

## 3. Tu propio agente (requiere API key)

Saca una API key en **platform.claude.com** (Console → API Keys) y carga unos dólares de crédito; esta práctica gasta centavos.

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python agente.py "¿Qué tiene pendiente Ana en Toluca?"
```

Verás en pantalla qué herramientas pide Claude (`→ listar_tickets(...)`) antes de responder. Lee `agente.py`: es el ciclo que Claude Code hace por ti, pero escrito a mano en ~40 líneas.

## 4. Evals

```powershell
python evals.py        # 3 corridas por caso
python evals.py 5      # 5 corridas
```

Califica si usó la herramienta correcta, si mencionó los tickets que debía, si no mencionó de más y si no inventa un ticket que no existe.

---

## Retos para antes del 19 (de menor a mayor)

1. **Agrega una herramienta** `resumen_por_planta()` que cuente tickets abiertos por planta. Agrégale su check en `probar_servidor.py` y un caso en `evals.py`.
2. **Rompe el agente a propósito:** quita la última línea de `SISTEMA` en `agente.py` y corre los evals. ¿Baja el puntaje? Eso es lo que hacen los evals: te dicen si un cambio mejoró o empeoró.
3. **Cambia de modelo:** en `agente.py` cambia `MODELO` a `claude-haiku-5-5` y compara puntaje y costo.
4. **Conéctalo a lo real:** cambia `cargar_tickets()` para leer tu plataforma (`http://192.168.20.19:8080`) en vez de `tickets.json`. El resto del código no cambia: ese es el valor de MCP.
5. **Multi-agente (para el taller):** un agente "despachador" que use `tickets_por_vencer` y, por cada responsable, mande a un subagente que redacte el recordatorio de WhatsApp.

## Preguntas que te conviene llevar al evento

- ¿Cómo hacen evals cuando la respuesta correcta no es una lista de ids sino un texto?
- ¿MCP por stdio o por HTTP en producción? ¿Cómo lo autentican?
- ¿Cuándo vale la pena multi-agente y cuándo es complejidad de más?
