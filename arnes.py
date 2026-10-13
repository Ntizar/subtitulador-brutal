#!/usr/bin/env python3
"""Arnés de verificación del Subtitulador Brutal.

No se fía de que "el comando terminó bien": comprueba el resultado.
  1. ESTRUCTURA  los tiempos cuadran (orden, sin solapes, dentro del vídeo,
                 palabras dentro de su bloque)
  2. COBERTURA   todas las tarjetas están en el .ass y en el .srt
  3. RENDER      extrae fotogramas reales con el ASS aplicado y mide si hay
                 TINTA en la banda de subtítulos (si el texto no se pinta,
                 libass no encuentra la fuente y el filtro sale limpio)
  4. CAMBIO      los fotogramas de momentos distintos deben ser distintos
                 (si no, el -ss está mal puesto y libass repinta el primero)

Uso:
  python arnes.py --video pruebas/video_prueba.mp4 --json salidas/x.json --estilos todos
"""
from __future__ import annotations
import argparse, json, os, hashlib, re, subprocess, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from lib import estilos as EST, render as REN, tarjetas as TAR, audio as AUD  # noqa
from lib.util import FFMPEG, FFMPEG as FF, entorno, normalizar  # noqa

FALLOS: list[str] = []
AVISOS: list[str] = []


def ok(txt):   print(f"  ✅ {txt}")
def no(txt):   FALLOS.append(txt); print(f"  ❌ {txt}")
def ojo(txt):  AVISOS.append(txt); print(f"  ⚠️  {txt}")


def comprobar_estructura(cards, info):
    print("\n1) ESTRUCTURA")
    if not cards:
        no("no hay tarjetas"); return
    dur = info.get("duracion") or max(c.fin for c in cards)
    desorden = [c.i for a, c in zip(cards, cards[1:]) if c.inicio < a.inicio]
    if desorden:
        no(f"tarjetas desordenadas: {desorden[:5]}")
    else:
        ok(f"{len(cards)} tarjetas ordenadas por tiempo")
    solapes = [(a.i, b.i) for a, b in zip(cards, cards[1:]) if b.inicio < a.fin - 0.001]
    if solapes:
        ojo(f"{len(solapes)} pares con solape de tiempo (ej. {solapes[:3]})")
    else:
        ok("sin solapes entre tarjetas")
    fuera = [c.i for c in cards if c.fin > dur + 0.5]
    if fuera:
        no(f"{len(fuera)} tarjetas acaban después del vídeo ({dur:.1f}s): {fuera[:5]}")
    else:
        ok(f"todas las tarjetas dentro del vídeo ({dur:.1f}s)")
    malas = []
    for c in cards:
        if c.palabras:
            if c.palabras[0]["a"] if isinstance(c.palabras[0], dict) else c.palabras[0].a:
                pass
            ps = [p if isinstance(p, dict) else {"w": p.w, "a": p.a, "b": p.b} for p in c.palabras]
            for p in ps:
                if p["a"] < c.inicio - 0.05 or p["b"] > c.fin + 0.05 or p["b"] <= p["a"]:
                    malas.append((c.i, p["w"]))
        else:
            malas.append((c.i, "(sin palabras)"))
    if malas:
        no(f"{len(malas)} palabras con tiempos fuera de su tarjeta: {malas[:5]}")
    else:
        ok("los tiempos de palabra caen dentro de su tarjeta")
    cortas = [c.i for c in cards if c.fin - c.inicio < 0.20]
    if cortas:
        ojo(f"{len(cortas)} tarjetas duran menos de 0,2 s (se leerán mal): {cortas[:5]}")
    largas = [c.i for c in cards if c.fin - c.inicio > 4.0]
    if largas:
        ojo(f"{len(largas)} tarjetas duran más de 4 s: {largas[:5]}")
    if not cortas and not largas:
        ok("duraciones de tarjeta dentro del rango legible")


