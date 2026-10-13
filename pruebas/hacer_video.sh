#!/usr/bin/env bash
# Crea un vídeo de prueba vertical 1080x1920 con la voz de kokoro (API de NaN)
# para probar el pipeline sin depender de un vídeo de influencer real.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FF="$RAIZ/bin/ffmpeg"
SAL="$RAIZ/pruebas"

bash "$RAIZ/pruebas/voz_prueba.sh" "$SAL/voz.mp3"

DUR=$("$FF" -hide_banner -i "$SAL/voz.mp3" 2>&1 | grep -oP 'Duration: \K[\d:.]+' || echo 00:00:50)
echo "voz: $DUR"

"$FF" -y -hide_banner -loglevel error \
  -f lavfi -i "gradients=s=1080x1920:d=120:speed=0.03:c0=0x0B1020:c1=0x1E1B4B:c2=0x082F49:n=3" \
  -i "$SAL/voz.mp3" \
  -filter_complex "[0:v]drawbox=x='(w-360)/2+sin(t/2)*260':y=700:w=360:h=520:color=0x22D3EE@0.20:t=fill,\
drawbox=x='(w-200)/2':y=1400:w=200:h=20:color=0xFF7A1A@0.5:t=fill,\
drawbox=x='(w-600)/2':y=250:w=600:h=8:color=0xFFFFFF@0.35:t=fill[v]" \
  -map "[v]" -map 1:a -c:v libx264 -preset ultrafast -crf 26 -pix_fmt yuv420p \
  -c:a aac -shortest "$SAL/video_prueba.mp4"
ls -la "$SAL/video_prueba.mp4"
"$RAIZ/bin/ffprobe" -v error -show_entries format=duration,size -of csv=p=0 "$SAL/video_prueba.mp4"
