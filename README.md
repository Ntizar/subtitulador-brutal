# Subtitulador Brutal

Herramienta de línea de órdenes que **subtitula cualquier vídeo, del largo que sea**, con
subtítulos animados palabra a palabra quemados dentro del fotograma. Usa la API de NaN
(`whisper` para transcribir, `qwen3.6` para corregir y maquetar) y **libass** vía ffmpeg
para el render final. Trae **8 estilos** y un previsualizador web para elegir sin gastar
proceso.

No es un envoltorio de otra herramienta: el motor es propio porque el servicio de
transcripción tiene dos limitaciones medidas y comprobadas — **no devuelve tiempos por
palabra** y con audio largo **devuelve segmentos de 20-30 s y se come frases**. Todo el
diseño del pipeline nace de esas dos realidades.

## La regla que explica todo lo demás

**Los subtítulos no se generan desde la transcripción: se generan desde los silencios del
audio.** ffmpeg trocea la voz en frases naturales (VAD por `silencedetect`), cada frase se
transcribe por separado y cada bloque de texto queda **anclado al borde real del silencio**.
La transcripción solo aporta el texto; el tiempo lo aporta el audio. Por eso dos frases
seguidas no se pisan nunca y por eso un vídeo de una hora se comporta igual que uno de
un minuto.

## Quiero cambiar… → fichero

| Quiero… | Voy a… |
|---|---|
| Añadir o retocar un estilo | `lib/estilos.py` (registro `ESTILOS`) y su gemelo en `index.html` |
| Cambiar cómo se trocea el audio | `lib/audio.py` (`agrupar`, umbrales de `silencedetect`) |
| Tocar la transcripción o el reintento | `lib/stt.py` |
| Cambiar el prompt de la corrección | `lib/llm.py` (constante `SISTEMA`) |
| Ajustar el reparto de tiempos | `lib/tarjetas.py` (`tiempos_de_bloque`, duración mínima) |
| Cambiar cómo se quema o se exporta | `lib/render.py` |
| Añadir una opción de línea de órdenes | `subtitular.py` |
| La herramienta web (subir → elegir → descargar) | `servidor.py`, `app.js` e `index.html` |
| El dibujo de las miniaturas de estilo | `vista.js` |
| Cambiar las comprobaciones | `arnes.py` |
| Bajar ffmpeg y las fuentes | `herramientas/instalar.sh` |
| El vídeo de prueba con voz sintética | `pruebas/hacer_video.sh` y `pruebas/voz_prueba.sh` |
| La página que se publica | `index.html` |

## Los 8 estilos

| Clave | Nombre | Qué hace |
|---|---|---|
| `aurora7` | Aurora 7 | Inter blanca, palabra activa cian, banda oscura con filete de acento |
| `brutal` | Brutal (Hormozi) | Archivo Black en mayúsculas, contorno grueso, activo amarillo con golpe de escala |
| `bestia` | Bestia (MrBeast) | Anton con contorno brutal y halo cian, activo en cian eléctrico |
| `karaoke` | Karaoke | Montserrat con barrido de color continuo palabra a palabra |
| `neon` | Neón | Bebas Neue violeta con brillo, activo cian, entrada con fundido |
| `editorial` | Editorial | Inter en caja negra translúcida, sin golpes: para vídeo serio |
| `maquina` | Máquina de escribir | Space Grotesk que aparece palabra a palabra con cursor |
| `vhs` | VHS | Archivo con temblor y separación de color rojo/cian |

Las animaciones son ASS de verdad (`\t`, `\kf`, `\fad`, vectores con `\p1`), no plantillas
de texto: el mismo fichero `.ass` sirve para quemar y para abrir en un editor.

## Interfaz

La orden es `python3 subtitular.py <vídeo> [opciones]`. Lo que importa de la interfaz:

| Opción | Para qué |
|---|---|
| `--estilo` | Cuál de los 8 estilos |
| `--desde-json` | Reutiliza una transcripción ya hecha: cambia de estilo sin volver a llamar a la API |
| `--rehacer` | Ignora la transcripción guardada y la vuelve a hacer |
| `--solo-ass` | No recodifica: escribe `.ass`, `.srt` y `.json` |
| `--posicion`, `--escala`, `--mayusculas` | Colocación y tamaño |
| `--limite` | Procesa solo los primeros N segundos (pruebas) |
| `--sin-llm` | Reparte por reglas, sin qwen3.6 |
| `--listar-estilos` | Lista los estilos |

Cada ejecución deja cuatro ficheros: el vídeo subtitulado, el `.ass` (editable), el `.srt`
(para cualquier editor) y un `.json` con los tiempos **de cada palabra**, que es el
contrato que consume el previsualizador.

Y **no se paga dos veces la misma transcripción**: el motor guarda cada transcripción con una
huella del vídeo (tamaño + primeros y últimos megabytes) y la reaprovecha mientras no cambies
nada que afecte al texto. Pasar por los 8 estilos cuesta una transcripción, no ocho; eso se
midió: 22,9 s la primera y 0 llamadas a la API las otras siete.

## La herramienta web: subir el vídeo, elegir estilo y descargarlo

`python3 servidor.py` levanta la herramienta en `http://127.0.0.1:8765`: se arrastra el vídeo
(o se toca para elegirlo en el móvil), se elige uno de los 8 estilos viendo su miniatura, se
pide **un fotograma real del propio vídeo** con ese estilo para confirmar antes de gastar
proceso, y se descarga el resultado. El trabajo pesado lo hace esta máquina, no el navegador:
la página solo habla con el motor y va contando por dónde va.

- **Un trabajo a la vez.** 1 vCPU: quien llegue mientras se trabaja espera en cola, y se dice.
- **La barra no miente.** El avance sale del `-progress` de ffmpeg (minuto real de quema), no
  de una estimación.
