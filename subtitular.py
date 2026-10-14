#!/usr/bin/env python3
"""SUBTITULADOR BRUTAL — subtitula cualquier vídeo, del largo que sea, con
whisper + qwen3.6 de la API de NaN y 8 estilos animados quemados con libass.

  subtitular.py video.mp4 --estilo bestia
  subtitular.py video.mp4 --estilo karaoke --solo-ass      (no recodifica)
  subtitular.py --listar-estilos

Hecho con ❤️ por David Antizar
"""
from __future__ import annotations
import argparse, os, shutil, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from lib import audio as AUD          # noqa: E402
from lib import estilos as EST        # noqa: E402
from lib import llm as LLM            # noqa: E402
from lib import render as REN         # noqa: E402
from lib import tarjetas as TAR       # noqa: E402
from lib.stt import Trozo, Whisper    # noqa: E402
from lib.util import clave_api, huella   # noqa: E402

T0 = time.time()


def log(msg: str):
    print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Subtitulador Brutal — subtítulos animados con la API de NaN",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", help="vídeo de entrada")
    ap.add_argument("-e", "--estilo", default="carta", help="estilo (ver --listar-estilos)")
    ap.add_argument("-p", "--posicion", default="bajo", choices=["bajo", "medio", "alto"])
    ap.add_argument("-o", "--salida", help="vídeo de salida (por defecto <nombre>.<estilo>.mp4)")
    ap.add_argument("--idioma", default=None, help="código de idioma (es, en…). Vacío = detectar")
    ap.add_argument("--solo-ass", action="store_true", help="no recodifica: escribe .ass y .srt")
    ap.add_argument("--sin-llm", action="store_true", help="sin qwen3.6 (parte por reglas)")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--hilos", type=int, default=5, help="peticiones de whisper en paralelo")
    ap.add_argument("--modelo", default="qwen3.6",
                    help="modelo de NaN para corregir y maquetar el texto (qwen3.6, qwen3.8-flash…)")
    ap.add_argument("--plazo", type=float,
                    help="segundos máximos para el paso de texto; si se pasa, ese lote va por reglas "
                         "(por defecto: 40%% de la duración del vídeo)")
    ap.add_argument("--ruido", type=float, default=-32.0, help="dB del silencio (VAD)")
    ap.add_argument("--escala", type=float, help="tamaño de fuente (fracción de la altura)")
    ap.add_argument("--mayusculas", action="store_true", default=None)
    ap.add_argument("--limite", type=float, help="procesa solo los primeros N segundos (pruebas)")
    ap.add_argument("--desde-json", help="reutiliza una transcripción ya hecha (probar estilos sin gastar API)")
    ap.add_argument("--rehacer", action="store_true",
                    help="ignora la caché de transcripción y vuelve a transcribir")
    ap.add_argument("--listar-estilos", action="store_true")
    a = ap.parse_args(argv)

    if a.listar_estilos:
        print("\n  ESTILOS DEL SUBTITULADOR BRUTAL\n")
        for k, n, d in EST.listar():
            print(f"  {k:11s} {n:22s} {d}")
        print()
        return 0
    if not a.video:
        ap.error("falta el vídeo de entrada (o usa --listar-estilos)")
    if a.estilo not in EST.ESTILOS:
        ap.error(f"estilo desconocido: {a.estilo}. Usa --listar-estilos")
    if not Path(a.video).exists():
        ap.error(f"no existe el fichero: {a.video}")

    clave = clave_api()
    salida_dir = RAIZ / "salidas"
    salida_dir.mkdir(exist_ok=True)
    nombre = Path(a.video).stem
    if a.limite:
        recorte = str(RAIZ / "salidas" / f".recorte_{nombre}.mp4")
        log(f"recortando los primeros {a.limite}s para la prueba")
        AUD.correr([AUD.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-t", str(a.limite), "-i", a.video, "-c", "copy", recorte])
        entrada = recorte
    else:
        entrada = a.video

    # ---- 1) audio y VAD
    cards = None
    tmp = None
    frases = []
    ruta_cache = None
    if a.desde_json:                       # atajo: solo se rehace el ASS
        log("0/5 reutilizando transcripción de " + a.desde_json)
        cards, info = TAR.cargar_json(a.desde_json)
        log(f"    {len(cards)} tarjetas cargadas ({info.get('ancho')}x{info.get('alto')})")
    if cards is None:
        # Caché: mismo audio + mismos ajustes = misma transcripción. Sin esto, probar
        # los 8 estilos transcribiría el MISMO audio 8 veces (8 veces el coste).
        cache_dir = salida_dir / ".cache"
        cache_dir.mkdir(exist_ok=True)
        ruta_cache = cache_dir / (f"{nombre}.{huella(entrada)}"
                                  f".r{a.ruido}.i{a.idioma}.llm{int(not a.sin_llm)}.json")
        if ruta_cache.exists() and not a.rehacer:
            log(f"0/5 reutilizando transcripción guardada ({ruta_cache.name})")
            cards, info = TAR.cargar_json(str(ruta_cache))
            log(f"    {len(cards)} tarjetas cargadas; la API no se toca (--rehacer para rehacerla)")
    if cards is None:
        log("1/5 analizando audio y detectando frases (VAD por silencios)")
        frases, info, tmp = AUD.trocear(entrada, ruido_db=a.ruido)
        log(f"    vídeo {info['ancho']}x{info['alto']} @{info['fps']}fps, "
            f"{info['duracion']:.1f}s -> {len(frases)} frases a transcribir")
        if a.limite:
            frases = [f for f in frases if f.inicio < a.limite]

        # ---- 2) trozos de audio + transcripción
        trozos = []
        for i, f in enumerate(frases):
            p = str(Path(tmp) / f"t{i:05d}.mp3")
            AUD.cortar(str(Path(tmp) / "audio.wav"), f, p)
            trozos.append(Trozo(i=i, inicio=f.inicio, fin=f.fin, fichero=p))
        log(f"2/5 transcribiendo con whisper ({len(trozos)} trozos, {a.hilos} en paralelo)")
        wh = Whisper(clave, hilos=a.hilos)
        sonda = None
        if not a.idioma and frases:
            # La sonda (una llamada extra con hasta 25 s de audio) solo hace falta si
            # NINGUNA frase llega a 1,5 s: entonces no hay trozo del que fiarse para
            # detectar el idioma. Con una frase larga, ese trozo hace de sonda gratis.
            if max(f.fin - f.inicio for f in frases) < 1.5:
                sonda = AUD.sonda_idioma(str(Path(tmp) / "audio.wav"), str(Path(tmp) / "sonda.mp3"),
                                         segundos=min(25.0, max(8.0, info["duracion"])))
        trozos = wh.transcribir(trozos, idioma=a.idioma, sonda=sonda,
                                avisar=lambda m: log("    " + m))
        ok = [t for t in trozos if t.texto]
        log(f"    {len(ok)}/{len(trozos)} trozos con texto"
            + (f", idioma {ok[0].idioma}" if ok else ""))

        # ---- 3) el modelo corrige y maqueta
        maquetado = {}
        if not a.sin_llm and ok:
            # Plazo: el paso de texto es el único que depende de una API compartida y
            # puede tardar de 5 a 20 s con el MISMO input. Con fecha límite, un lote
            # lento se cae a las reglas (cobertura 1.0 por construcción) y el vídeo
            # nunca tarda más de lo que dura.
            plazo = a.plazo or max(20.0, min(240.0, info["duracion"] * 0.4))
            log(f"3/5 {a.modelo} corrigiendo erratas y partiendo en bloques (plazo {plazo:.0f}s)")
            try:
                q = LLM.Qwen(clave, modelo=a.modelo, timeout=int(plazo))
                maquetado = q.maquetar([{"i": t.i, "texto": t.texto} for t in ok],
                                       avisar=lambda m: log("    " + m))
            except Exception as e:
                log(f"    {a.modelo} falló ({e}); sigo con el reparto por reglas")
        else:
            log("3/5 sin LLM (reparto por reglas)")

        cards = TAR.construir_todas(trozos, maquetado)
        malas = [c for c in cards if c.fuente == "reglas"]
        log(f"    {len(cards)} tarjetas finales ({len(malas)} por reglas por pérdida de texto)")
        idioma_final = ok[0].idioma if ok else ""
        if ruta_cache is not None:          # guardar para los próximos estilos
            REN.escribir_json(cards, info, str(ruta_cache),
                              {"estilo": "(caché)", "lineas_total": len(cards),
                               "frases": len(frases), "idioma": idioma_final})
            log(f"    transcripción guardada en {ruta_cache.name} (reutilizable por otros estilos)")
    else:
        idioma_final = info.get("idioma", "") or ""

    # ---- 4) ASS / SRT / JSON
    est = EST.ESTILOS[a.estilo]
    nombre_sal = f"{nombre}.{a.estilo}"
    ruta_ass = str(salida_dir / f"{nombre_sal}.ass")
    meta = REN.escribir_ass(cards, info, a.estilo, ruta_ass, posicion=a.posicion,
                            escala=a.escala, mayusculas=a.mayusculas)
    REN.escribir_srt(cards, str(salida_dir / f"{nombre_sal}.srt"))
    REN.escribir_json(cards, info, str(salida_dir / f"{nombre_sal}.json"),
                      {"estilo": a.estilo, "lineas_total": len(cards),
                       "frases": len(frases), "idioma": idioma_final})
    log(f"4/5 subtítulos escritos: {nombre_sal}.ass / .srt / .json "
        f"({meta['estilo']}: fuente {meta['fuente']} {meta['tamano']}px, "
        f"máx {meta['max_caracteres']} car/beat)")

    # ---- 5) quema
    if a.solo_ass:
        log("5/5 --solo-ass: no se recodifica el vídeo")
        print(f"\n  ASS: {ruta_ass}")
        if tmp:
            AUD.limpiar(tmp)
        return 0
    destino = a.salida or str(salida_dir / f"{nombre_sal}.mp4")
    log(f"5/5 quemando subtítulos en el vídeo (x264 {a.preset} crf{a.crf})…")
    t = time.time()
    REN.quemar(entrada, ruta_ass, destino, crf=a.crf, preset=a.preset)
    log(f"    quemado en {time.time()-t:.1f}s")

    if a.limite and Path(a.video).resolve() != Path(entrada).resolve():
        Path(entrada).unlink(missing_ok=True)
    if tmp:
        AUD.limpiar(tmp)
    mb = Path(destino).stat().st_size / 1e6
    print(f"\n  ✅ LISTO  ->  {destino}  ({mb:.1f} MB)")
    print(f"     estilo: {meta['estilo']}   tarjetas: {len(cards)}   "
          f"acelerado: {'sí' if a.hilos>1 else 'no'}")
    print(f"     total: {time.time()-T0:.1f}s\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrumpido")
        sys.exit(130)
    except Exception as e:
        print(f"\n  ❌ {e}\n", file=sys.stderr)
        sys.exit(1)