def comprobar_cobertura(cards, ruta_ass, ruta_srt):
    print("\n2) COBERTURA (.ass / .srt)")
    ass = Path(ruta_ass).read_text(encoding="utf-8")
    srt = Path(ruta_srt).read_text(encoding="utf-8")
    faltan_ass, faltan_srt = [], []
    for c in cards:
        for w in (c.palabras[0]["w"] if c.palabras and isinstance(c.palabras[0], dict)
                  else (c.palabras[0].w if c.palabras else c.texto.split()[0]),):
            break
        primera = normalizar(c.texto.split()[0]) if c.texto.split() else ""
        if primera and primera not in normalizar(ass):
            faltan_ass.append(c.i)
        if primera and primera not in normalizar(srt):
            faltan_srt.append(c.i)
    if faltan_ass or faltan_srt:
        no(f"tarjetas que no aparecen: ass={faltan_ass[:5]} srt={faltan_srt[:5]}")
    else:
        ok(f"las {len(cards)} tarjetas están en el .ass y en el .srt")
    eventos = len(re.findall(r"^Dialogue:", ass, re.M))
    estilos = re.findall(r"^Style: (\w+),([^,]+),(\d+)", ass, re.M)
    if not estilos:
        no("el .ass no declara ningún estilo")
    else:
        for n, fuente, fs in estilos:
            ok(f"estilo declarado: {n} -> {fuente} {fs}px")
    ok(f"{eventos} eventos de subtítulo (incluye un evento por palabra resaltada)")


def tinta_y_hash(png: str):
    """Devuelve (desviación típica de la banda inferior, md5 del fichero).

    La banda se extrae en crudo (gris) y se mide en Python: si libass no
    encuentra la fuente, el fotograma sale limpio y la desviación cae a ~0.
    """
    p = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", png,
                        "-vf", "crop=iw:ih*0.18:0:ih*0.80,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, env=entorno())
    d = p.stdout
    if not d:
        return -1.0, hashlib.md5(Path(png).read_bytes()).hexdigest()[:10]
    n = len(d)
    media = sum(d) / n
    var = sum((x - media) ** 2 for x in d) / n
    return var ** 0.5, hashlib.md5(Path(png).read_bytes()).hexdigest()[:10]


