"""Fase 3 — qwen3.6 de NaN como corrector y maquetador de subtítulos.

Hace tres cosas, con red de seguridad:
  1. corrige erratas obvias de ASR usando el contexto de las tarjetas vecinas
  2. parte cada frase en "beats" de 2-4 palabras (lo que se ve en pantalla)
  3. marca la palabra clave de cada beat (la que se resalta)

Trampas verificadas de la API (2026-10-13):
  - qwen3.6 viene con *thinking* activado y se gasta el presupuesto en
    `reasoning_content`: hay que mandar enable_thinking=false o se corta
    antes de escribir el JSON (finish_reason=length).
  - Devuelve el JSON metido en ```json a veces: hay que limpiarlo.
  - NUNCA se confía en él: si al unir los beats se pierden palabras, se
    descarta su salida y se parte por reglas. Sin alucinaciones.
"""
from __future__ import annotations
import json, re, subprocess
from concurrent.futures import ThreadPoolExecutor
from .util import palabras

API = "https://api.nan.builders/v1/chat/completions"

SISTEMA = """Eres un subtitulador profesional de vídeo vertical para redes sociales.
Recibes frases transcritas automáticamente de un vídeo y devuelves SOLO un JSON.

Reglas:
1. Corrige SOLO erratas evidentes de transcripción (mayúsculas raras, palabras partidas, homófonos mal puestos). Usa el contexto de las frases vecinas. NO reescribas el estilo, NO traduzcas, NO añadas palabras que no estén.
2. Parte cada frase en bloques ("beats") de 2 a 4 palabras que se lean de un golpe, respetando el sentido. Máximo 24 caracteres por bloque.
3. Añade puntuación final si falta (, . ? !), sin inventar contenido.
4. Marca en "clave" la palabra MÁS importante del bloque (una sola, tal cual aparece en el texto; vacío si ninguna destaca).
5. Si una frase ya es corta (1-3 palabras), devuélvela como un único bloque.

Formato exacto de salida:
{"frases":[{"i":0,"bloques":[{"texto":"...","clave":"..."}]}]}"""


