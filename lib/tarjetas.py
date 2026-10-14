"""Fase 4 — tarjetas finales: bloques con tiempos absolutos y por palabra.

Los timestamps por palabra NO existen en la API (whisper devuelve words=null).
Se derivan repartiendo la duración real de cada frase entre sus bloques y, dentro
de cada bloque, entre sus palabras, ponderando por longitud. El borde de cada
bloque está anclado al silencio real del audio, así que el resultado cuadra con
la voz aunque el reparto interno sea proporcional.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict

from .llm import cobertura, partir_por_reglas


@dataclass
class Palabra:
    w: str
    a: float
    b: float


@dataclass
class Tarjeta:
    i: int
    inicio: float
    fin: float
    texto: str
    clave: str = ""
    fuente: str = "llm"          # llm | reglas
    cobertura: float = 1.0
    palabras: list = field(default_factory=list)
    texto_2: str = ""            # segunda línea (traducción), opcional

    def dict(self) -> dict:
        d = asdict(self)
        d["palabras"] = [asdict(p) if not isinstance(p, dict) else p for p in self.palabras]
        return d


def _peso(t: str) -> float:
    return max(len(t.strip()), 5)


def tiempos_de_bloque(inicio: float, fin: float, bloques: list[dict],
                      hueco: float = 0.035, min_dur: float = 0.32):
    """Reparte [inicio, fin] entre los bloques por longitud y calcula palabra a palabra."""
    dur = max(0.05, fin - inicio)
    disp = max(0.1, dur - hueco * max(0, len(bloques) - 1))
    pesos = [_peso(b["texto"]) for b in bloques]
    total = sum(pesos) or 1.0
    salida, t = [], inicio
    for idx, (b, p) in enumerate(zip(bloques, pesos)):
        d = disp * p / total
        a, z = t, t + d
        # palabras del bloque
        ws = b["texto"].split()
        if ws:
            pws = [len(w) + 1 for w in ws]
            tot = sum(pws) or 1
            t2 = a
            for w, pw in zip(ws, pws):
                dw = d * pw / tot
                b["_palabras"] = b.get("_palabras", [])
                b["_palabras"].append({"w": w, "a": round(t2, 3), "b": round(t2 + dw, 3)})
                t2 += dw
        salida.append((round(a, 3), round(z, 3)))
        t = z + hueco
    return salida


def _fusionar_cortos(bloques: list[dict], duraciones, min_dur: float):
    """Los bloques que quedarían ilegibles se pegan al vecino más largo."""
    i = 0
    while i < len(bloques):
        d = duraciones[i][1] - duraciones[i][0]
        if d < min_dur and len(bloques) > 1:
            j = i - 1 if i > 0 else i + 1
            if j < i:
                bloques[j]["texto"] = (bloques[j]["texto"] + " " + bloques[i]["texto"]).strip()
                if not bloques[j].get("clave"):
                    bloques[j]["clave"] = bloques[i].get("clave", "")
            else:
                bloques[j]["texto"] = (bloques[i]["texto"] + " " + bloques[j]["texto"]).strip()
            bloques.pop(i)
            duraciones.pop(i)
            continue
        i += 1
    return bloques


def construir(trozo, bloques_llm: list[dict] | None, min_dur: float = 0.32) -> Tarjeta:
    """trozo: objeto de lib.stt (i, inicio, fin, texto)."""
    texto = (trozo.texto or "").strip()
    fuente, cob = "llm", 1.0
    bloques = bloques_llm
    if bloques:
        cob = cobertura(texto, bloques)
        if cob < 0.80:                       # el LLM perdió texto -> plan B
            bloques, fuente, cob = None, "reglas", 1.0
    if not bloques:
        bloques = partir_por_reglas(texto)
    bloques = [b for b in bloques if str(b.get("texto", "")).strip()]
    if not bloques:
        bloques = [{"texto": texto, "clave": ""}]
    duraciones = tiempos_de_bloque(trozo.inicio, trozo.fin, bloques)
    if len(bloques) > 1:
        n0 = len(bloques)
        bloques = _fusionar_cortos(bloques, duraciones, min_dur)
        if len(bloques) != n0:               # recalcular tras fusionar
            duraciones = tiempos_de_bloque(trozo.inicio, trozo.fin, bloques)
    # las palabras ya calculadas se pierden al fusionar -> recalcular siempre al final
    for b in bloques:
        b.pop("_palabras", None)
    duraciones = tiempos_de_bloque(trozo.inicio, trozo.fin, bloques)
    salida = []
    for k, (b, (a, z)) in enumerate(zip(bloques, duraciones)):
        salida.append(Tarjeta(i=trozo.i, inicio=a, fin=z, texto=" ".join(b["texto"].split()),
                              clave=(b.get("clave") or "").strip(), fuente=fuente,
                              cobertura=round(cob, 3),
                              palabras=[Palabra(**p) for p in b.get("_palabras", [])]))
    return salida


def construir_todas(trozos, maquetado: dict, min_dur: float = 0.32):
    salida = []
    for t in trozos:
        if not (t.texto or "").strip():
            continue
        salida.extend(construir(t, maquetado.get(t.i)))
    # reindexar y sanear
    for n, c in enumerate(salida):
        c.i = n
        c.inicio = round(max(0.0, c.inicio), 3)
        c.fin = round(max(c.inicio + 0.12, c.fin), 3)
    return salida


def cargar_json(ruta: str):
    """Reconstruye las tarjetas desde un JSON ya generado: permite probar los 8
    estilos sin volver a llamar a whisper ni a qwen3.6."""
    import json
    from pathlib import Path
    d = json.loads(Path(ruta).read_text(encoding="utf-8"))
    cards = []
    for t in d.get("tarjetas", []):
        c = Tarjeta(i=t["i"], inicio=t["inicio"], fin=t["fin"], texto=t["texto"],
                    clave=t.get("clave", ""), fuente=t.get("fuente", "json"),
                    cobertura=t.get("cobertura", 1.0), texto_2=t.get("texto_2", ""))
        c.palabras = [Palabra(w=p["w"], a=p["a"], b=p["b"]) for p in t.get("palabras", [])]
        cards.append(c)
    return cards, d.get("info", {})
