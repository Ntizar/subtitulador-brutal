"""Fase 6 — salida: ASS/SRT/JSON y quema con libass (ffmpeg estático)."""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path

from .estilos import generar_ass, ESTILOS
from .util import FFMPEG, correr, srt_tiempo, entorno


def escribir_ass(cards, info, estilo: str, ruta: str, **op) -> dict:
    texto, meta = generar_ass(cards, info, estilo, **op)
    Path(ruta).write_text(texto, encoding="utf-8")
    return meta


def escribir_srt(cards, ruta: str):
    trozos = []
    for n, c in enumerate(cards, 1):
        # SRT multilingüe: original arriba y debajo cada traducción pedida, en su orden
        lineas = [c.texto]
        for campo in ("texto_2", "texto_3"):
            t = (getattr(c, campo, "") or "").strip()
            if t:
                lineas.append(t)
        trozos.append(f"{n}\n{srt_tiempo(c.inicio)} --> {srt_tiempo(c.fin)}\n"
                      + "\n".join(lineas) + "\n")
    Path(ruta).write_text("\n".join(trozos), encoding="utf-8")


def escribir_json(cards, info, ruta: str, extra: dict | None = None):
    d = {
        "generado_por": "Subtitulador Brutal",
        "info": info,
        "tarjetas": [c.dict() if hasattr(c, "dict") else c for c in cards],
    }
    if extra:
        d.update(extra)
    Path(ruta).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def quemar(video: str, ass: str, salida: str, crf: int = 20, preset: str = "veryfast",
           audio: str = "aac", avisar=None) -> str:
    """Quema los subtítulos dentro del vídeo. libass necesita FONTCONFIG_FILE,
    y el filtro ass= se lanza con el cwd en la carpeta del .ass para que las
    rutas con espacios o dos puntos no rompan el filtro.

    Con MM_PROGRESO=1 va informando del avance REAL (ffmpeg lo manda por stdout):
    es lo que permite una barra que no miente en la web."""
    ass = str(Path(ass).resolve())
    carpeta, fichero = os.path.split(ass)
    salida_abs = str(Path(salida).resolve())
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-i", str(Path(video).resolve()),
           "-vf", f"ass={fichero}",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-movflags", "+faststart"]
    if audio == "copia":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    seguir = bool(os.environ.get("MM_PROGRESO"))
    if seguir:
        cmd += ["-progress", "pipe:1"]      # antes del fichero de salida, no después
    cmd += [salida_abs]
    if seguir:
        p = subprocess.Popen(cmd, cwd=carpeta, env=entorno(), text=True, bufsize=1,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for linea in p.stdout:
            if linea.startswith(("out_time_ms=", "out_time_us=", "progress=")):
                print("PROGRESO " + linea.strip(), flush=True)
        error = p.stderr.read()
        if p.wait() != 0:
            raise RuntimeError("falló la quema con ffmpeg:\n" + (error or "")[-2000:])
        return salida
    p = subprocess.run(cmd, cwd=carpeta, capture_output=True, text=True, env=entorno())
    if p.returncode != 0:
        raise RuntimeError("falló la quema con ffmpeg:\n" + (p.stderr or "")[-2000:])
    return salida


def fotograma(video: str, t: float, salida: str, ass: str | None = None) -> str:
    """Extrae un fotograma. IMPORTANTE: el -ss va DESPUÉS del -i (búsqueda de
    salida), porque si no libass reinicia su reloj a 0 y pinta el primer
    subtítulo en todos los fotogramas."""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(Path(video).resolve())]
    if ass:
        a = str(Path(ass).resolve())
        cmd += ["-vf", f"ass={os.path.basename(a)}"]
    cmd += ["-ss", f"{t:.3f}", "-frames:v", "1", str(Path(salida).resolve())]
    cwd = os.path.dirname(str(Path(ass).resolve())) if ass else None
    p = subprocess.run(cmd, capture_output=True, text=True, env=entorno(), cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError("no pude extraer el fotograma:\n" + (p.stderr or "")[-800:])
    return salida
