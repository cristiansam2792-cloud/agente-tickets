"""Página web del agente de tickets TIC para los jefes (solo red interna).

Sirve pagina.html y un endpoint /api/preguntar que llama a tu mismo agente
(agente.py -> server.py -> plataforma real). Cada jefe entra con su usuario.

Uso:
  python app_web.py --agregar-usuario abel     # crea o cambia la contraseña de un usuario
  python app_web.py                            # levanta la página en el puerto 8000

Variables opcionales:
  WEB_PUERTO   default 8000
  WEB_HOST     default 0.0.0.0 (todas las interfaces de la LAN)

Archivos que crea junto a este script:
  usuarios_web.json   usuarios con contraseña cifrada (hash), nunca en texto plano
  bitacora_web.jsonl  quién preguntó qué y cuándo
"""
import asyncio
import getpass
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

CARPETA = Path(__file__).resolve().parent
USUARIOS = CARPETA / "usuarios_web.json"
BITACORA = CARPETA / "bitacora_web.jsonl"
PAGINA = CARPETA / "pagina.html"
CACHE_TICKETS = CARPETA / "tickets_cache.json"
MAX_PREGUNTA = 500

os.environ.setdefault("TICKETS_FUENTE", "grupak")  # la página siempre usa datos reales
from agente import preguntar  # noqa: E402  (después de fijar TICKETS_FUENTE)


# ---------------------------------------------------------------- usuarios
def _hash(clave: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), 200_000).hex()


def _leer_usuarios() -> dict:
    return json.loads(USUARIOS.read_text(encoding="utf-8")) if USUARIOS.exists() else {}


def agregar_usuario(nombre: str):
    clave = getpass.getpass(f"Contraseña para {nombre}: ")
    if len(clave) < 8 or clave != getpass.getpass("Repítela: "):
        sys.exit("No coinciden o tiene menos de 8 caracteres. No se guardó nada.")
    usuarios = _leer_usuarios()
    sal = secrets.token_hex(16)
    usuarios[nombre.lower()] = {"sal": sal, "hash": _hash(clave, sal)}
    USUARIOS.write_text(json.dumps(usuarios, indent=1), encoding="utf-8")
    print(f"Usuario '{nombre.lower()}' guardado. Usuarios: {', '.join(sorted(usuarios))}")


seguridad = HTTPBasic(realm="Tickets TIC Grupak")


def usuario_actual(cred: HTTPBasicCredentials = Depends(seguridad)) -> str:
    u = _leer_usuarios().get(cred.username.lower())
    if not u or not secrets.compare_digest(_hash(cred.password, u["sal"]), u["hash"]):
        raise HTTPException(401, "Usuario o contraseña incorrectos",
                            headers={"WWW-Authenticate": 'Basic realm="Tickets TIC Grupak"'})
    return cred.username.lower()


# ---------------------------------------------------------------- agente
def _correr_agente(pregunta: str):
    """Corre el agente en su propio hilo y loop.

    En Windows los subprocesos de asyncio (el servidor MCP por stdio) necesitan el
    ProactorEventLoop; así no depende del loop que use el servidor web."""
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(preguntar(pregunta, verbose=False))
    finally:
        loop.close()


_bitacora_lock = threading.Lock()


def _anotar(registro: dict):
    with _bitacora_lock, BITACORA.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- web
app = FastAPI(title="Agente de tickets TIC", docs_url=None, redoc_url=None, openapi_url=None)


class Intercambio(BaseModel):
    pregunta: str = Field(max_length=MAX_PREGUNTA)
    respuesta: str = Field(max_length=4000)


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=3, max_length=MAX_PREGUNTA)
    historial: list[Intercambio] = Field(default_factory=list, max_length=2)


@app.get("/")
def inicio(usuario: str = Depends(usuario_actual)):
    return FileResponse(PAGINA, headers={"Cache-Control": "no-store"})


@app.get("/api/estado")
def estado(usuario: str = Depends(usuario_actual)):
    edad = None
    if CACHE_TICKETS.exists():
        edad = round((time.time() - CACHE_TICKETS.stat().st_mtime) / 60)
    return {"usuario": usuario, "datos_minutos": edad}


@app.post("/api/preguntar")
async def api_preguntar(p: Pregunta, usuario: str = Depends(usuario_actual)):
    texto = p.pregunta.strip()
    if p.historial:  # seguimiento: el agente no tiene memoria, le pasamos lo reciente
        previo = "\n\n".join(f"Pregunta: {h.pregunta}\nRespuesta: {h.respuesta[:1500]}"
                             for h in p.historial)
        texto = (f"Contexto de la conversación (solo como referencia; vuelve a consultar "
                 f"las herramientas para datos actuales):\n{previo}\n\nNueva pregunta: {texto}")

    t0 = time.time()
    registro = {"fecha": datetime.now().isoformat(timespec="seconds"), "usuario": usuario,
                "pregunta": p.pregunta.strip()}
    try:
        respuesta, herramientas = await asyncio.to_thread(_correr_agente, texto)
    except Exception as e:  # noqa: BLE001 - se reporta al usuario y a la bitácora
        registro.update(error=f"{type(e).__name__}: {e}", segundos=round(time.time() - t0, 1))
        _anotar(registro)
        raise HTTPException(502, "No pude consultar los tickets en este momento. "
                                 "Intenta de nuevo en un minuto.") from e

    registro.update(herramientas=herramientas, segundos=round(time.time() - t0, 1))
    _anotar(registro)
    return {"respuesta": respuesta, "herramientas": herramientas, "segundos": registro["segundos"]}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--agregar-usuario":
        agregar_usuario(sys.argv[2])
        sys.exit()
    if not _leer_usuarios():
        sys.exit("Primero crea al menos un usuario: python app_web.py --agregar-usuario <nombre>")
    puerto = int(os.environ.get("WEB_PUERTO", "8000"))
    print(f"Página lista en http://<ip-de-este-equipo>:{puerto}  (Ctrl+C para detener)")
    uvicorn.run(app, host=os.environ.get("WEB_HOST", "0.0.0.0"), port=puerto, log_level="warning")