class Qwen:
    def __init__(self, clave: str, modelo: str = "qwen3.6", timeout: int = 240, lote: int = 40):
        self.clave, self.modelo, self.timeout, self.lote = clave, modelo, timeout, lote
        self.ultimo_error = ""
        self.ultimo_finish = ""
        self.notas_error: list[str] = []

    def _peticion(self, cuerpo: dict) -> dict:
        p = subprocess.run(
            ["curl", "-s", "-m", str(self.timeout), API,
             "-H", f"Authorization: Bearer {self.clave}",
             "-H", "Content-Type: application/json", "-H", "User-Agent: Mozilla/5.0",
             "-d", json.dumps(cuerpo, ensure_ascii=False)],
            capture_output=True, text=True)
        try:
            return json.loads(p.stdout)
        except Exception:
            return {"_error": (p.stdout or p.stderr or "")[:400]}

    def chat(self, usuario: str, max_tokens: int = 4000, sistema: str | None = None) -> str:
        cuerpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema or SISTEMA},
                         {"role": "user", "content": usuario}],
            "temperature": 0.15,
            "max_tokens": max_tokens,
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }
        r = self._peticion(cuerpo)
        if "_error" in r:
            self.ultimo_error = r["_error"]
            return ""
        try:
            msg = r["choices"][0]["message"]
            self.ultimo_finish = r["choices"][0].get("finish_reason")
            return msg.get("content") or ""
        except Exception as e:
            self.ultimo_error = f"respuesta inesperada: {str(r)[:200]} ({e})"
            return ""

    @staticmethod
    def sacar_json(txt: str):
        if not txt:
            return None
        txt = re.sub(r"^\s*```(?:json)?|```\s*$", "", txt.strip())
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    def maquetar(self, tarjetas, avisar=None):
        """tarjetas: lista de dicts {i, texto}. Devuelve {i: [ {texto, clave} ]}"""
        salida: dict[int, list] = {}
        lotes = [tarjetas[k:k + self.lote] for k in range(0, len(tarjetas), self.lote)]

        def trabajo(lote):
            cuerpo = "\n".join(f'{t["i"]}: {t["texto"]}' for t in lote)
            usuario = (f"Frases transcritas del vídeo (índice: texto). "
                       f"Devuelve el JSON con la misma cantidad de elementos, "
                       f"uno por índice:\n\n{cuerpo}")
            datos = self.sacar_json(self.chat(usuario, max_tokens=max(1600, 130 * len(lote))))
            res = {}
            if not datos:
                self.notas_error.append(f"lote de {len(lote)}: finish={self.ultimo_finish} "
                                        f"err={self.ultimo_error[:160] or 'JSON ilegible'}")
            if datos:
                for f in datos.get("frases", []):
                    try:
                        i = int(f["i"])
                    except Exception:
                        continue
                    bloques = []
                    for b in f.get("bloques", []):
                        if isinstance(b, str):
                            bloques.append({"texto": b, "clave": ""})
                        elif isinstance(b, dict) and b.get("texto"):
                            bloques.append({"texto": str(b["texto"]), "clave": str(b.get("clave") or "")})
                    if bloques:
                        res[i] = bloques
            return res

        with ThreadPoolExecutor(max_workers=3) as ex:
            for res in ex.map(trabajo, lotes):
                salida.update(res)
        if avisar:
            avisar(f"{self.modelo} maquetó {len(salida)}/{len(tarjetas)} frases")
            for n in self.notas_error[:3]:
                avisar(f"aviso {self.modelo}: " + n)
        return salida

    def _traducir_lote(self, lote, idioma: str, sistema: str) -> tuple[dict, bool]:
        """Devuelve ({i: t}, respuesta_llegó). El segundo valor distingue 'vino un JSON
        con los índices mal' (se puede reintentar partiendo el lote) de 'no vino nada'
        (la API falló: reintentar en trozos solo gastaría llamadas)."""
        cuerpo = "\n".join(f'{t["i"]}: {t["texto"]}' for t in lote)
        datos = self.sacar_json(self.chat(
            f"Traduce cada bloque al {idioma} (índice: texto):\n\n{cuerpo}",
            max_tokens=max(1200, 110 * len(lote)), sistema=sistema))
        if not datos:
            self.notas_error.append(f"traducción de {len(lote)}: finish={self.ultimo_finish} "
                                    f"err={self.ultimo_error[:160] or 'JSON ilegible'}")
            return {}, False
        res = {}
        for b in datos.get("bloques", []):
            try:
                i = int(b["i"])
            except Exception:
                continue
            t = str(b.get("t") or "").strip()
            if t:
                res[i] = t
        return res, True

    def traducir(self, tarjetas, idioma: str, avisar=None) -> dict[int, str]:
        """{i: traducción} para una segunda línea de subtítulo.

        El modelo NO es de fiar con los índices: medido, con 21 bloques devolvió 20 y a
        partir del décimo la traducción de cada uno era la del SIGUIENTE (el texto se
        pinta detrás del original, así que un desfase se ve y queda fatal). Por eso cada
        lote se valida: si los índices no cuadran exactamente, se parte en dos y se
        reintenta; si un bloque solo tampoco cuadra, se queda SIN traducción (nunca se
        inventa ni se acepta una que no se sabe de quién es).
        """
        salida: dict[int, str] = {}
        lotes = [tarjetas[k:k + self.lote] for k in range(0, len(tarjetas), self.lote)]
        sistema = SISTEMA_TRAD.replace("{idioma}", idioma)   # .format() rompería con las llaves del JSON

        def trabajo(lote):
            res, vino = self._traducir_lote(lote, idioma, sistema)
            if set(res) == {t["i"] for t in lote}:
                return res
            if not vino or len(lote) == 1:
                self.notas_error.append(
                    f"bloque {lote[0]['i'] if len(lote) == 1 else 'lote de %d' % len(lote)}: "
                    f"traducción descuadrada, se queda sin ella")
                return {}
            mitad = len(lote) // 2
            self.notas_error.append(f"lote de {len(lote)}: índices descuadrados, lo parto en dos")
            return {**trabajo(lote[:mitad]), **trabajo(lote[mitad:])}

        with ThreadPoolExecutor(max_workers=3) as ex:
            for res in ex.map(trabajo, lotes):
                salida.update(res)
        if avisar:
            avisar(f"{self.modelo} tradujo {len(salida)}/{len(tarjetas)} bloques a {idioma}")
            for n in self.notas_error[:3]:
                avisar(f"aviso traducción: " + n)
        return salida


SISTEMA_TRAD = """Eres un traductor profesional de subtítulos para vídeo.
Recibes bloques de subtítulo numerados (índice: texto) y devuelves SOLO un JSON:

{"bloques":[{"i":0,"t":"..."}]}

Reglas:
1. Traduce al {idioma}. Natural y coloquial, como se subtitula de verdad: nada de traducción literal.
2. MISMA cantidad de elementos y los MISMOS índices que el original. No juntes ni separes bloques.
3. Respeta la puntuación final y NO añadas ni quites información.
4. Si el bloque es un nombre propio, una marca o una interjección, déjalo tal cual.
5. Nada más que el JSON."""


def partir_por_reglas(texto: str, max_palabras: int = 4, max_car: int = 24) -> list[dict]:
    """Plan B sin LLM: respeta la puntuación y no se inventa nada."""
    trozos = re.split(r"(?<=[.,;:!?…])\s+", texto.strip())
    salida, buf = [], []
    for t in trozos:
        for p in (t.split() or []):
            buf.append(p)
            termina = p.endswith((".", ",", ";", ":", "!", "?", "…"))
            if len(buf) >= max_palabras or sum(len(x) + 1 for x in buf) > max_car or (termina and len(buf) >= 2):
                salida.append({"texto": " ".join(buf), "clave": ""})
                buf = []
    if buf:
        salida.append({"texto": " ".join(buf), "clave": ""})
    return salida or [{"texto": texto.strip(), "clave": ""}]


def cobertura(original: str, bloques) -> float:
    """Qué fracción de las palabras originales sobrevive en los bloques."""
    o = palabras(original)
    if not o:
        return 1.0
    d = palabras(" ".join(b["texto"] for b in bloques) if bloques and isinstance(bloques[0], dict)
                 else " ".join(bloques))
    from collections import Counter
    c_o, c_a = Counter(o), Counter(d)
    comunes = sum(min(c_o[w], c_a[w]) for w in c_o)
    return comunes / len(o)
