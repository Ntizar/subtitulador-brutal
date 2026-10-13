/* app.js — la herramienta: subir el vídeo, elegir estilo y descargarlo subtitulado.
   Habla con servidor.py (mismo origen). Si no hay motor detrás (por ejemplo si esta
   página se abre publicada en GitHub Pages) se dice claramente y solo se previsualiza. */
const $ = id => document.getElementById(id);

let trabajo = null;      // id del trabajo en el servidor
let fichero = null;      // File elegido
let estilo = "aurora7";
let posicion = "bajo";
let mayus = false;
let sondeo = null;

const nombreBonito = () => (fichero ? fichero.name.replace(/\.[^.]+$/, "") : "vídeo");

function fmtDuracion(s) {
  s = Math.max(0, Math.round(s || 0));
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}
function fmtTiempo(s) {
  s = Math.max(0, Math.round(s || 0));
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}

/* ───── el selector de estilos: 8 piezas con su miniatura dibujada ───── */
function montarEstilos() {
  const marco = $("marco");
  VISTA.ponerDatos(VISTA.EJEMPLO);
  marco.innerHTML = "";
  for (const k of VISTA.ORDEN) {
    const est = VISTA.ESTILOS[k];
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sb-pieza";
    b.dataset.estilo = k;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(k === estilo));
    b.innerHTML = '<canvas class="sb-mini" width="270" height="480" aria-hidden="true"></canvas>' +
      '<span class="sb-nombre">' + est.nombre + "</span>";
    b.addEventListener("click", () => elegir(k));
    marco.appendChild(b);
    try { VISTA.miniatura(b.querySelector("canvas"), k); } catch (e) { console.warn("miniatura", k, e); }
  }
  elegir(estilo);
}

function elegir(k) {
  estilo = k;
  VISTA.opciones({ estilo: k });
  for (const n of $("marco").children) {
    const on = n.dataset.estilo === k;
    n.classList.toggle("is-active", on);
    n.setAttribute("aria-checked", String(on));
  }
  $("caja-muestra").hidden = true;   // la muestra era de otro estilo
}

/* ───── subir el vídeo ───── */
async function subir(f) {
  if (!f) return;
  if (!/^video\//.test(f.type) && !/\.(mp4|mov|m4v|webm|mkv|avi|mts|mpg|mpeg)$/i.test(f.name)) {
    aviso("Ese fichero no parece un vídeo. Prueba con MP4, MOV, WEBM o MKV.");
    return;
  }
  fichero = f;
  $("ficha").hidden = false;
  $("f-nombre").textContent = f.name;
  $("f-tamano").textContent = (f.size / 1e6).toFixed(1) + " MB";
  $("f-duracion").textContent = "…";
  $("f-resolucion").textContent = "…";
  $("nota-boton").textContent = "Subiendo el vídeo…";
  $("btn-subtitular").disabled = true;
  const fd = new FormData();
  fd.append("video", f, f.name);
  try {
    const r = await fetch("/api/videos", { method: "POST", body: fd });
    if (!r.ok) throw new Error(detalle(await r.json().catch(() => ({}))) || ("error " + r.status));
    const d = await r.json();
    trabajo = d.id;
    $("f-duracion").textContent = fmtDuracion(d.duracion);
    $("f-resolucion").textContent = d.ancho && d.alto ? d.ancho + "×" + d.alto : "—";
    const seg = 0.8 * (d.duracion || 0) + 12;
    $("f-estimacion").textContent =
      "Tardará del orden de " + fmtTiempo(seg) + " en subtitularlo (60 s de vídeo ≈ 50 s de " +
      "trabajo aquí). La primera vez incluye transcribir; si repites con otro estilo, " +
      "ese paso se reaprovecha.";
    $("nota-boton").textContent = "Vídeo listo. Elige estilo y dale.";
    $("btn-subtitular").disabled = false;
    $("btn-muestra").disabled = false;
    $("nota-muestra").textContent = "";
    $("caja-resultado").hidden = true;
    $("caja-error").hidden = true;
  } catch (e) {
    $("nota-boton").textContent = "No he podido subirlo.";
    $("f-estimacion").textContent = "El motor no responde: " + e.message +
      ". ¿Está arrancado servidor.py en tu máquina?";
  }
}

function detalle(d) { return d && (d.detail || d.message) ? d.detail || d.message : ""; }
function aviso(texto) { $("nota-muestra").textContent = texto; }

/* ───── subtitular y seguir el avance ───── */
async function subtitular() {
  if (!trabajo) return;
  $("caja-error").hidden = true;
  $("caja-resultado").hidden = true;
  $("caja-progreso").hidden = false;
  $("barra").style.width = "0%";
  $("fase").textContent = "Arrancando el motor…";
  $("registro").textContent = "";
  $("btn-subtitular").disabled = true;
  const fd = new FormData();
  fd.append("estilo", estilo);
  fd.append("posicion", posicion);
  fd.append("mayusculas", mayus ? "true" : "false");
  try {
    const r = await fetch("/api/videos/" + trabajo + "/subtitular", { method: "POST", body: fd });
    if (!r.ok) throw new Error(detalle(await r.json().catch(() => ({}))) || ("error " + r.status));
    seguir();
  } catch (e) {
    fallo(e.message);
  }
}

