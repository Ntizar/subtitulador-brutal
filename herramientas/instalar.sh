#!/usr/bin/env bash
# Instala las dependencias del Subtitulador Brutal SIN root:
#   - ffmpeg estático (libass + libx264 + fontconfig)
#   - fuentes de los estilos + fontconfig propio (esta máquina no tiene /etc/fonts)
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$RAIZ/bin"; FONTES="$RAIZ/fuentes"
mkdir -p "$BIN" "$FONTES"

echo "== ffmpeg estático =="
if [ ! -x "$BIN/ffmpeg" ]; then
  T=$(mktemp -d)
  curl -sL --max-time 900 -o "$T/ff.tar.xz" https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar xJf "$T/ff.tar.xz" -C "$T"
  cp "$T"/ffmpeg-*-static/ffmpeg "$T"/ffmpeg-*-static/ffprobe "$BIN/"
  rm -rf "$T"
fi
"$BIN/ffmpeg" -hide_banner -version | head -1
"$BIN/ffmpeg" -hide_banner -filters 2>/dev/null | grep -qE "ass +V->V" && echo "  libass OK"

echo "== fuentes (Google Fonts vía raw.githubusercontent) =="
BASE="https://raw.githubusercontent.com/google/fonts/main"
descargar() { # url|fichero
  local url="$1" out="$2" code size
  [ -s "$FONTES/$out" ] && return 0
  code=$(curl -sL -o "$FONTES/$out" -w "%{http_code}" --max-time 120 "$BASE/$url" || echo 000)
  size=$(stat -c%s "$FONTES/$out" 2>/dev/null || echo 0)
  if [ "$code" != "200" ] || [ "$size" -lt 20000 ]; then rm -f "$FONTES/$out"; echo "  FALLA $out ($code)"; fi
}
while IFS='|' read -r url out; do [ -n "${url:-}" ] && descargar "$url" "$out"; done <<'EOF'
ofl/archivoblack/ArchivoBlack-Regular.ttf|ArchivoBlack.ttf
ofl/anton/Anton-Regular.ttf|Anton.ttf
ofl/bebasneue/BebasNeue-Regular.ttf|BebasNeue.ttf
ofl/inter/Inter%5Bopsz,wght%5D.ttf|Inter.ttf
ofl/montserrat/Montserrat%5Bwght%5D.ttf|Montserrat.ttf
ofl/outfit/Outfit%5Bwght%5D.ttf|Outfit.ttf
ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf|SpaceGrotesk.ttf
ofl/archivo/Archivo%5Bwdth,wght%5D.ttf|Archivo.ttf
ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf|NotoSans.ttf
EOF
for f in "$FONTES"/*.ttf; do printf "  %-26s %8s\n" "$(basename "$f")" "$(stat -c%s "$f")"; done

echo "== fontconfig propio =="
cat > "$FONTES/fonts.conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>$FONTES</dir>
  <cachedir>$RAIZ/.cachefont</cachedir>
  <alias><family>sans-serif</family><prefer><family>Noto Sans</family><family>Inter</family></prefer></alias>
  <alias><family>sans</family><prefer><family>Noto Sans</family><family>Inter</family></prefer></alias>
</fontconfig>
EOF
rm -rf "$RAIZ/.cachefont"

echo "== prueba real: libass tiene que resolver las familias =="
export FONTCONFIG_FILE="$FONTES/fonts.conf"
"$BIN/ffmpeg" -hide_banner -loglevel info -f lavfi -i color=c=0x101018:s=900x520:d=1 \
  -vf "ass='$FONTES/_prueba.ass'" -frames:v 1 -y "$FONTES/_prueba.png" 2>&1 \
  | grep -E "fontselect|Glyph|not found" | head -8
echo "-- fin: si arriba no pone 'failed to find', libass resuelve bien --"
