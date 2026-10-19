import { expect, test } from "@playwright/test";
import { abrirTablero, sesiones } from "./tablero-fijo";
import type { Peer } from "../src/types";

const peers: Peer[] = [
  { pc_id:"local",name:"esta-PC",color:"#123456",alive:true,local:true,last_seen:null,health:null },
  { pc_id:"remote",name:"otra-PC",color:"#abcdef",alive:true,local:false,last_seen:null,health:null },
];
const preview = {plan:"plan-1",source:"REMOTE/Downloads",destination:"LOCAL/Downloads",files:[
  {id:"new",name:"Notas Gemini.pdf",size:100,modified_ns:1700000000000000000,exists:false},
  {id:"old",name:"Reunion.docx",size:200,modified_ns:1700000000000000000,exists:true},
]};

for (const overwrite of [false,true]) test(`clic derecho pide confirmación y ${overwrite?'sobrescribe':'saltea'} existentes`,async({page})=>{
  const writes: Record<string,unknown>[]=[];
  await abrirTablero(page,sesiones(),peers);
  await page.route('**/downloads**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(request.method()==='GET'&&path==='/downloads')return route.fulfill({json:preview});
    if(request.method()==='POST'&&path==='/downloads'){writes.push(request.postDataJSON());return route.fulfill({status:202,json:{id:'job-1'}});}
    if(path==='/downloads/jobs/job-1')return route.fulfill({json:{id:'job-1',state:'received',bytes:100,total:100,error:null,files:[{name:'Notas Gemini.pdf',state:'received'}]}});
    return route.fulfill({status:404,json:{error:'fixture desconocida'}});
  });
  await page.locator('.pcchip',{hasText:'otra-PC'}).click({button:'right'});
  await page.getByRole('menuitem',{name:'Traer descargas…'}).click();
  const dialog=page.getByRole('dialog',{name:'Traer descargas de otra-PC'});
  await expect(dialog.getByText('Ya existe',{exact:true})).toBeVisible();
  await dialog.getByLabel('Traer Notas Gemini.pdf',{exact:true}).check();
  await dialog.getByLabel('Traer Reunion.docx',{exact:true}).check();
  await dialog.getByRole('button',{name:'Traer seleccionados (2)',exact:true}).click();
  await expect(page.getByRole('alertdialog',{name:'Confirmar sobrescritura'})).toBeVisible();
  expect(writes).toEqual([]);
  await dialog.getByRole('button',{name:overwrite?'Sobrescribir y traer':'Saltear existentes',exact:true}).click();
  await expect(dialog.getByText(/Archivos recibidos y verificados/)).toBeVisible();
  await expect(dialog.getByRole('heading',{name:'✓ Transferencia finalizada'})).toBeVisible();
  await expect(dialog.getByRole('progressbar')).toHaveCount(0);
  await expect(dialog.getByText('Los 30 archivos más recientes. Elegí cuáles guardar en esta PC.')).toHaveCount(0);
  expect(writes).toEqual([{plan:'plan-1',files:overwrite?['new','old']:['new'],replace:overwrite?['old']:[]}]);
  await dialog.getByRole('button',{name:'Cerrar',exact:true}).click();
  await expect(dialog).toHaveCount(0);
});

test('respuesta tardía al cerrar el diálogo no escribe ni abre otra PC',async({page})=>{
  await abrirTablero(page,sesiones(),peers);
  await page.route('**/downloads?*',async route=>{await new Promise(resolve=>setTimeout(resolve,500));await route.fulfill({json:preview});});
  await page.locator('.pcchip',{hasText:'otra-PC'}).click({button:'right'});
  await page.getByRole('menuitem',{name:'Traer descargas…'}).click();
  await page.getByRole('button',{name:'Cerrar descargas'}).click();
  await expect(page.getByRole('dialog',{name:'Traer descargas de otra-PC'})).toHaveCount(0);
  await page.waitForTimeout(700);
  await expect(page.getByRole('dialog',{name:'Traer descargas de otra-PC'})).toHaveCount(0);
});
