#!/usr/bin/env bash
# Genera la voz de prueba con kokoro (API de NaN). Frases con pausas reales
# para que el VAD tenga silencios que detectar.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SALIDA="${1:-$RAIZ/pruebas/voz.mp3}"
K=$(tr '\0' '\n' < /proc/$(pgrep -f hermes | head -1)/environ 2>/dev/null | grep '^OPENAI_API_KEY=' | cut -d= -f2-)
API="https://api.nan.builders/v1/audio/speech"

FRASES=(
"Bienvenidos al canal. Hoy vamos a hablar de tres cosas que cambian por completo la forma en que trabajas con video."
"Primero, la transcripcion automatica. Segundo, el diseno de subtitulos animados. Y tercero, el render final con ffmpeg sin tocar una sola linea a mano."
"Lo importante aqui es que cada frase aparezca en el momento exacto. Si el subtitulo se adelanta dos decimas, el espectador lo nota. Y si se retrasa, tambien."
"Por eso vamos a anclar cada bloque de texto al silencio real del audio, no a una estimacion hecha a ojo."
"Y con esto terminamos la prueba. Si todo cuadra, tendremos una herramienta capaz de subtitular un video de diez minutos en un par de minutos de proceso. Con ocho estilos distintos."
"El que mas te guste lo quemamos dentro del video para siempre. Y listo. Asi de simple."
)

TMP=$(mktemp -d)
i=0
for f in "${FRASES[@]}"; do
  i=$((i+1))
  curl -s -m 120 "$API" -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
    -H "User-Agent: Mozilla/5.0" \
    -d "$(printf '{"model":"kokoro","input":"%s","voice":"alloy","response_format":"mp3"}' "$f")" \
    -o "$TMP/f$i.mp3"
  sleep 0.4
done
# 0,9 s de silencio entre frases para que el VAD tenga trabajo
"$RAIZ/bin/ffmpeg" -y -hide_banner -loglevel error -f lavfi -i anullsrc=r=24000:cl=mono -t 0.9 "$TMP/s.mp3"
: > "$TMP/lista.txt"
for n in $(seq 1 $i); do echo "file '$TMP/f$n.mp3'" >> "$TMP/lista.txt"; echo "file '$TMP/s.mp3'" >> "$TMP/lista.txt"; done
"$RAIZ/bin/ffmpeg" -y -hide_banner -loglevel error -f concat -safe 0 -i "$TMP/lista.txt" -c copy "$SALIDA"
rm -rf "$TMP"
echo "voz de prueba -> $SALIDA"
