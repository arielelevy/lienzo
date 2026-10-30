// Cinta de montaje abierta, sin plataforma común. 69 piezas sólidas.
// Los tres útiles son frentes ilustrativos, no etapas obligatorias.
import { k, acento, write } from "../kit.mjs";
const width = 760, height = 450;
const bounds = { x: -185, y: -54, w: 365, d: 112, r: 4 };
const P = k.fitProjection(k.boxCorners(bounds, 0, 105), width, height, { pad: 32, azimuth: 62, elevation: 28 });
const box = (x,y,w,d,z,h,style={}) => k.solidSvg(k.slabOf({x,y,w,d,r:1},z,h,P,4,.5), {tone:"mid",...style});
const text = (x,y,z,t,size=5) => k.faceTextSvg(k.topMatrix([x,y],z,P,"x"),t,{size,tone:"hi",anchor:"middle"});
function plaque(x,y,z,w,t) { return box(x,y,w,12,z,1,{tone:"hi"}) + text(x+w/2,y+8,z+1,t); }
export function build() {
  const body = ['<path class="iso-halo" d="'+k.haloOf(bounds,0,9,P)+'"/>'];
  for (const x of [-105,105]) for (const y of [-24,26]) {
    body.push(box(x-5,y-5,10,10,0,3,{tone:"lo"}),box(x-2,y-2,4,4,3,31));
  }
  for (const y of [-27,27]) body.push(box(-125,y,290,4,30,8,{tone:"lo"}));
  body.push(box(-128,-23,296,50,33,4,{tone:"lo"}));
  for (let i=0;i<19;i++) body.push(box(-124+i*15,-22,13,48,37,2,{tone:"hi"}));
  // Torre coordinadora y cajones de rondas, fuera de la cinta.
  body.push(box(-183,-20,43,52,0,6,{tone:"lo"}),box(-177,-14,31,36,6,80));
  body.push(box(-175,22,27,1,49,28,{tone:"lo"}),box(-172,23,21,1,53,20,{tone:"hi",lit:true}));
  for (const z of [12,22,32]) body.push(box(-174,22,25,2,z,7,{tone:"hi"}),box(-166,24,9,2,z+2,2));
  body.push(plaque(-181,-17,86,39,"Coordina"),plaque(-181,34,0,39,"Rondas"));
  for (const x of [-112,134]) body.push(box(x,-47,7,7,0,96));
  body.push(box(-112,-47,253,9,96,7));
  body.push(plaque(-48,-46,103,92,"Meta-harness"));
  // Útiles distintos: pinza, sello, lector.
  for (const [i,x] of [-80,10,100].entries()) {
    body.push(box(x-3,-42,6,19,72,24),box(x-12,-23,24,7,72,7));
    if(i===0) for(const dx of [-12,8]) body.push(box(x+dx,-16,4,18,52,23));
    if(i===1) body.push(box(x-4,-16,8,15,55,20),box(x-17,-19,34,24,51,4,{tone:"hi"}));
    if(i===2) body.push(box(x-14,-16,28,10,61,10),box(x-11,-6,22,1,63,5,{className:acento.verde}));
    body.push(plaque(x-18,-36,79,36,"Frente"));
  }
  for(const [x,color] of [[-100,acento.ambar],[-10,acento.ambar],[120,acento.verde]]) {
    body.push(box(x,-8,28,22,39,3,{tone:"hi"}),box(x+2,-6,4,18,42,1,{className:color}));
  }
  body.push(plaque(-116,34,0,62,"Encargos"),plaque(91,34,0,62,"Informes"));
  return write("fabrica", {width,height,body,
    label:"Línea de montaje sobre patas: torre coordinadora y archivo de rondas; pórtico meta-harness con tres útiles de agentes sobre una cinta con encargos ámbar e informes verdes.",
    card:{fig:"Fig 9",title:"La fábrica de software",hint:"Una cinta, distintos instrumentos",readout:"La coordinadora verifica el árbol",
      keys:[{mark:"lit",label:"Torre: coordinación; cajones: rondas"},{mark:"raised",label:"Pórtico: meta-harness; útiles: frentes"},{mark:"flat",label:"Ámbar: encargos; verde: informes"}],
      caption:"La cinta representa el trabajo que circula. Los útiles son frentes ilustrativos, no pasos obligatorios ni un máximo de sesiones. El pórtico reúne lanzamiento, hooks, permisos y controles. Recibir el informe no sustituye verificar el árbol."}});
}
