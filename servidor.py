#!/usr/bin/env python3
"""SUBTITULADOR BRUTAL — servidor local.

Subes un vídeo, eliges estilo y te lo devuelve subtitulado. El trabajo lo hace el
mismo motor del CLI (whisper + qwen3.6 de NaN + libass): este fichero solo pone la
puerta web y va contando por dónde va.

    python3 servidor.py            # abre http://127.0.0.1:8765
    python3 servidor.py --puerto 9000 --host 0.0.0.0     # accesible desde el móvil

Un trabajo a la vez: la máquina tiene 1 vCPU y quemar vídeo es lo más caro que hay
aquí. Los que lleguen mientras se trabaja esperan en cola.

Hecho con ❤️ por David Antizar
"""
from __future__ import annotations
import json, hmac, os, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from lib import estilos as EST          # noqa: E402
from lib import render as REN           # noqa: E402
from lib.util import FFMPEG, FFPROBE, huella   # noqa: E402

TRABAJOS = RAIZ / "trabajos"
TRABAJOS.mkdir(exist_ok=True)
PY = sys.executable
EXTENSIONES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mts", ".mpg", ".mpeg"}
# Límites que se ajustan por entorno: la app de NaN va más justa de disco que esta VM.
TAM_MAX = int(float(os.environ.get("SB_TAM_MAX_MB", "3072"))) * 1024 * 1024
HORAS_VIDA = float(os.environ.get("SB_HORAS_VIDA", "24"))
# Clave opcional. En una URL pública es lo que impide que cualquiera gaste la
# inferencia de la cuenta: sin ella, el primero que encuentre la dirección la usa.
CLAVE = os.environ.get("SB_CLAVE", "").strip()

app = FastAPI(title="Subtitulador Brutal", docs_url=None, redoc_url=None)
cola: list[tuple[str, dict]] = []        # trabajos esperando
candado = threading.Lock()
ocupado = threading.Event()


def carpeta(jid: str) -> Path:
    d = TRABAJOS / jid
    d.mkdir(parents=True, exist_ok=True)
    return d


def estado(jid: str) -> dict:
    f = carpeta(jid) / "estado.json"
    if not f.exists():
        raise HTTPException(404, "no existe ese trabajo")
    return json.loads(f.read_text(encoding="utf-8"))


def anota(jid: str, **campos):
    """Actualiza el estado del trabajo sin pisar lo que ya había."""
    d = estado(jid) if (carpeta(jid) / "estado.json").exists() else {"id": jid, "log": []}
    d.update(campos)
    d["actualizado"] = time.time()
    tmp = carpeta(jid) / "estado.json.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(carpeta(jid) / "estado.json")
    return d


def sondea(ruta: str) -> dict:
    """Duración y tamaño reales del vídeo subido (ffprobe)."""
    p = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", ruta], capture_output=True, text=True)
    try:
        d = json.loads(p.stdout or "{}")
        st = (d.get("streams") or [{}])[0]
        return {"ancho": st.get("width"), "alto": st.get("height"),
                "duracion": float(d.get("format", {}).get("duration") or 0)}
    except Exception:
        return {"ancho": None, "alto": None, "duracion": 0.0}

# ───────── el trabajo de verdad: llamar al motor y traducir su salida a progreso ─────────
# Las fases son las del CLI (1/5 VAD, 2/5 whisper, 3/5 qwen3.6, 4/5 ASS, 5/5 quema).
# La quema informa de su avance real con `-progress` de ffmpeg, no a ojo.
FASES = {
    "1/5": (6, "analizando el audio y buscando frases (VAD)"),
    "2/5": (16, "transcribiendo con whisper"),
    "3/5": (36, "corrigiendo y maquetando con qwen3.6"),
    "4/5": (46, "escribiendo los subtítulos"),
    "5/5": (48, "quemando los subtítulos en el vídeo"),
    "0/5": (40, "reutilizando una transcripción ya hecha"),
}


