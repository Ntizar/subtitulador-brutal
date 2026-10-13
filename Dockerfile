# Subtitulador Brutal — imagen para NaN Cloud (apps.nan.builders)
#
# El ffmpeg de Debian ya viene con libass y fontconfig, así que aquí NO hace falta
# el binario estático de herramientas/instalar.sh: esa vía es para máquinas sin root.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Madrid

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/motor
COPY . /app/motor

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart

# Las 9 fuentes de los estilos, al sistema: libass las encuentra por fontconfig y
# no hay que mantener un fonts.conf con rutas dentro de la imagen.
RUN mkdir -p /usr/local/share/fonts/subtitulador \
 && cp /app/motor/fuentes/*.ttf /usr/local/share/fonts/subtitulador/ \
 && fc-cache -f \
 && fc-list | grep -ci "Anton\|Archivo Black\|Bebas" | xargs -I{} test {} -ge 3

# NaN rechaza los pods que corren como root (la app se queda en 'pending' sin error
# visible), así que el proceso va con un usuario sin privilegios.
RUN groupadd -r appgroup && useradd -r -g appgroup -M -d /app/motor appuser \
 && mkdir -p /app/motor/trabajos /app/motor/salidas \
 && chown -R appuser:appgroup /app/motor
USER appuser

# Límites del plan de la app (se pueden cambiar desde el panel sin tocar el código).
ENV PORT=8765 \
    SB_TAM_MAX_MB=400 \
    SB_HORAS_VIDA=6

EXPOSE 8765
CMD ["sh", "-c", "python3 -m uvicorn servidor:app --host 0.0.0.0 --port ${PORT}"]
