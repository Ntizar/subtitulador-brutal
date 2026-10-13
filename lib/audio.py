"""Fase 1 — del vídeo al audio: duración, extracción y detección de frases (VAD).

La clave del invento: whisper de la API de NaN NO devuelve timestamps por palabra
y con audio largo devuelve segmentos de 20-30 s (y a veces se come frases).
Así que troceamos el audio por FRASES NATURALES usando silencedetect de ffmpeg
y transcribimos cada trozo por separado: timing exacto y cero pérdida de texto.
"""
from __future__ import annotations
import json, re, shutil, tempfile
from dataclasses import dataclass
from pathlib import Path
from .util import FFMPEG, FFPROBE, correr


@dataclass
class Frase:
    inicio: float
    fin: float
    @property
    def dur(self) -> float:
        return self.fin - self.inicio


def sonda(video: str) -> dict:
    p = correr([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", video])
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise RuntimeError("el fichero no tiene pista de vídeo")
    if not a:
        raise RuntimeError("el fichero no tiene pista de audio: no hay nada que subtitular")
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    fps = round(float(num) / float(den), 3) if float(den) else 0.0
    return {
        "ancho": int(v["width"]), "alto": int(v["height"]), "fps": fps,
        "duracion": float(d["format"].get("duration") or 0),
        "audio_hz": int(a.get("sample_rate") or 0), "audio_ch": int(a.get("channels") or 0),
        "bitrate": int(d["format"].get("bit_rate") or 0),
    }


def extraer_audio(video: str, destino: str, hz: int = 16000) -> str:
    correr([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", video,
            "-vn", "-ac", "1", "-ar", str(hz), "-c:a", "pcm_s16le", destino])
    return destino


def silencios(wav: str, ruido_db: float = -32.0, min_s: float = 0.28):
    """Devuelve (frases_de_voz, duracion_total)."""
    p = correr([FFMPEG, "-hide_banner", "-i", wav,
                "-af", f"silencedetect=noise={ruido_db}dB:d={min_s}", "-f", "null", "-"], check=False)
    err = p.stderr
    dur = None
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    voz, cur = [], 0.0
    for s, e in zip(ini, fin):
        if s - cur > 0.12:
            voz.append(Frase(cur, s))
        cur = e
    if dur and dur - cur > 0.12:
        voz.append(Frase(cur, dur))
    return voz, (dur or 0.0)


def agrupar(frases, min_s: float = 1.15, max_s: float = 5.5, max_gap: float = 0.55):
    """Fusiona micro-frases (whisper alucina con trozos <1 s sin contexto) y
    parte las demasiado largas. Devuelve las tarjetas base para transcribir."""
    acum = []
    for f in frases:
        if acum:
            ult = acum[-1]
            # fusiona si el hueco es pequeño y no nos pasamos de duración
            if (f.inicio - ult.fin) <= max_gap and (f.fin - ult.inicio) <= max_s:
                ult.fin = f.fin
                continue
            # si la anterior es demasiado corta, fusiónala aunque el hueco sea mayor
            if ult.dur < min_s and (f.inicio - ult.inicio) <= max_s:
                ult.fin = f.fin
                continue
        acum.append(Frase(f.inicio, f.fin))
    # última tarjeta corta -> se pega a la anterior
    if len(acum) > 1 and acum[-1].dur < min_s:
        acum[-2].fin = acum[-1].fin
        acum.pop()
    return [Frase(round(f.inicio, 3), round(f.fin, 3)) for f in acum]


def cortar(wav: str, f: Frase, destino: str, mp3: bool = True):
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{f.inicio:.3f}", "-t", f"{f.dur + 0.08:.3f}", "-i", wav,
           "-ar", "16000", "-ac", "1"]
    if mp3:
        cmd += ["-c:a", "libmp3lame", "-q:a", "5"]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    correr(cmd + [destino])
    return destino


def trocear(video: str, tmp: str | None = None, ruido_db: float = -32.0) -> tuple[list[Frase], dict, str]:
    """Devuelve (tarjetas, info_video, carpeta_temporal)."""
    info = sonda(video)
    tmp = tmp or tempfile.mkdtemp(prefix="subti_")
    wav = str(Path(tmp) / "audio.wav")
    extraer_audio(video, wav)
    frases, dur = silencios(wav, ruido_db=ruido_db)
    tarjetas = agrupar(frases)
    if not tarjetas:
        raise RuntimeError("no he detectado voz en el audio (¿es música sin voz?)")
    return tarjetas, info, tmp


def sonda_idioma(wav: str, destino: str, segundos: float = 25.0) -> str:
    """Trozo largo (25 s) para que whisper acierte el idioma: con una sola frase
    corta se equivoca."""
    correr([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-t", f"{segundos:.1f}",
            "-i", wav, "-ar", "16000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "5", destino])
    return destino


def limpiar(tmp: str):
    shutil.rmtree(tmp, ignore_errors=True)
