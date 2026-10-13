(function () {
"use strict";

/* vista.js — motor de dibujo de los subtítulos, compartido por la herramienta
   y el previsualizador. Es el MISMO dibujo que el render de libass: los colores,
   la tipografía, el contorno y la animación salen de la tabla ESTILOS, gemela de
   lib/estilos.py. Extraído del previsualizador para no tener dos copias del dibujo. */

/* ───────── estilos: mismos parámetros que lib/estilos.py ───────── */
const ESTILOS = {
  aurora7:{nombre:"Aurora 7",fuente:"Inter",escala:.058,mayus:false,color:"#FFFFFF",clave:"#22D3EE",
    contorno:4,sombra:2,colorContorno:"#05070D",anim:"pop",pop:1.14,espaciado:1.2,
    banda:{alto:.055,color:"#0B1220",alfa:118,filete:"#22D3EE",fileteAlto:.006}},
  brutal:{nombre:"Brutal (Hormozi)",fuente:"Archivo Black",escala:.062,mayus:true,color:"#FFFFFF",
    clave:"#FFE000",contorno:6,sombra:0,colorContorno:"#000000",anim:"pop",pop:1.22,espaciado:.8},
  bestia:{nombre:"Bestia (MrBeast)",fuente:"Anton",escala:.066,mayus:true,color:"#FFFFFF",clave:"#00E5FF",
    contorno:7,sombra:3,colorContorno:"#000000",colorSombra:"#00B8D4",sombraAlfa:100,anim:"pop",pop:1.18,espaciado:.5},
  karaoke:{nombre:"Karaoke",fuente:"Montserrat",escala:.056,mayus:false,color:"#FFFFFF",clave:"#FF4D6D",
    contorno:4,sombra:2,colorContorno:"#12040B",anim:"karaoke",espaciado:.6},
  neon:{nombre:"Neón",fuente:"Bebas Neue",escala:.072,mayus:true,color:"#F5D0FE",clave:"#22D3EE",
    contorno:3,sombra:0,colorContorno:"#7C3AED",colorSombra:"#A855F7",sombraAlfa:90,anim:"pop",pop:1.12,
    espaciado:2,entradaFade:90},
  editorial:{nombre:"Editorial",fuente:"Inter",escala:.046,mayus:false,color:"#F8FAFC",clave:"#FBBF24",
    contorno:0,sombra:0,caja:true,cajaColor:"#000000",cajaAlfa:150,anim:"fade",fade:140,espaciado:.4},
  maquina:{nombre:"Máquina de escribir",fuente:"Space Grotesk",escala:.05,mayus:false,color:"#E5E7EB",
    clave:"#34D399",contorno:3,sombra:1,colorContorno:"#0A0F0D",anim:"maquina",espaciado:1},
  vhs:{nombre:"VHS",fuente:"Archivo",escala:.058,mayus:true,color:"#FDE047",clave:"#FF2D55",
    contorno:5,sombra:2,colorContorno:"#1B0030",colorSombra:"#22D3EE",sombraAlfa:120,anim:"glitch",espaciado:1.6}
};
const ORDEN = Object.keys(ESTILOS);
/* ───────── transcripción de ejemplo (la genera el CLI) ───────── */
const EJEMPLO = {
  info:{ancho:1080,alto:1920,duracion:25.4},
  tarjetas:[
    ["Bienvenidos al canal.",0,1.30,"Bienvenidos"],
    ["Hoy vamos a hablar",1.55,2.60,"hablar"],
    ["de tres cosas que",2.62,3.60,"tres"],
    ["cambian por completo",3.62,4.70,"cambian"],
    ["tu forma de trabajar con vídeo.",4.72,6.60,"vídeo"],
    ["Primero, la transcripción automática.",7.40,9.60,"transcripción"],
    ["Detección de frases por silencios reales.",9.80,12.10,"silencios"],
    ["Cada bloque cae donde acaba la voz.",12.30,14.40,"voz"],
    ["Segundo, el diseño del subtítulo.",15.20,17.30,"diseño"],
    ["Ocho estilos, y el que más te guste.",17.50,19.90,"guste"],
    ["Tercero, la quema con libass.",20.70,22.80,"libass"],
    ["Y listo. Así de simple.",23.00,25.00,"simple."]
  ].map(([texto,inicio,fin,clave],i)=>({i,inicio,fin,texto,clave,palabras:repartir(texto,inicio,fin)}))
};
function repartir(texto,inicio,fin){
  const ws=texto.split(/\s+/).filter(Boolean);
  const pes=ws.map(w=>Math.max(w.length,5)), tot=pes.reduce((a,b)=>a+b,0);
  let t=inicio; return ws.map((w,k)=>{const d=(fin-inicio)*pes[k]/tot;const p={w,a:t,b:t+d};t+=d;return p;});
}

/* ───────── estado del dibujo (lo fija la página) ───────── */
let estilo = "aurora7", posicion = "bajo", escala = 1, mayus = null;
let datos = { info: { ancho: 1080, alto: 1920, duracion: 0 }, tarjetas: [] };
let ctx = null;
/* Si la página tiene un <video> cargado, el motor dibuja ese fotograma de fondo; si no,
   pinta un fondo sintético. La herramienta web no usa vídeo en el lienzo (el vídeo real
   lo ve el usuario en su reproductor), así que aquí vive a null. */
let video = null;
/* ───────── dibujo ───────── */
function fondo(W,H,tt){
  const g=ctx.createLinearGradient(0,0,W,H);
  g.addColorStop(0,"#0B1020"); g.addColorStop(.5,"#1E1B4B"); g.addColorStop(1,"#082F49");
  ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
  // dos formas que se mueven, para que se note que hay "vídeo" detrás
  ctx.save(); ctx.globalAlpha=.20; ctx.fillStyle="#22D3EE";
  ctx.fillRect(W/2-180+Math.sin(tt/2)*130,H*0.36,360,H*0.27); ctx.restore();
  ctx.save(); ctx.globalAlpha=.5; ctx.fillStyle="#FF7A1A";
  ctx.fillRect(W/2-100,H*0.73,200,H*0.011); ctx.restore();
}
function fuente(est,px){ return `${px}px "${est.fuente}", "Noto Sans", sans-serif`; }

function medir(est,px,texto,esp){
  ctx.font=fuente(est,px);
  let w=ctx.measureText(texto).width;
  if(esp){ w += esp*(texto.length-1); }
  return w;
}
function pintaPalabra(w,x,y,est,px,color,esp){
  ctx.font=fuente(est,px);
  ctx.textAlign="left";
  if(est.caja){
    const a=(est.cajaAlfa??150)/255;
    ctx.save(); ctx.globalAlpha=1-a; ctx.fillStyle=est.cajaColor;
    ctx.fillRect(x-14,y-px*0.92,w+28,px*1.34); ctx.restore();
  }
  if(est.contorno>0){
    ctx.lineJoin="round"; ctx.lineWidth=est.contorno*(px/72); ctx.strokeStyle=est.colorContorno;
    if(est.colorSombra && est.sombra){ ctx.save(); ctx.globalAlpha=1-(est.sombraAlfa??0)/255;
      ctx.strokeStyle=est.colorSombra; ctx.save(); ctx.translate(0,px*0.06); ctx.strokeText(w,x,y); ctx.restore(); ctx.restore(); }
    ctx.strokeText(w,x,y);
  }
  if(est.sombra && !est.colorSombra){ ctx.save(); ctx.globalAlpha=.55; ctx.fillStyle="#000";
    ctx.fillText(w,x+px*0.05,y+px*0.05); ctx.restore(); }
  ctx.fillStyle=color; ctx.fillText(w,x,y);
  return x + w + (esp||0);
}
function tarjetaEn(tt){ return datos.tarjetas.find(c=>tt>=c.inicio && tt<=c.fin); }

function dibujar(tt,W,H,destino){
  const est=ESTILOS[estilo]; ctx=destino;
  ctx.clearRect(0,0,W,H);
  if(video && video.readyState>=2){ ctx.drawImage(video,0,0,W,H); } else { fondo(W,H,tt); }

  const card=tarjetaEn(tt); if(!card) return;
  const fsBase=Math.round(H*est.escala*escala);
  const util=W*0.88;
  const usaMayus = (mayus===null) ? est.mayus : mayus;
  const palabras=card.palabras.map(p=>({w: usaMayus ? p.w.toUpperCase() : p.w,
      a:p.a, b:p.b, orig:p.w}));
  const frase=palabras.map(p=>p.w).join(" ");
  let px=fsBase;
  const esp=est.espaciado||0;
  if(medir(est,px,frase,esp)>util) px=Math.max(12,Math.floor(px*util/medir(est,px,frase,esp)));

  const margen=H*(posicion==="alto"?0.12:0.11);
  let y = posicion==="alto" ? margen+px : (posicion==="medio" ? H/2+px/3 : H-margen);

  // banda de Aurora 7
  if(est.banda){
    const ah=H*est.banda.alto, cy=(y+ (y-px*1.32))/2, by=cy-ah/2, bx=W*0.05, bw=W-2*bx;
    ctx.save();
    ctx.globalAlpha=1-est.banda.alfa/255; ctx.fillStyle=est.banda.color;
    ctx.fillRect(bx,by,bw,ah);
    ctx.globalAlpha=1; ctx.fillStyle=est.banda.filete;
    ctx.fillRect(bx,by-H*est.banda.fileteAlto,bw,H*est.banda.fileteAlto);
    ctx.restore();
  }
  const anchoTotal=medir(est,px,frase,esp);
  let x=W/2-anchoTotal/2;

  if(est.anim==="karaoke"){
    ctx.font=fuente(est,px); ctx.textAlign="left";
    let xx=x;
    palabras.forEach(p=>{
      const cantado = tt>=p.b ? 1 : (tt<=p.a ? 0 : (tt-p.a)/(p.b-p.a));
      const w=ctx.measureText(p.w).width;
      // fondo del barrido: blanco; encima, en color, solo lo ya cantado
      const col = cantado>0.5 ? est.clave : est.color;
      xx=pintaPalabra(p.w,xx,y,est,px,col,esp);
    });
    return;
  }
  if(est.anim==="maquina"){
    const idx=palabras.findIndex(p=>tt<p.b);
    const vis=idx<0?palabras.length:idx+1;
    palabras.slice(0,vis).forEach(p=>{ x=pintaPalabra(p.w,x,y,est,px,est.color,esp); });
    ctx.font=fuente(est,px); ctx.fillStyle=est.clave;
    if(Math.floor(tt*3)%2===0) ctx.fillText("|",x+2,y);
    return;
  }
  if(est.anim==="fade"){
    palabras.forEach(p=>{ x=pintaPalabra(p.w,x,y,est,px,est.color,esp); });
    return;
  }
  // pop + glitch: la palabra activa se resalta y se agranda
  palabras.forEach((p,k)=>{
    const activo = tt>=p.a && (k+1>=palabras.length || tt<palabras[k+1].a);
    const esClave = card.clave && p.orig.toLowerCase().replace(/[.,;:!?¡¿]/g,"")===
                    card.clave.toLowerCase().replace(/[.,;:!?¡¿]/g,"");
    if(activo && est.anim==="glitch"){
      const desp=px*0.05;
      ctx.save(); ctx.globalAlpha=.7; ctx.fillStyle="#FF2D55"; ctx.font=fuente(est,px); ctx.textAlign="left";
      ctx.fillText(p.w,x-desp,y); ctx.fillStyle="#22D3EE"; ctx.fillText(p.w,x+desp,y); ctx.restore();
    }
    if(activo){
      const ppx=px*est.pop*((esClave)?1.06:1);
      const wAct=medir(est,ppx,p.w,esp);
      const wNorm=medir(est,px,p.w,esp);
      const dx=(wAct-wNorm)/2;
      pintaPalabra(p.w,x-dx,y,est,ppx,est.clave,esp);
      x += wNorm;
    } else {
      x=pintaPalabra(p.w,x,y,est,px,est.color,esp);
    }
  });
}


/* ───────── API que usa la página ───────── */

window.VISTA = {
  ESTILOS, ORDEN, EJEMPLO,
  opciones(o = {}) {
    if (o.estilo) estilo = o.estilo;
    if (o.posicion) posicion = o.posicion;
    if (o.escala != null) escala = o.escala;
    if ("mayusculas" in o) mayus = o.mayusculas;
    return { estilo, posicion, escala, mayus };
  },
  ponerDatos(d) { datos = d; },
  datos() { return datos; },
  tarjetaEn,
  /* Dibuja el fotograma t del vídeo en el canvas que le pases. */
  dibujar(t, W, H, destino) { ctx = destino; return dibujar(t, W, H, destino); },
  /* Miniatura de un estilo para el selector: usa la tarjeta 1 del ejemplo. */
  miniatura(canvas, clave) {
    const antes = { estilo, posicion, escala, mayus };
    estilo = clave; posicion = "bajo"; escala = 1; mayus = null;
    const c = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const card = datos.tarjetas[1] || datos.tarjetas[0];
    const t = card ? (card.inicio + card.fin) / 2 : 0;
    ctx = c; dibujar(t, W, H, c);
    ({ estilo, posicion, escala, mayus } = antes);
  },
  /* Cuántos caracteres puede tener una línea como máximo a este tamaño. */
  topeCaracteres(clave, alto) {
    const est = ESTILOS[clave];
    return Math.floor((alto * 0.88) / ((alto * (est.escala || 0.05)) * 0.52));
  },
};

})();
