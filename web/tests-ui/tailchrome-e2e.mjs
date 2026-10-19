/** Dos Lienzos aislados. El proxy Tailchrome se sustituye sólo en el transporte
 * del navegador (100.x -> loopback). No acredita extensión ni red remota real. */
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import net from 'node:net';

const root=resolve(import.meta.dirname,'../..');
const out=resolve(root,'pruebas-agenticas/resultados/tailchrome');
await mkdir(out,{recursive:true});
const children=[];
let browser;
const proxySockets=new Set();
// Proxy HTTP local de prueba: la única IP 100.x del caso se enruta a loopback.
// Chrome usa su configuración de proxy real, como hace Tailchrome.
const proxy=net.createServer(client=>{
  proxySockets.add(client);client.on('close',()=>proxySockets.delete(client));client.on('error',()=>client.destroy());
  let buffered=Buffer.alloc(0);
  function first(data){
    buffered=Buffer.concat([buffered,data]);if(buffered.length>65536){client.destroy();return;}
    const end=buffered.indexOf('\r\n\r\n');if(end<0)return;
    client.removeListener('data',first);client.pause();
    const head=buffered.subarray(0,end).toString('latin1'),lines=head.split('\r\n');
    const [method,target,version]=lines[0].split(' ');
    const url=new URL(method==='CONNECT'?`http://${target}`:target);
    const hostname=url.hostname==='100.81.147.100'?'127.0.0.1':url.hostname;
    if(hostname!=='127.0.0.1'){client.destroy();return;}
    const upstream=net.connect(Number(url.port)||80,hostname,()=>{
      if(method==='CONNECT')client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      else{lines[0]=`${method} ${url.pathname}${url.search} ${version}`;upstream.write(lines.join('\r\n')+'\r\n\r\n');}
      if(buffered.length>end+4)upstream.write(buffered.subarray(end+4));
      client.pipe(upstream);upstream.pipe(client);client.resume();
    });
    proxySockets.add(upstream);upstream.on('close',()=>{proxySockets.delete(upstream);client.destroy();});
    upstream.on('error',()=>client.destroy());client.on('close',()=>upstream.destroy());
  }
  client.on('data',first);
});
await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
async function start(id,other){
  const home=resolve(out,`${id}-${process.pid}`);await mkdir(home,{recursive:true});
  await writeFile(resolve(home,'peer.json'),JSON.stringify({pc_id:id,name:id,color:'#12B886'}));
  const child=spawn('py',['-3.14',resolve(root,'tests/tailchrome_fixture.py'),other],{
    cwd:root,env:{...process.env,LIENZO_HOME:home,PYTHONIOENCODING:'utf-8',LIENZO_TEST_AUTO_HOST:'1'},stdio:['ignore','pipe','pipe'],windowsHide:true,
  });
  children.push(child);const lines=createInterface({input:child.stdout});
  let log='';child.stderr.on('data',d=>log+=d);child.stdout.on('data',d=>log+=d);
  const ports=await new Promise((yes,no)=>{
    const timer=setTimeout(()=>no(Error('fixture no arrancó')),15000);
    child.once('exit',code=>{clearTimeout(timer);no(Error(`fixture salió ${code}: ${log}`));});
    child.once('error',no);
    lines.on('line',line=>{if(line.startsWith('{')){clearTimeout(timer);yes(JSON.parse(line));}});
  });
  return {...ports,home,id,other,child,save:()=>writeFile(resolve(out,`${id}.log`),log)};
}
async function eventually(check){
  const deadline=Date.now()+15000;let last;
  while(Date.now()<deadline){try{return await check();}catch(error){last=error;await new Promise(r=>setTimeout(r,100));}}
  throw last;
}
let nodes=[];
try{
  nodes=[await start('aaaaaaaaaaaa','bbbbbbbbbbbb'),await start('bbbbbbbbbbbb','aaaaaaaaaaaa')];
  for(let i=0;i<2;i++){
    const n=nodes[i],other=nodes[1-i];
    await writeFile(resolve(n.home,'peers.json'),JSON.stringify({[other.id]:{
      pc_id:other.id,name:other.id,ip:'127.0.0.2',port:other.peer,key:Buffer.alloc(32,'k').toString('hex'),
    }}));
  }
  const before=await Promise.all(nodes.map(n=>readFile(resolve(n.home,'peers.json'),'utf8')));
  browser=await chromium.launch({headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--proxy-bypass-list=<-loopback>']});
  const page=await browser.newPage({viewport:{width:1050,height:850}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${nodes[0].board}/tailchrome`);
  await page.getByRole('option',{name:nodes[1].id}).waitFor({state:'attached'});
  await page.getByText('Puente manual para diagnóstico',{exact:true}).click();
  await page.getByLabel('IP de Tailscale de esa PC').fill('100.81.147.100');
  await page.getByRole('button',{name:'Conectar puente',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Puente conectado.'}).waitFor({timeout:15000});
  for(let i=0;i<2;i++)await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[i].board}/test/forward-health`);
    assert.equal(response.status,200);assert.equal((await response.json()).fixture_pc,nodes[1-i].id);
  });
  await page.screenshot({path:resolve(out,'conectado.png'),fullPage:true});
  await page.getByRole('button',{name:'Desconectar',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Puente desconectado.'}).waitFor();
  await eventually(async()=>{
    for(const n of nodes){const response=await fetch(`http://127.0.0.1:${n.board}/test/forward-health`);assert.equal(response.status,503);}
  });
  await page.getByRole('button',{name:'Conectar puente',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Puente conectado.'}).waitFor({timeout:15000});
  await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[0].board}/test/forward-health`);
    assert.equal(response.status,200);
  });
  await page.close();
  await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[1].board}/test/forward-health`);assert.equal(response.status,503);
  });
  for(let i=0;i<2;i++)assert.equal(await readFile(resolve(nodes[i].home,'peers.json'),'utf8'),before[i]);
  // Proceso automático: inventario entero, sin ninguna IP ingresada en la UI.
  await writeFile(resolve(nodes[0].home,'network.json'),JSON.stringify({running:true,
    selfNode:{id:'self',hostname:'fixture-lienzo',online:true,tailscaleIPs:['100.64.1.9']},
    peers:[{id:'known',hostname:nodes[1].id,online:true,tailscaleIPs:['100.81.147.100']},
      {id:'unknown',hostname:'otro-equipo',online:true,tailscaleIPs:['100.68.123.40']},
      {id:'phone',hostname:'telefono',online:false,tailscaleIPs:['100.71.143.59']}],totalPeers:3,
  }));
  const autoPage=await browser.newPage();
  await autoPage.goto(`http://127.0.0.1:${nodes[0].board}/tailchrome`);
  await autoPage.getByRole('button',{name:'Activar proceso automático',exact:true}).click();
  await autoPage.getByRole('table',{name:'Equipos de Tailscale'}).getByRole('row').filter({hasText:nodes[1].id}).filter({hasText:'Conectado'}).waitFor({timeout:20000});
  assert.equal(await autoPage.getByRole('table').getByRole('row').count(),5);
  await autoPage.screenshot({path:resolve(out,'automatico.png'),fullPage:true});
  await browser.close();browser=undefined; // no quedan pestañas ni navegador
  for(let i=0;i<2;i++)await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[i].board}/test/forward-health`);
    assert.equal(response.status,200);assert.equal((await response.json()).fixture_pc,nodes[1-i].id);
  });
  assert.deepEqual(JSON.parse(await readFile(resolve(nodes[0].home,'tailchrome-process.json'),'utf8')),{enabled:true});
  await writeFile(resolve(nodes[0].home,'Downloads/Reunion.pdf'),'local-original');
  await writeFile(resolve(nodes[1].home,'Downloads/Reunion.pdf'),'remote-approved');
  const notes=Buffer.alloc(400000,'G');
  await writeFile(resolve(nodes[1].home,'Downloads/Notas.pdf'),notes);
  const base=`http://127.0.0.1:${nodes[0].board}`;
  const post=(path,body)=>fetch(base+path,{method:'POST',headers:{'X-Lienzo':'1','Content-Type':'application/json'},body:JSON.stringify(body)});
  assert.equal((await post('/downloads/enable',{pc:nodes[1].id})).status,200);
  const filesResponse=await fetch(base+`/downloads?pc=${nodes[1].id}`);assert.equal(filesResponse.status,200);
  const files=await filesResponse.json(),old=files.files.find(f=>f.name==='Reunion.pdf');assert.equal(old.exists,true);
  const selection={plan:files.plan,files:files.files.map(f=>f.id)};
  assert.equal((await post('/downloads',selection)).status,409);
  assert.equal(await readFile(resolve(nodes[0].home,'Downloads/Reunion.pdf'),'utf8'),'local-original');
  const transfer=await post('/downloads',{...selection,replace:[old.id]});assert.equal(transfer.status,202);
  const job=await transfer.json();
  await eventually(async()=>{
    const result=await (await fetch(base+`/downloads/jobs/${job.id}`)).json();assert.equal(result.state,'received');
  });
  assert.equal(await readFile(resolve(nodes[0].home,'Downloads/Reunion.pdf'),'utf8'),'remote-approved');
  assert.deepEqual(await readFile(resolve(nodes[0].home,'Downloads/Notas.pdf')),notes);
  await nodes[0].save();nodes[0].child.kill();
  nodes[0]=await start(nodes[0].id,nodes[0].other); // mismo LIENZO_HOME, puertos nuevos
  for(let i=0;i<2;i++)await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[i].board}/test/forward-health`);assert.equal(response.status,200);
  });
  const stopped=await fetch(`http://127.0.0.1:${nodes[0].board}/tailchrome/process`,{method:'POST',headers:{'X-Lienzo':'1','Content-Type':'application/json'},body:JSON.stringify({enabled:false})});
  assert.equal(stopped.status,200);
  await eventually(async()=>{
    const response=await fetch(`http://127.0.0.1:${nodes[1].board}/test/forward-health`);assert.equal(response.status,503);
  });
  for(let i=0;i<2;i++)assert.equal(await readFile(resolve(nodes[i].home,'peers.json'),'utf8'),before[i]);
  assert.deepEqual(errors,[]);
  console.log('OK: proceso automático sin Chrome, inventario, autostart, descargas cifradas de 400 KB, confirmación de sobrescritura, stop y peers.json intacto. Helper y tailnet sustituidos; integración real pendiente.');
}catch(error){
  for(const page of browser?.contexts().flatMap(c=>c.pages())||[])await page.screenshot({path:resolve(out,'fallo.png'),fullPage:true}).catch(()=>{});
  throw error;
}finally{
  await browser?.close();
  for(const child of children){child.kill();}
  for(const socket of proxySockets)socket.destroy();
  await new Promise(resolve=>proxy.close(resolve));
  await Promise.all(nodes.map(n=>n.save()));
}
