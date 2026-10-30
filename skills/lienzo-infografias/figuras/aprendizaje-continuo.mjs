// Prensa vertical de filtros con hojas extraíbles. 60 piezas; sin mesa común.
// Los filtros son lecturas distintas de la evidencia, no una conversión automática.
import { k, acento, write } from "../kit.mjs";
const width=660, height=510;
const bounds={x:-78,y:-60,w:194,d:205,r:4};
const P=k.fitProjection(k.boxCorners(bounds,0,210),width,height,{pad:35,azimuth:48,elevation:25});
const box=(x,y,w,d,z,h,style={})=>k.solidSvg(k.slabOf({x,y,w,d,r:1},z,h,P,4,.5),{tone:"mid",...style});
const disc=(x,y,r,z,h,style={})=>k.solidSvg(k.cylinder(x,y,r,z,h,P,64),{tone:"mid",...style});
const front=(x,y,z,t,size=5)=>k.faceTextSvg(k.sideMatrix([x,y],z,P,"left"),t,{size,tone:"hi",anchor:"middle"});
export function build(){
  const body=['<path class="iso-halo" d="'+k.haloOf(bounds,0,9,P)+'"/>'];
  body.push(disc(0,0,65,0,8,{tone:"lo"}));
  for(const x of [-48,48]) {
    body.push(disc(x,-28,8,8,5,{tone:"lo"}),disc(x,-28,4,13,174),disc(x,-28,8,187,5));
  }
  for(const [i,label] of ["1 Crudo","2 Cómo","3 Qué","Creencias"].entries()){
    const z=18+i*35;
    body.push(disc(0,0,43,z,6,{tone:"lo"}),disc(0,0,38,z+6,3,{tone:"hi"}));
    for(const dx of [-24,-8,8,24]) body.push(box(dx-2,-24,4,48,z+9,1,{tone:"lo"}));
    body.push(box(-29,16,58,42,z+10,1,{tone:"hi"}),box(-29,57,58,1,z+1,10,{tone:"hi"}));
    body.push(front(0,58,z+3,label,5.5));
    body.push(box(25,39,4,12,z+11,1,{className:i===3?acento.ambar:acento.verde}));
  }
  body.push(disc(0,0,33,153,6,{tone:"hi"}),disc(0,0,7,159,28));
  body.push(box(-58,-37,116,34,187,9));
  body.push(box(-24,-3,48,1,187,9,{tone:"hi"}),front(0,-2,189,"Prolog",6));
  body.push(disc(0,-20,6,196,7),box(-27,-23,54,6,203,4,{tone:"hi"}));
  // La llave humana está separada del contraste lógico.
  body.push(box(61,12,34,31,0,13,{tone:"lo"}),disc(78,27,9,13,3,{className:acento.ambar}));
  body.push(box(76,25,4,4,16,12),box(72,25,12,4,28,4,{tone:"hi",lit:true}));
  body.push(box(59,44,40,1,3,9,{tone:"hi"}),front(79,45,5,"Veredicto",4.5));
  for(const [i,t] of ["Contexto","Checklist","Controles"].entries()){
    const x=48,y=65+i*27,z=0;
    body.push(box(x,y,62,24,z,2,{tone:"hi"}),box(x+2,y+2,4,20,z+2,1,{className:acento.verde}));
    body.push(k.faceTextSvg(k.topMatrix([x+35,y+15],z+2,P,"x"),t,{size:4.5,tone:"hi",anchor:"middle"}));
  }
  return write("aprendizaje-continuo",{width,height,body,
    label:"Prensa vertical de cuatro filtros: crudo, cómo, qué y creencias propuestas. Prolog contrasta hechos y reglas; una llave aparte representa el veredicto humano. Tres hojas devuelven contexto, checklist y controles.",
    card:{fig:"Fig 10",title:"Aprendizaje que vuelve al trabajo",hint:"Lecturas distintas de la evidencia",readout:"Prolog contrasta · una persona da vigencia",
      keys:[{mark:"raised",label:"Filtros: crudo, proceso, resultados y propuestas"},{mark:"flat",label:"Cabezal Prolog: contraste, contraejemplos y deducción"},{mark:"lit",label:"Llave de veredicto; hojas para la siguiente ronda"}],
      caption:"Las cuatro capas no obligan a convertir cada captura en una creencia. La IA resume y propone; Prolog trabaja con hechos y reglas formalizadas, conserva pruebas y no otorga vigencia por sí solo. Los aprendizajes revisados vuelven al trabajo."}});
}
