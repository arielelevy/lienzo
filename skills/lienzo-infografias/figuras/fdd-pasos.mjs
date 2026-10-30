// Selector mecánico de cuatro posiciones: una ficha y un último paso con llave.
// 55 piezas sólidas. Las marcas indican hitos, no porcentaje de avance.
import { acento, k, write } from "../kit.mjs";
const width=680,height=470;
const bounds={x:-135,y:-155,w:270,d:290,r:8};
const P=k.fitProjection(k.boxCorners(bounds,0,65),width,height,{pad:32,azimuth:42,elevation:46});
const box=(x,y,w,d,z,h,style={})=>k.solidSvg(k.slabOf({x,y,w,d,r:1},z,h,P,4,.5),{tone:"mid",...style});
const disc=(x,y,r,z,h,style={})=>k.solidSvg(k.cylinder(x,y,r,z,h,P,80),{tone:"mid",...style});
const text=(x,y,z,t,size=5)=>k.faceTextSvg(k.topMatrix([x,y],z,P,"x"),t,{size,tone:"hi",anchor:"middle"});
export function build(){
  const body=['<path class="iso-halo" d="'+k.haloOf(bounds,0,8,P)+'"/>'];
  body.push(disc(0,0,112,0,12,{tone:"lo"}),disc(0,0,107,12,7),disc(0,0,98,19,2,{tone:"hi"}));
  // Dientes sobre la corona: las posiciones son discretas.
  for(let i=0;i<24;i++){
    const a=i*Math.PI/12,x=103*Math.cos(a),y=103*Math.sin(a);
    body.push(disc(x,y,2.2,19,3));
  }
  body.push(box(-31,-12,62,24,21,2,{tone:"lo"}),text(0,3,23,"Constitución",5.5));
  const positions=[[-62,-46,"1 Diseñado"],[20,-46,"2 Implementado"],[-62,37,"3 Verificado"],[20,37,"4 Integrado"]];
  for(const [i,[x,y,t]] of positions.entries()){
    body.push(box(x,y,45,25,21,2,{tone:"hi"}),text(x+22.5,y+17,23,t,4.1));
    body.push(disc(x+23,y-5,4,21,3,{className:i===3?acento.rojo:acento.verde}));
    for(const dx of [3,42]) body.push(disc(x+dx,y+3,1,23,1));
  }
  // Portaficha en la posición verificada.
  body.push(box(-100,22,32,7,21,4),box(-98,24,28,1,25,34,{tone:"hi"}));
  body.push(k.faceTextSvg(k.sideMatrix([-84,25],47,P,"left"),"Ficha",{size:5,tone:"hi",anchor:"middle"}));
  for(const z of [32,37,42]) body.push(k.lineSvg(k.segment([-95,25,z],[-73,25,z],P),{tone:"lo",free:true}));
  // Cerradura de integración; la llave queda afuera, en manos de la persona.
  body.push(disc(43,74,8,21,4,{className:acento.rojo}),box(40,73,6,2,25,1,{tone:"lo"}));
  body.push(box(88,72,25,4,0,3,{className:acento.ambar}),disc(114,74,6,0,3,{className:acento.ambar}));
  // Mapa apoyado al costado: no forma parte de la secuencia de hitos.
  body.push(box(-54,-151,108,28,0,1,{tone:"hi"}),text(0,-132,1,"Mapa del dominio",5.5));
  for(const x of [-36,-12,12,36]) body.push(box(x-3,-147,6,4,1,1));
  return write("fdd-pasos",{width,height,body,
    label:"Selector circular con cuatro posiciones: diseñado, implementado, verificado e integrado. Una ficha está en verificado. La corona es la constitución, el mapa del dominio está al costado y la última posición requiere una llave humana.",
    card:{fig:"FDD",title:"Una ficha, cuatro hitos",hint:"La corona sostiene las cuatro posiciones",readout:"Integrar requiere una persona",
      keys:[{mark:"green",label:"Posiciones con evidencia observada"},{mark:"red",label:"Cerradura: integración humana"},{mark:"flat",label:"Corona: constitución; hoja: mapa del dominio"}],
      caption:"La ficha conserva objetivo, alcance, criterios, evidencia y próximo paso. Cada posición exige su evidencia; no representa un porcentaje. Un cambio puntual y claro se hace y se verifica directo, sin abrir ficha."}});
}