def _trabajar(jid: str, pedido: dict):
    d = carpeta(jid)
    video = d / pedido["fichero"]
    dur = float(pedido.get("duracion") or 0)
    anota(jid, estado="trabajando", fase=FASES["1/5"][1], pct=1, inicio=time.time())
    cmd = [PY, str(RAIZ / "subtitular.py"), str(video), "--estilo", pedido["estilo"],
           "-p", pedido.get("posicion", "bajo"),
           "-o", str(d / f"salida_{pedido['estilo']}.mp4")]
    if pedido.get("mayusculas"):
        cmd.append("--mayusculas")
    env = dict(os.environ, MM_PROGRESO="1")

    try:
        p = subprocess.Popen(cmd, cwd=str(RAIZ), env=env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             bufsize=1, errors="replace")
    except Exception as e:
        anota(jid, estado="error", error=f"no pude arrancar el motor: {e}", pct=0)
        return
    log = []
    for linea in p.stdout:
        linea = linea.rstrip()
        if not linea:
            continue
        if linea.startswith("PROGRESO"):
            # out_time_ms=… -> la quema va por el minuto X del vídeo
            if "out_time_ms=" in linea and dur > 0:
                try:
                    ms = int(linea.split("out_time_ms=")[1].split()[0].strip())
                    pct = 48 + 50 * min(1.0, (ms / 1_000_000) / dur)
                    anota(jid, pct=round(pct, 1))
                except (ValueError, IndexError):
                    pass
            continue
        log.append(linea)
        log[:] = log[-40:]
        for marca, (pc, texto) in FASES.items():
            if f"{marca} " in linea:
                anota(jid, fase=texto, pct=max(pc, estado(jid).get("pct", 0)))
                break
        if "tarjetas finales" in linea or "LISTO" in linea:
            anota(jid, pct=max(96, estado(jid).get("pct", 0)), aviso=linea.strip())
        anota(jid, log=log)
    codigo = p.wait()
    salida = d / f"salida_{pedido['estilo']}.mp4"
    if codigo == 0 and salida.exists():
        anota(jid, estado="listo", pct=100, fase="terminado", log=log,
              salida=salida.name, mb=round(salida.stat().st_size / 1e6, 1),
              segundos=round(time.time() - estado(jid)["inicio"], 1))
    else:
        cola_err = "\n".join(log[-14:]) or "sin salida"
        anota(jid, estado="error", pct=0, log=log,
              error=f"el motor falló (código {codigo}). Últimas líneas:\n{cola_err}")
    ocupado.clear()
    _siguiente()

def _siguiente():
    """Arranca el primero de la cola si la máquina está libre."""
    with candado:
        if ocupado.is_set() or not cola:
            return
        jid, pedido = cola.pop(0)
        ocupado.set()
    threading.Thread(target=_trabajar, args=(jid, pedido), daemon=True).start()


# ───────── la puerta (solo si hay SB_CLAVE) ─────────
LIBRES = ("", "/", "/vista.js", "/app.js", "/api/entrar", "/api/clave")


@app.middleware("http")
async def puerta(request: Request, call_next):
    if not CLAVE or request.url.path in LIBRES or request.url.path.startswith("/fuentes/"):
        return await call_next(request)
    traida = request.cookies.get("sb_clave") or request.headers.get("x-sb-clave", "")
    if not hmac.compare_digest(traida, CLAVE):
        return JSONResponse({"detail": "esta herramienta pide clave"}, status_code=401)
    return await call_next(request)


@app.get("/api/clave")
def hay_clave():
    """¿Está protegida? La página lo pregunta para pedirla solo cuando toca."""
    return {"protegida": bool(CLAVE)}


@app.post("/api/entrar")
def entrar(clave: str = Form(...)):
    if not CLAVE:
        return {"ok": True, "protegida": False}
    if not hmac.compare_digest(clave, CLAVE):
        raise HTTPException(403, "esa clave no es")
    r = JSONResponse({"ok": True, "protegida": True})
    r.set_cookie("sb_clave", clave, httponly=True, samesite="lax",
                 max_age=60 * 60 * 24 * 30, path="/")
    return r


# ───────── puerta web ─────────
@app.get("/")
def raiz():
    return FileResponse(RAIZ / "index.html")


@app.get("/vista.js")
@app.get("/app.js")
def estatico_propio(request: Request):
    """Los ficheros de la propia herramienta (whitelist: nada de servir el repo entero)."""
    nombre = Path(request.url.path).name
    if nombre not in ("vista.js", "app.js"):
        raise HTTPException(404, "ese fichero no se sirve")
    return FileResponse(RAIZ / nombre, media_type="application/javascript")


@app.get("/fuentes/{nombre}")
def fuente(nombre: str):
    f = (RAIZ / "fuentes" / nombre).resolve()
    if not str(f).startswith(str(RAIZ / "fuentes")) or not f.exists():
        raise HTTPException(404, "esa fuente no está")
    return FileResponse(f)


@app.get("/api/estilos")
def api_estilos():
    return [{"clave": k, "nombre": n, "descripcion": d} for k, n, d in EST.listar()]


@app.post("/api/videos")
async def subir(video: UploadFile = File(...)):
    ext = Path(video.filename or "video.mp4").suffix.lower()
    if ext not in EXTENSIONES:
        raise HTTPException(400, f"formato no soportado ({ext}). Prueba con mp4, mov o webm")
    jid = uuid.uuid4().hex[:12]
    d = carpeta(jid)
    destino = d / ("entrada" + ext)
    total = 0
    try:
        with destino.open("wb") as f:
            while True:
                trozo = await video.read(4 * 1024 * 1024)
                if not trozo:
                    break
                total += len(trozo)
                if total > TAM_MAX:
                    raise HTTPException(413, "el vídeo pasa de 3 GB: recórtalo o comprímelo")
                f.write(trozo)
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    if total == 0:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "el fichero llegó vacío")
    info = sondea(str(destino))
    anota(jid, estado="subido", pct=0, nombre=video.filename, fichero=destino.name,
          mb=round(total / 1e6, 1), log=[], error=None, salida=None, **info)
    return {"id": jid, "nombre": video.filename, "mb": round(total / 1e6, 1), **info}