function seguir() {
  clearInterval(sondeo);
  sondeo = setInterval(async () => {
    let d;
    try {
      d = await (await fetch("/api/videos/" + trabajo + "/estado")).json();
    } catch (e) { return; }                     // un fallo suelto no corta el trabajo
    $("barra").style.width = Math.min(100, d.pct || 0) + "%";
    $("fase").textContent = d.fase || "trabajando";
    if (d.log && d.log.length) $("registro").textContent = d.log.join("\n");
    if (d.estado === "trabajando" && d.inicio) {
      $("detalle-tiempo").textContent = "lleva " + fmtTiempo(Date.now() / 1000 - d.inicio) +
        " de trabajo" + (d.aviso ? " · " + d.aviso : "");
    }
    if (d.estado === "listo") { clearInterval(sondeo); terminado(d); }
    else if (d.estado === "error") { clearInterval(sondeo); fallo(d.error || "el motor falló"); }
  }, 1500);
}

function terminado(d) {
  $("btn-subtitular").disabled = false;
  $("caja-progreso").hidden = true;
  $("caja-resultado").hidden = false;
  const url = "/api/videos/" + trabajo + "/descarga";
  $("reproductor").src = url;
  $("descargar").href = url;
  $("descargar").setAttribute("download", nombreBonito() + "." + estilo + ".mp4");
  $("descargar-srt").href = "/api/videos/" + trabajo + "/subtitulos";
  $("descargar-srt").setAttribute("download", nombreBonito() + "." + estilo + ".srt");
  $("resumen").textContent = "Listo en " + fmtTiempo(d.segundos) + " (" + (d.mb || "?") +
    " MB) con el estilo «" + VISTA.ESTILOS[estilo].nombre + "».";
  $("caja-resultado").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function fallo(texto) {
  $("btn-subtitular").disabled = false;
  $("caja-progreso").hidden = true;
  $("caja-error").hidden = false;
  $("texto-error").textContent = texto;
}

/* ───── un fotograma real de SU vídeo con el estilo elegido ───── */
async function pedirMuestra() {
  if (!trabajo) return;
  const fd = new FormData();
  fd.append("estilo", estilo);
  fd.append("posicion", posicion);
  fd.append("mayusculas", mayus ? "true" : "false");
  $("btn-muestra").disabled = true;
  $("nota-muestra").textContent = "Sacando el fotograma…";
  try {
    const r = await fetch("/api/videos/" + trabajo + "/fotograma", { method: "POST", body: fd });
    if (!r.ok) throw new Error(detalle(await r.json().catch(() => ({}))) || ("error " + r.status));
    const blob = await r.blob();
    const viejo = $("muestra").dataset.url;
    if (viejo) URL.revokeObjectURL(viejo);
    const url = URL.createObjectURL(blob);
    $("muestra").src = url;
    $("muestra").dataset.url = url;
    $("caja-muestra").hidden = false;
    $("pie-muestra").textContent = "Así queda tu vídeo con «" + VISTA.ESTILOS[estilo].nombre +
      "». Es un fotograma de verdad, sacado del render.";
    $("nota-muestra").textContent = "";
  } catch (e) {
    $("nota-muestra").textContent = e.message;
  }
  $("btn-muestra").disabled = false;
}

/* ───── enganches ───── */
function montarZona() {
  const zona = $("zona");
  $("fichero").addEventListener("change", e => subir(e.target.files[0]));
  ["dragenter", "dragover"].forEach(t => zona.addEventListener(t, e => {
    e.preventDefault(); zona.classList.add("is-active");
  }));
  ["dragleave", "drop"].forEach(t => zona.addEventListener(t, e => {
    e.preventDefault(); zona.classList.remove("is-active");
  }));
  zona.addEventListener("drop", e => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) subir(f);
  });
  $("posicion").addEventListener("click", e => {
    const b = e.target.closest("button[data-pos]");
    if (!b) return;
    posicion = b.dataset.pos;
    for (const n of e.currentTarget.children) {
      n.setAttribute("aria-selected", n === b ? "true" : "false");
    }
    $("caja-muestra").hidden = true;
  });
  $("mayus").addEventListener("change", e => { mayus = e.target.checked; $("caja-muestra").hidden = true; });
  $("btn-subtitular").addEventListener("click", subtitular);
  $("btn-muestra").addEventListener("click", pedirMuestra);
}

async function hayMotor() {
  try {
    const r = await fetch("/api/estilos", { cache: "no-store" });
    return r.ok;
  } catch (e) { return false; }
}

(async function arrancar() {
  montarEstilos();
  montarZona();
  if (!(await hayMotor())) {
    $("aviso-motor").hidden = false;
    $("modo").textContent = "sin motor";
    $("nota-boton").textContent = "Esta página necesita el motor en marcha para subtitular.";
  }
  document.documentElement.dataset.listo = "1";
})();