def comprobar_render(cards, info, video, clave_estilo, carpeta):
    ass = str(Path(carpeta) / f"{video.stem}.{clave_estilo}.ass")
    srt = str(Path(carpeta) / f"{video.stem}.{clave_estilo}.srt")
    meta = REN.escribir_ass(cards, info, clave_estilo, ass, posicion="bajo")
    REN.escribir_srt(cards, srt)
    print(f"\n3) RENDER [{clave_estilo}]  {meta['estilo']}: {meta['fuente']} "
          f"{meta['tamano']}px, máx {meta['max_caracteres']} car")
    salida = Path(carpeta) / "_arnes"
    salida.mkdir(exist_ok=True)
    muestra = cards[:2] + cards[len(cards) // 2:len(cards) // 2 + 2] + cards[-2:]
    pngs, hashes, valores = [], [], []
    for c in muestra:
        t = (c.inicio + c.fin) / 2
        png = str(salida / f"{clave_estilo}_{c.i:04d}.png")
        REN.fotograma(str(video), t, png, ass=ass)
        ystd, h = tinta_y_hash(png)
        pngs.append((png, c, t)); hashes.append(h); valores.append(ystd)
    sin_tinta = [c.i for (p, c, t), v in zip(pngs, valores) if v < 8]
    if sin_tinta:
        no(f"[{clave_estilo}] fotogramas sin tinta en la banda ({sin_tinta}) "
           f"-> ¿la fuente no resuelve? YSTD={valores}")
    else:
        ok(f"[{clave_estilo}] hay texto pintado en los {len(pngs)} fotogramas "
           f"(YSTD {min(valores):.1f}-{max(valores):.1f})")
    # el texto no puede salir con las palabras pegadas (bug real del karaoke)
    pegadas = []
    for (p, c, t) in pngs:
        palabras_card = [w for w in c.texto.split() if len(w) > 3]
        if len(palabras_card) < 2:
            continue
        pegado = "".join(palabras_card)
        # en el ASS, si las palabras van sin separación, el texto sale así
        if pegado.lower() in "".join(Path(ass).read_text(encoding="utf-8").lower().split()):
            pegadas.append(c.i)
    if pegadas and clave_estilo == "karaoke":
        no(f"[{clave_estilo}] palabras sin separación en el ASS: {pegadas[:4]}")
    if len(set(hashes)) < len(hashes):
        no(f"[{clave_estilo}] fotogramas repetidos -> el -ss está mal: {hashes}")
    else:
        ok(f"[{clave_estilo}] los fotogramas son distintos entre sí")
    # tira para mirar a ojo
    tira = str(salida / f"tira_{clave_estilo}.png")
    n = len(pngs)
    esc = "scale=300:533"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error"]
    for p, _, _ in pngs:
        cmd += ["-i", p]
    cadenas = ";".join(f"[{i}]{esc}[a{i}]" for i in range(n))
    entradas = "".join(f"[a{i}]" for i in range(n))
    cmd += ["-filter_complex", f"{cadenas};{entradas}hstack={n}", "-frames:v", "1", tira]
    p = subprocess.run(cmd, capture_output=True, text=True, env=entorno())
    if not Path(tira).exists():
        no(f"[{clave_estilo}] no pude montar la tira: {(p.stderr or '')[-200:]}")
        return tira
    ok(f"[{clave_estilo}] tira de comprobación: {tira}")
    print("     tiempos y texto esperado:")
    for (p, c, t) in pngs:
        print(f"       {t:6.2f}s  «{c.texto}»  (clave: {c.clave or '—'})")
    return tira


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--json", required=True, help="transcripción JSON ya generada")
    ap.add_argument("--estilos", default="aurora7")
    ap.add_argument("--carpeta", default=str(RAIZ / "salidas"))
    a = ap.parse_args()
    video = Path(a.video)
    cards, info = TAR.cargar_json(a.json)
    print(f"\n═══ ARNÉS SUBTITULADOR BRUTAL ═══\nvídeo: {video}\n"
          f"json: {a.json} ({len(cards)} tarjetas)")
    comprobar_estructura(cards, info)
    estilos = list(EST.ESTILOS) if a.estilos in ("todos", "all") else a.estilos.split(",")
    tiras = []
    for e in estilos:
        if e not in EST.ESTILOS:
            no(f"estilo desconocido: {e}"); continue
        c_ass = str(Path(a.carpeta) / f"{video.stem}.{e}.ass")
        c_srt = str(Path(a.carpeta) / f"{video.stem}.{e}.srt")
        if Path(c_ass).exists():
            print(f"\n2) COBERTURA [{e}]")
            ass = Path(c_ass).read_text(encoding="utf-8")
            srt = Path(c_srt).read_text(encoding="utf-8") if Path(c_srt).exists() else ""
            faltan = [c.i for c in cards if normalizar(c.texto.split()[0]) not in normalizar(ass)]
            no_ass = "❌" if faltan else "✅"
            print(f"  {no_ass} {len(cards)-len(faltan)}/{len(cards)} tarjetas en el .ass")
            if faltan: FALLOS.append(f"[{e}] faltan en el ass: {faltan[:5]}")
        tiras.append(comprobar_render(cards, info, video, e, a.carpeta))
    print("\n═══ RESULTADO ═══")
    print(f"  fallos: {len(FALLOS)}   avisos: {len(AVISOS)}")
    for f in FALLOS: print("   ❌ " + f)
    for f in AVISOS: print("   ⚠️  " + f)
    print("\n  tiras generadas:")
    for t in tiras: print("   " + t)
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