@app.post("/api/videos/{jid}/subtitular")
def subtitular(jid: str, estilo: str = Form(...), posicion: str = Form("bajo"),
               mayusculas: bool = Form(False)):
    d = estado(jid)
    if estilo not in EST.ESTILOS:
        raise HTTPException(400, "ese estilo no existe")
    if d.get("estado") in ("en_cola", "trabajando"):
        raise HTTPException(409, "ese trabajo ya está en marcha")
    pedido = {"fichero": d["fichero"], "estilo": estilo, "posicion": posicion,
              "mayusculas": mayusculas, "duracion": d.get("duracion")}
    en_cola = ocupado.is_set() or bool(cola)
    anota(jid, estado="en_cola" if en_cola else "trabajando", estilo=estilo, pct=1,
          fase="esperando turno" if en_cola else "arrancando", log=[], error=None, salida=None)
    if en_cola:
        cola.append((jid, pedido))
        return {"id": jid, "estado": "en_cola", "delante": len(cola)}
    ocupado.set()
    threading.Thread(target=_trabajar, args=(jid, pedido), daemon=True).start()
    return {"id": jid, "estado": "trabajando"}


@app.get("/api/videos/{jid}/estado")
def api_estado(jid: str):
    return JSONResponse(estado(jid))


@app.get("/api/videos/{jid}/descarga")
def descargar(jid: str):
    d = estado(jid)
    if d.get("estado") != "listo" or not d.get("salida"):
        raise HTTPException(409, "ese vídeo todavía no está listo")
    f = carpeta(jid) / d["salida"]
    if not f.exists():
        raise HTTPException(410, "el fichero ya no está (los trabajos se limpian a las 24 h)")
    nombre = Path(d.get("nombre") or "video.mp4").stem + "." + d.get("estilo", "sub") + ".mp4"
    return FileResponse(f, media_type="video/mp4", filename=nombre)


@app.get("/api/videos/{jid}/subtitulos")
def subtitulos(jid: str):
    """El .srt de ese trabajo, para quien quiera retocar el texto en un editor."""
    d = estado(jid)
    estilo = d.get("estilo")
    if not estilo:
        raise HTTPException(409, "todavía no hay subtítulos para ese trabajo")
    f = RAIZ / "salidas" / f"{Path(d['fichero']).stem}.{estilo}.srt"
    if not f.exists():
        raise HTTPException(404, "el .srt todavía no está")
    return FileResponse(f, media_type="text/plain; charset=utf-8",
                        filename=Path(d.get("nombre") or "video").stem + f".{estilo}.srt")


@app.post("/api/videos/{jid}/fotograma")
def fotograma(jid: str, estilo: str = Form(...), posicion: str = Form("bajo"),
              mayusculas: bool = Form(False)):
    """Un fotograma REAL de su vídeo con los subtítulos puestos: la forma honesta de
    elegir estilo (el dibujo del selector es una aproximación)."""
    if ocupado.is_set():
        raise HTTPException(429, "el motor está ocupado: prueba cuando acabe")
    d = estado(jid)
    video = carpeta(jid) / d["fichero"]
    cmd = [PY, str(RAIZ / "subtitular.py"), str(video), "--estilo", estilo,
           "--solo-ass", "-p", posicion]
    if mayusculas:
        cmd.append("--mayusculas")
    p = subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        raise HTTPException(500, "no pude preparar el fotograma: " + (p.stderr or "")[-400:])
    ass = RAIZ / "salidas" / f"{video.stem}.{estilo}.ass"
    js = RAIZ / "salidas" / f"{video.stem}.{estilo}.json"
    if not ass.exists() or not js.exists():
        raise HTTPException(500, "el motor no dejó los subtítulos esperados")
    tarjetas = json.loads(js.read_text(encoding="utf-8"))["tarjetas"]
    if not tarjetas:
        raise HTTPException(422, "no he detectado voz en el audio de ese vídeo")
    c = tarjetas[1] if len(tarjetas) > 1 else tarjetas[0]
    t = (c["inicio"] + c["fin"]) / 2
    png = carpeta(jid) / f"muestra_{estilo}.png"
    REN.fotograma(str(video), t, str(png), ass=str(ass))
    return FileResponse(png, media_type="image/png", headers={"Cache-Control": "no-store"})

def limpiar_viejos():
    limite = time.time() - HORAS_VIDA * 3600
    for d in TRABAJOS.iterdir():
        if d.is_dir() and d.stat().st_mtime < limite:
            shutil.rmtree(d, ignore_errors=True)


limpiar_viejos()   # vale tanto por `python3 servidor.py` como por uvicorn directo


if __name__ == "__main__":
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description="Subtitulador Brutal — servidor local")
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 8765)))
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 para abrirlo también al móvil de casa")
    a = ap.parse_args()
    limpiar_viejos()
    print(f"\n  SUBTITULADOR BRUTAL — abre http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.puerto}")
    print(f"  trabajos: {TRABAJOS}")
    print(f"  un trabajo a la vez; los temporales se borran a las {HORAS_VIDA} h\n")
    uvicorn.run(app, host=a.host, port=a.puerto, log_level="warning")
