"""Fase 5 — motor de estilos: 8 diseños animados en ASS (los renderiza libass).

Todo se genera a mano en ASS v4+ para poder animar palabra a palabra sin
depender de nada más que de ffmpeg. Trucos del formato que están usados aquí:

  * &HAABBGGRR  -> el color va en BGR y el alfa invertido (00 = opaco).
  * PlayResX/Y = dimensiones reales del vídeo -> el tamaño de fuente se
    define como fracción de la altura y todo escala solo.
  * Efecto "pop" (CapCut/TikTok): un evento por palabra cubriendo la línea
    entera, con la palabra activa resaltada y un \\t() que la devuelve a su
    tamaño. Es lo que usan todas las herramientas del sector.
  * \\kf = barrido karaoke continuo; requiere SecondaryColour (antes) y
    PrimaryColour (después).
  * BorderStyle=3 = caja opaca detrás de la línea (BackColour = color de caja).
  * Rectangle vectorial con \\p1 para la banda del estilo Aurora 7.
"""
from __future__ import annotations
from .util import ass_tiempo

# ---------------------------------------------------------------- colores

def c(hexrgb: str, alfa: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (alfa 0 = opaco, 255 = invisible)."""
    h = hexrgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alfa:02X}{b}{g}{r}".upper()


def escapar(t: str) -> str:
    return (t.replace("\\", "／").replace("{", "(").replace("}", ")")
             .replace("\n", " ").strip())


# ---------------------------------------------------------------- estilos

ESTILOS = {
    "aurora7": dict(
        nombre="Aurora 7", fuente="Inter", escala=0.058, mayusculas=False,
        color="#FFFFFF", clave="#22D3EE", contorno=4, sombra=2, color_contorno="#05070D",
        anim="pop", pop=1.14, espaciado=1.2, banda=dict(alto=0.055, color="#0B1220", alfa=118,
        filete="#22D3EE", filete_alto=0.006),
        descripcion="Marca Ntizar: cian sobre banda oscura con filete de acento."),
    "brutal": dict(
        nombre="Brutal (Hormozi)", fuente="Archivo Black", escala=0.062, mayusculas=True,
        color="#FFFFFF", clave="#FFE000", contorno=6, sombra=0, color_contorno="#000000",
        anim="pop", pop=1.22, espaciado=0.8,
        descripcion="Mayúsculas gordas, palabra activa en amarillo con golpe de escala."),
    "bestia": dict(
        nombre="Bestia (MrBeast)", fuente="Anton", escala=0.066, mayusculas=True,
        color="#FFFFFF", clave="#00E5FF", contorno=7, sombra=3, color_contorno="#000000",
        color_sombra="#00B8D4", sombra_alfa=100, anim="pop", pop=1.18, espaciado=0.5,
        descripcion="Anton con contorno brutal y halo cian; activo en cian eléctrico."),
    "karaoke": dict(
        nombre="Karaoke", fuente="Montserrat", escala=0.056, mayusculas=False,
        color="#FFFFFF", clave="#FF4D6D", contorno=4, sombra=2, color_contorno="#12040B",
        anim="karaoke", espaciado=0.6,
        descripcion="Barrido continuo de color palabra a palabra, tipo letra de canción."),
    "neon": dict(
        nombre="Neón", fuente="Bebas Neue", escala=0.072, mayusculas=True,
        color="#F5D0FE", clave="#22D3EE", contorno=3, sombra=0, color_contorno="#7C3AED",
        color_sombra="#A855F7", sombra_alfa=90, anim="pop", pop=1.12, espaciado=2.0,
        entrada_fade=90,
        descripcion="Tubo de neón: violeta con brillo y activo en cian."),
    "editorial": dict(
        nombre="Editorial", fuente="Inter", escala=0.046, mayusculas=False,
        color="#F8FAFC", clave="#FBBF24", contorno=0, sombra=0, caja=True,
        caja_color="#000000", caja_alfa=150, anim="fade", fade=140, espaciado=0.4,
        descripcion="Sobrio y legible: caja negra translúcida, sin golpes. Para vídeo serio."),
    "maquina": dict(
        nombre="Máquina de escribir", fuente="Space Grotesk", escala=0.050, mayusculas=False,
        color="#E5E7EB", clave="#34D399", contorno=3, sombra=1, color_contorno="#0A0F0D",
        anim="maquina", espaciado=1.0,
        descripcion="Aparece palabra a palabra con cursor parpadeante."),
    "vhs": dict(
        nombre="VHS", fuente="Archivo", escala=0.058, mayusculas=True,
        color="#FDE047", clave="#FF2D55", contorno=5, sombra=2, color_contorno="#1B0030",
        color_sombra="#22D3EE", sombra_alfa=120, anim="glitch", espaciado=1.6,
        descripcion="Cinta vieja: temblor, separación de color y activo en rojo."),
    "carta": dict(
        nombre="Carta", fuente="Archivo Black", escala=0.062, mayusculas=True,
        color="#C9D4E4", clave="#FFFFFF", color_activo="#F2F6FF", contorno=7, sombra=0,
        color_contorno="#161A22",
        color_sombra="#5C6578", sombra_alfa=0, anim="carta", pop=1.16, espaciado=1.4,
        bisel=4,
        descripcion="Plateado de carta coleccionable: bisel claro arriba, sombra abajo, "
                    "contorno iridiscente y fogonazo blanco en la palabra activa."),
}

POSICIONES = {"bajo": 2, "medio": 5, "alto": 8}

# Valores por defecto: un estilo declara solo lo que le diferencia. Sin esto,
# olvidar una clave revienta el generador con un KeyError (pasó con `editorial`
# y su color_contorno).
DEFECTOS = dict(
    color="#FFFFFF", clave="#FFFFFF", color_contorno="#000000", contorno=4, sombra=2,
    espaciado=0.0, pop=1.15, anim="pop", mayusculas=False, escala=0.058, caja=False,
    caja_color="#000000", caja_alfa=150, color_sombra="#000000", sombra_alfa=0,
    entrada_fade=0, fade=0, banda=None, nombre="?", fuente="Inter", descripcion="",
)


def estilo(clave: str) -> dict:
    """Estilo completo: los defectos + lo que declara el estilo."""
    if clave not in ESTILOS:
        raise KeyError(f"estilo desconocido: {clave}")
    return {**DEFECTOS, **ESTILOS[clave]}


def _cabecera(info, est, fs, max_car, posicion, margen):
    alineacion = POSICIONES[posicion]
    borde_estilo = 3 if est.get("caja") else 1
    back = c(est["caja_color"], est.get("caja_alfa", 128)) if est.get("caja") else \
        c(est.get("color_sombra", "#000000"), est.get("sombra_alfa", 0))
    karaoke = est.get("anim") == "karaoke"
    # karaoke: PrimaryColour es el color tras el barrido y SecondaryColour el de antes
    prim = c(est["clave"]) if karaoke else c(est["color"])
    sec = c(est["color"]) if karaoke else c(est["clave"])
    sty = (f"Style: Principal,{est['fuente']},{fs},{prim},{sec},"
           f"{c(est['color_contorno'])},{back},"
           f"0,0,0,0,100,100,{est.get('espaciado',0)},0,{borde_estilo},"
           f"{est.get('contorno',4)},{est.get('sombra',2)},{alineacion},"
           f"{margen},{margen},{margen},1")
    return f"""[Script Info]
; Generado por Subtitulador Brutal
ScriptType: v4.00+
PlayResX: {info['ancho']}
PlayResY: {info['alto']}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{sty}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _evento(a, b, texto, capa=0, estilo="Principal"):
    return f"Dialogue: {capa},{ass_tiempo(a)},{ass_tiempo(b)},{estilo},,0,0,0,,{texto}"


def calcular_tamano(info, est, max_car_objetivo=22):
    """Fuente como fracción de la altura, topada por el ancho útil del vídeo."""
    fs = max(16, int(round(info["alto"] * est["escala"])))
    # ancho aproximado por carácter: 0.52 em en sans (0.62 en mayúsculas gordas)
    factor = 0.62 if est.get("mayusculas") else 0.53
    util = info["ancho"] * 0.88
    if fs * factor * max_car_objetivo > util:
        fs = max(16, int(util / (factor * max_car_objetivo)))
    return fs


def max_caracteres(info, est, fs):
    factor = 0.62 if est.get("mayusculas") else 0.53
    return max(8, int((info["ancho"] * 0.90) / (fs * factor)))


def _texto_linea(palabras, activo, est, karaoke=False, clave="", glint=""):
    """Construye la línea con la palabra `activo` resaltada.

    OJO: en ASS un bloque {\\c...} afecta a TODO lo que va detrás en la línea,
    así que hay que reponer el color normal en cada palabra no activa.

    Si la palabra activa es además la CLAVE de la tarjeta, el golpe es más
    grande (el diseño tiene intención: lo importante se nota).

    `glint` = etiquetas extra para la palabra activa (el destello del estilo
    Carta: entra en blanco y se asienta en plata con un \\t).
    """
    norm = c(est["color"])
    partes = []
    kclave = (clave or "").strip().lower().strip(".,;:!?¡¿")
    for k, p in enumerate(palabras):
        w = escapar(p["w"] if isinstance(p, dict) else p.w)
        if est.get("mayusculas"):
            w = w.upper()
        if k == activo and not karaoke:
            es_clave = kclave and w.lower().strip(".,;:!?¡¿") == kclave
            pop = est.get("pop", 1.15) * (1.06 if es_clave else 1.0)
            w = (f"{{\\c{c(est['clave'])}{glint}\\fscx{pop*100:.0f}\\fscy{pop*100:.0f}"
                 f"\\t(0,110,\\fscx100\\fscy100)}}{w}"
                 f"{{\\c{norm}\\fscx100\\fscy100}}")
        else:
            w = f"{{\\c{norm}}}{w}"
        partes.append(w)
    return " ".join(partes)


def _banda_aurora(info, est, card, fs=None, margen=None):
    """Rectángulo vectorial detrás del texto, centrado en la línea (estilo Aurora 7)."""
    cfg = est["banda"]
    fs = fs or int(info["alto"] * est["escala"])
    margen = margen or int(info["alto"] * 0.11)
    alto = max(2, int(info["alto"] * cfg["alto"]))
    # el texto (alineación 2) vive entre alto-margen y alto-margen-fs*1.32
    texto_abajo = info["alto"] - margen
    texto_arriba = texto_abajo - int(fs * 1.32)
    centro = (texto_abajo + texto_arriba) / 2
    y = int(centro - alto / 2)
    x = int(info["ancho"] * 0.05)
    ancho = info["ancho"] - 2 * x
    filo = max(2, int(info["alto"] * cfg.get("filete_alto", 0.006)))
    dib = (f"{{\\an7\\pos({x},{y})\\p1\\bord0\\shad0"
           f"\\1c{c(cfg['color'])}\\1a&H{cfg['alfa']:02X}&}}"
           f"m 0 0 l {ancho} 0 {ancho} {alto} 0 {alto}{{\\p0}}")
    dib2 = (f"{{\\an7\\pos({x},{y - filo})\\p1\\bord0\\shad0"
            f"\\1c{c(cfg['filete'])}\\1a&H00&}}"
            f"m 0 0 l {ancho} 0 {ancho} {filo} 0 {filo}{{\\p0}}")
    return (_evento(card.inicio, card.fin, dib, capa=0),
            _evento(card.inicio, card.fin, dib2, capa=0))


def _palabras(card):
    if card.palabras:
        return [p if isinstance(p, dict) else {"w": p.w, "a": p.a, "b": p.b} for p in card.palabras]
    # sin palabras (no debería pasar): reparto uniforme
    ws = card.texto.split()
    n = max(1, len(ws))
    paso = (card.fin - card.inicio) / n
    return [{"w": w, "a": round(card.inicio + i * paso, 3), "b": round(card.inicio + (i + 1) * paso, 3)}
            for i, w in enumerate(ws)]


def eventos_de(card, info, est, fs, max_car, margen=None):
    ws = _palabras(card)
    if not ws:
        return []
    anim = est.get("anim", "pop")
    ev = []
    fade = est.get("entrada_fade") or est.get("fade") or 0
    if est.get("banda"):
        ev.extend(_banda_aurora(info, est, card, fs=fs, margen=margen))
    if est.get("mayusculas"):
        for p in ws:
            p["w"] = p["w"].upper()

    if anim == "karaoke":
        # OJO: el espacio va FUERA de las llaves. Si se concatena
        # "{\kf50}Hola{\kf40}mundo" libass pinta "Holamundo" (bug real detectado
        # mirando un fotograma: 6 palabras pegadas, ilegible).
        trozos = []
        n = len(ws)
        for k, p in enumerate(ws):
            cs = max(1, int(round((p["b"] - p["a"]) * 100)))
            trozos.append(f"{{\\kf{cs}}}{escapar(p['w'])}")
            if k < n - 1:
                trozos.append(" ")
        ev.append(_evento(card.inicio, card.fin, "".join(trozos)))
        return ev

    if anim == "maquina":
        for k, p in enumerate(ws):
            inicio = p["a"]
            fin = ws[k + 1]["a"] if k + 1 < len(ws) else card.fin
            visible = " ".join(escapar(x["w"]) for x in ws[:k + 1])
            cursor = "|" if (k % 2 == 0) else " "
            texto = f"{visible}{{\\alpha&H80&}} {cursor}{{\\alpha&H00&}}"
            if k == 0 and fade:
                texto = f"{{\\fad({int(fade/10)},{int(fade/10)})}}" + texto
            ev.append(_evento(inicio, fin, texto))
        return ev

    if anim == "fade":
        f = est.get("fade", 140)
        ev.append(_evento(card.inicio, card.fin,
                          f"{{\\fad({int(f/10)},{int(f/10)})}}"
                          + _texto_linea(ws, -1, est, clave=card.clave)))
        return ev

    if anim == "carta":
        # Plateado de carta coleccionable. El ASS no tiene degradados, así que el metal
        # se finge dibujando la MISMA línea tres veces: copia clara desplazada arriba
        # (bisel), copia gris desplazada abajo (canto) y el plata encima. Los despla-
        # zamientos van en \xshad/\yshad, NO en el Shadow del estilo: así cada copia
        # conserva su contorno oscuro y el filo queda limpio.
        bisel = est.get("bisel", 3)
        arriba = {**est, "color": "#FFFFFF", "clave": "#FFFFFF"}
        abajo = {**est, "color": "#6E7789", "clave": "#6E7789"}
        for k, p in enumerate(ws):
            inicio = p["a"]
            fin = ws[k + 1]["a"] if k + 1 < len(ws) else card.fin
            # el destello: entra en blanco puro y se asienta en un plata más claro
            # (`color_activo`), no en el plata base: si no, a los 190 ms la palabra
            # activa se confunde con las demás y el resalte no se ve.
            destello = est.get("color_activo") or est["clave"]
            glint = f"\\t(0,190,\\1c{c(destello)})"
            texto = _texto_linea(ws, k, est, clave=card.clave, glint=glint)
            # irisación: el contorno alterna carbón / violeta apagado palabra a palabra
            iri = c("#3A3350" if k % 2 else est["color_contorno"])
            texto = (f"{{\\3c{iri}\\frz{1.2 if k % 2 else -1.2}"
                     f"\\t(0,110,\\frz0)}}{texto}")
            ev.append(_evento(inicio, fin, f"{{\\xshad0\\yshad-{bisel}}}" + _texto_linea(ws, -1, arriba), capa=1))
            ev.append(_evento(inicio, fin, f"{{\\xshad0\\yshad{bisel}}}" + _texto_linea(ws, -1, abajo), capa=0))
            ev.append(_evento(inicio, fin, texto, capa=2))
        return ev

    # pop / glitch -> un evento por palabra (la palabra activa se resalta)
    for k, p in enumerate(ws):
        inicio = p["a"]
        fin = ws[k + 1]["a"] if k + 1 < len(ws) else card.fin
        texto = _texto_linea(ws, k, est, clave=card.clave)
        if anim == "glitch":
            jx = 3 if k % 2 == 0 else -3
            texto = (f"{{\\frz{'2' if k % 2 else '-2'}\\t(0,90,\\frz0)"
                     f"\\xshad{jx}\\4c{c(est.get('color_sombra', '#22D3EE'))}}}{texto}")
        if k == 0 and fade:
            texto = f"{{\\fad({int(fade/10)},0)}}" + texto
        if k == len(ws) - 1 and fade:
            texto += f"{{\\fad(0,{int(fade/10)})}}"
        ev.append(_evento(inicio, fin, texto))
    return ev


def generar_ass(cards, info, clave_estilo: str = "aurora7", posicion: str = "bajo",
                escala: float | None = None, mayusculas: bool | None = None,
                max_car_objetivo: int = 22, margen_pct: float = 0.11):
    est = estilo(clave_estilo)
    if escala:
        est["escala"] = escala
    if mayusculas is not None:
        est["mayusculas"] = mayusculas
    fs = calcular_tamano(info, est, max_car_objetivo)
    max_car = max_caracteres(info, est, fs)
    margen = int(info["alto"] * margen_pct)
    if posicion == "alto":
        margen = int(info["alto"] * 0.12)
    cab = _cabecera(info, est, fs, max_car, posicion, margen)
    lineas = []
    for card in cards:
        lineas.extend(eventos_de(card, info, est, fs, max_car, margen=margen))
    return cab + "\n".join(lineas) + "\n", {"fuente": est["fuente"], "tamano": fs,
                                            "max_caracteres": max_car,
                                            "estilo": est["nombre"]}


def listar():
    return [(k, v["nombre"], v["descripcion"]) for k, v in ESTILOS.items()]
