"""Subtitulador Brutal — utilidades compartidas."""
from __future__ import annotations
import os, re, subprocess, unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BIN = RAIZ / "bin"
FFMPEG = str(BIN / "ffmpeg") if (BIN / "ffmpeg").exists() else "ffmpeg"
FFPROBE = str(BIN / "ffprobe") if (BIN / "ffprobe").exists() else "ffprobe"
FUENTES = RAIZ / "fuentes"
FONTCONFIG = FUENTES / "fonts.conf"

def entorno():
    """libass necesita FONTCONFIG_FILE apuntando a nuestras fuentes (la máquina
    no tiene /etc/fonts)."""
    e = dict(os.environ)
    if FONTCONFIG.exists():
        e["FONTCONFIG_FILE"] = str(FONTCONFIG)
    return e

def correr(cmd, capturar=True, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True, env=entorno())
    if check and p.returncode != 0:
        raise RuntimeError(f"falló: {' '.join(str(c) for c in cmd[:6])}…\n{p.stderr[-1500:]}")
    return p

def clave_api(nombre="OPENAI_API_KEY") -> str:
    """Lee la clave del entorno (o del proceso de Hermes como último recurso)."""
    v = os.environ.get(nombre)
    if v:
        return v
    for cand in ("~/.hermes/.env", "/etc/hermes/env"):
        p = Path(cand).expanduser()
        if p.exists():
            for linea in p.read_text(errors="ignore").splitlines():
                if linea.startswith(nombre + "="):
                    return linea.split("=", 1)[1].strip().strip('"').strip("'")
    # environ del proceso de Hermes
    try:
        pid = subprocess.check_output(["pgrep", "-f", "hermes"], text=True).split()[0]
        for trozo in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            if trozo.startswith(nombre.encode() + b"="):
                return trozo.split(b"=", 1)[1].decode()
    except Exception:
        pass
    raise RuntimeError(f"no encuentro {nombre}")

def srt_tiempo(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

def ass_tiempo(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"

def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]+", " ", s)

def palabras(s: str):
    return [w for w in normalizar(s).split() if w]
