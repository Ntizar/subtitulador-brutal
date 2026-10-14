"""Fase 2 — transcripción con whisper de NaN, un trozo por frase, en paralelo.

Aprendido a base de probar la API de verdad (2026-10-13):
  - `response_format=verbose_json` acepta `timestamp_granularities[]` pero IGNORA
    el parámetro: `words` siempre es null. No hay timestamps por palabra.
  - Si no se pasa `language`, detecta mal el español (dice "en").
  - Con chunks de menos de ~1,2 s alucina cosas tipo "¡Oyter Ser!": por eso el
    troceo los fusiona. `prompt` se acepta pero NO arregla un chunk sin contexto:
    la segunda pasada solo reintenta los que salen con poca confianza.
  - El modelo se llama `whisper` a secas (no `whisper-1`).
"""
from __future__ import annotations
import json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.nan.builders/v1/audio/transcriptions"


@dataclass
class Trozo:
    i: int
    inicio: float
    fin: float
    texto: str = ""
    confianza: float = 0.0
    idioma: str = ""
    intentos: int = 0
    fichero: str = ""
    notas: list = field(default_factory=list)

    @property
    def dur(self) -> float:
        return self.fin - self.inicio


class Whisper:
    def __init__(self, clave: str, modelo: str = "whisper", hilos: int = 5, timeout: int = 180):
        self.clave, self.modelo, self.hilos, self.timeout = clave, modelo, hilos, timeout

    def _peticion(self, ruta: str, idioma: str | None, prompt: str | None) -> dict:
        cmd = ["curl", "-s", "-m", str(self.timeout), API,
               "-H", f"Authorization: Bearer {self.clave}",
               "-H", "User-Agent: Mozilla/5.0",
               "-F", f"file=@{ruta}", "-F", f"model={self.modelo}",
               "-F", "response_format=verbose_json"]
        if idioma:
            cmd += ["-F", f"language={idioma}"]
        if prompt:
            cmd += ["-F", f"prompt={prompt[:900]}"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(p.stdout)
        except Exception:
            return {"_error": (p.stdout or p.stderr or "")[:300]}

    def uno(self, t: Trozo, idioma: str | None, prompt: str | None = None) -> Trozo:
        r = self._peticion(t.fichero, idioma, prompt)
        t.intentos += 1
        if "_error" in r:
            t.notas.append(r["_error"])
            return t
        t.texto = (r.get("text") or "").strip()
        segs = r.get("segments") or []
        t.idioma = r.get("language") or t.idioma
        if segs:
            t.confianza = sum(s.get("avg_logprob", -1.0) for s in segs) / len(segs)
        return t

    def transcribir(self, trozos: list[Trozo], idioma: str | None = None,
                    sonda: str | None = None,
                    segunda_pasada: bool = True, umbral_confianza: float = -0.75,
                    avisar=None) -> list[Trozo]:
        """`sonda` = fichero de audio largo (20-30 s) para detectar el idioma.

        OJO: con audio corto (una frase suelta) whisper detecta mal el idioma
        (dice `en` con voz en español, comprobado). Con 25 s acierta.
        """
        pendientes = list(trozos)
        if not idioma:
            # El idioma lo decide el trozo MÁS LARGO, no el primero: un trozo corto
            # detecta mal el idioma (dice `en` con español) y preguntárselo a una
            # sonda aparte cuesta una llamada entera —hasta 25 s de audio que se
            # tiraban a la basura—: medido, 3,4 s de un vídeo de 16 s. Con el trozo
            # largo se reutiliza su transcripción y no se paga nada extra.
            ref_t = None
            if sonda is None and trozos:
                largo = max(trozos, key=lambda t: t.dur)
                if largo.dur >= 1.5:
                    ref_t = largo
            ref = sonda or (ref_t.fichero if ref_t else (trozos[0].fichero if trozos else None))
            if not ref:
                raise RuntimeError("no hay audio para detectar el idioma")
            r = self._peticion(ref, None, None)
            idioma = (r.get("language") or "es") if isinstance(r, dict) else "es"
            if avisar:
                avisar(f"idioma detectado: {idioma}"
                       + (" (trozo de %.1fs)" % ref_t.dur if ref_t else " (sonda)"))
            if sonda is None and trozos:
                # la referencia era un trozo nuestro: reaprovecha su transcripción
                t0 = ref_t if ref_t is not None else trozos[0]
                t0.texto = (r.get("text") or "").strip()
                t0.idioma = idioma
                segs = r.get("segments") or []
                if segs:
                    t0.confianza = sum(s.get("avg_logprob", -1.0) for s in segs) / len(segs)
                if t0.texto:
                    pendientes = [t for t in trozos if t is not t0]

        # pasada en paralelo, sin prompt (el prompt impide paralelizar)
        with ThreadPoolExecutor(max_workers=self.hilos) as ex:
            hechos = list(ex.map(lambda t: self.uno(t, idioma), pendientes))
        salida = sorted([t for t in trozos if t.texto] + [t for t in hechos if t not in trozos],
                        key=lambda t: t.i)
        faltan = [t for t in trozos if not t.texto]
        if faltan:
            with ThreadPoolExecutor(max_workers=self.hilos) as ex:
                salida = sorted(list(ex.map(lambda t: self.uno(t, idioma), faltan)) + salida,
                                key=lambda t: t.i)

        # 3) segunda pasada SOLO para los trozos de baja confianza, ahora con el
        #    contexto del vecino anterior ya transcrito (arregla las alucinaciones)
        if segunda_pasada:
            malos = [t for t in salida if t.texto and t.confianza < umbral_confianza]
            cortos = [t for t in salida if t.texto and len(t.texto.split()) <= 1 and t.dur < 0.9]
            revisar = sorted({id(t): t for t in malos + cortos}.values(), key=lambda t: t.i)
            if revisar and avisar:
                avisar(f"segunda pasada en {len(revisar)} trozos con poca confianza")
            def rep(t):
                prev = next((x for x in salida if x.i == t.i - 1 and x.texto), None)
                if not prev:
                    return t
                antes = (t.confianza, t.texto, t.intentos)
                self.uno(t, idioma, prompt=prev.texto)
                t.notas.append(f"2ª pasada conf {antes[0]:.2f}->{t.confianza:.2f}")
                return t
            with ThreadPoolExecutor(max_workers=max(2, self.hilos // 2)) as ex:
                list(ex.map(rep, revisar))
        return sorted(salida, key=lambda t: t.i)

    @staticmethod
    def idioma_fijado(t: Trozo) -> bool:
        return bool(t.idioma)