- **Nada sale de la máquina.** El vídeo se sube a una carpeta propia (`trabajos/`) y la clave
  de la API nunca llega al navegador. Los trabajos se borran solos a las 24 horas.
- **Con `--host 0.0.0.0`** se abre además al móvil de casa.

`index.html` **es la misma página** que se publica en GitHub Pages
(https://ntizar.github.io/subtitulador-brutal/): ahí no hay motor detrás, así que lo detecta,
lo dice claramente y deja los 8 estilos para mirarlos. No finge que funciona.

## Previsualizador

`index.html` es una página autónoma (sin servidor, sin dependencias de build) que reproduce
los 8 estilos en canvas con la misma transcripción que usó el CLI: se le suelta el `.json` y
un vídeo local, y se ve el resultado antes de gastar un minuto de proceso. Publicada en
**https://ntizar.github.io/subtitulador-brutal/**

## Verificación

`arnes.py` no comprueba que la orden termine bien: comprueba el resultado. Valida estructura
(orden, solapes, palabras dentro de su bloque), cobertura (que las tarjetas estén en el
`.ass` y en el `.srt`) y render (extrae fotogramas reales con el ASS aplicado, mide que hay
tinta en la banda de subtítulos y que dos momentos distintos dan fotogramas distintos —
la única forma de cazar que libass no encuentre una fuente o que el reloj del filtro se
reinicie). `pruebas/arnes-navegador.html` hace lo mismo con la página en un navegador real.

Cifras medidas en la máquina de desarrollo (1 vCPU, sin GPU): un vídeo 1080×1920 de 59 s
tarda **38 s** en quemarse y sus 13 frases se transcriben en **9 s**; extrapolado, un vídeo
de 10 minutos sale en unos **6,5 minutos**.

## Detalles que cuestan tiempo si no se saben

- El modelo de transcripción se llama `whisper` a secas: `whisper-1` da 401.
- Si no se fuerza el idioma, con una frase suelta detecta mal el español (dice `en`); con
  una muestra de 25 s acierta.
- `qwen3.6` trae el *thinking* activado y se gasta el presupuesto antes de escribir el JSON:
  hay que apagarlo (`enable_thinking: false`).
- Los trozos de menos de ~1,2 s alucinan al transcribirse solos: el troceo los fusiona.
- En ASS, un bloque `{\c…}` afecta a **todo** lo que va detrás en la línea: hay que reponer
  el color en cada palabra. Y en las etiquetas karaoke el espacio va **fuera** de las llaves.
- libass necesita `FONTCONFIG_FILE` apuntando a `fuentes/fonts.conf`: esta máquina no tiene
  `/etc/fonts` ni fuentes de sistema.
- Al extraer un fotograma con subtítulos, `-ss` va **después** de `-i`; si va antes, el
  filtro reinicia su reloj y pinta el primer subtítulo en todos los fotogramas.

## Replicar este patrón en otra herramienta

**Qué se copia y qué no.** Se copia la forma: un motor en pasos numerados con su docstring
explicando *qué se midió* para llegar ahí, un registro declarativo (los estilos) separado de
su generador, un `.json` intermedio como contrato entre el motor y cualquier interfaz, y un
arnés que mide el resultado en vez de confiar en el código de salida. No se copia: las rutas
absolutas de la máquina (todo se calcula desde `RAIZ` en `lib/util.py`), ni el binario de
ffmpeg (lo baja `herramientas/instalar.sh`), ni los ficheros de `salidas/`.

**Qué hay que cambiar en el motor.** El proveedor y los nombres de modelo viven en `lib/stt.py`
y `lib/llm.py`; el idioma por defecto y la muestra de detección, en `subtitular.py`. Los
umbrales de troceo (`lib/audio.py`) son los que hay que reajustar si el material no es voz
continua: con música o con locución muy pausada, `min_s`, `max_s` y `max_gap` cambian el
resultado más que ningún estilo.

**Identidad.** El color, la tipografía y el contorno de cada estilo son datos, no código: se
declara una entrada en `ESTILOS` y su equivalente en el objeto `ESTILOS` de `index.html`. La
trampa es que son dos copias y hay que tocarlas juntas: el CLI manda sobre el render y la
página solo aproxima (canvas no tiene karaoke ni `\t`). Las fuentes van auto-alojadas en
`fuentes/` y `instalar.sh` las vuelve a bajar si faltan; **enlazar un CDN de fuentes está
prohibido** en este proyecto por coherencia con el resto de las webs.

**Modelo de contenido.** El JSON de la transcripción es la frontera: `info` (ancho, alto,
duración) más `tarjetas` con `inicio`, `fin`, `texto`, `clave` y `palabras` con sus tiempos.
Cualquier interfaz nueva (otro previsualizador, un editor, un lote) se enchufa ahí sin tocar
el motor.

**Publicación y control.** La web es un fichero suelto (`index.html`) servido por GitHub
Pages desde la rama principal; no hay build ni workflow. Antes de publicar se pasa el escáner
de PII y se comprueba con `curl` que las rutas sensibles dan 404.

**Comprobaciones antes de dar un cambio por bueno.** El arnés en verde
(`arnes.py --estilos todos`) con 0 fallos y 0 avisos, y el arnés del navegador con
`errores_js=0` y tinta en los 8 estilos. Un estilo nuevo que no pase por los dos no está
terminado.

## Fuentes y licencias

Las 9 fuentes de `fuentes/` son de Google Fonts con licencia SIL Open Font License y se
distribuyen aquí tal cual. ffmpeg **no** se incluye en el repositorio: lo descarga
`herramientas/instalar.sh` (compilación estática con libass y libx264, licencia GPL).

Hecho con ❤️ por David Antizar
