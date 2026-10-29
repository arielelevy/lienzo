import {expect, test, type Page} from '@playwright/test';
import {bloquearEscrituras} from './tablero-fijo';

async function nativeFlow(page: Page) {
  await bloquearEscrituras(page);
  await page.route('**/auth', r => r.fulfill({json:{configured:false,authenticated:true,local:true}}));
  await page.route('**/peers', r => r.fulfill({json:[{pc_id:'flow',name:'Fixture',alive:true,local:false}]}));
  await page.route('**/browser', r => r.fulfill({json:r.request().postDataJSON().action === 'windows'
    ? {windows:[{id:'123',title:'Fixture'},{id:'456',title:'Otra ventana'}]} : {profiles:[{id:'Default',name:'Fixture'}]}}));
  const commands: {t:string;n?:number;events?:{type:string;x:number;y:number}[]}[] = [];
  let reply: (message:string) => void = () => {};
  let close = () => {};
  const header = Buffer.alloc(17);
  header.writeUInt32BE(1); header.writeUInt16BE(1,8); header.writeUInt16BE(1,10);
  header.writeUInt16BE(1280,12); header.writeUInt16BE(800,14); header.writeUInt8(1,16);
  const frame=Buffer.concat([header,Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4AWP4z8AAAAMBAQDbfS68AAAAAElFTkSuQmCC','base64')]);
  await page.routeWebSocket('**/browser/stream*', ws => {
    reply = message => ws.send(message);
    close = () => ws.close();
    ws.onMessage(message => { const d=JSON.parse(String(message)); commands.push(d); if(d.t==='open')ws.send(frame); });
  });
  await page.goto('/chrome');
  const screen=page.getByRole('application',{name:'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  return {screen, commands, reply:(message:string)=>reply(message), close:()=>close()};
}

test('ventana limita hover sin ACK, conserva el último y no pierde clics', async ({page}) => {
  const {screen,commands,reply}=await nativeFlow(page);
  const box=(await screen.boundingBox())!;
  for(let i=0;i<12;i++) { await page.mouse.move(box.x+box.width/2+i*5,box.y+box.height/2); await page.waitForTimeout(35); }
  const inputs=()=>commands.filter(d=>d.t==='input');
  expect(inputs()).toHaveLength(1);
  reply(JSON.stringify({t:'input',n:inputs()[0].n}));
  await expect.poll(()=>inputs().length).toBe(2);
  const scale=Math.min(box.width/1280,box.height/800);
  expect(inputs()[1].events![0].x).toBe(Math.round(640+55/scale));
  reply(JSON.stringify({t:'input',n:inputs()[1].n}));
  await page.mouse.down(); await page.mouse.up();
  await expect.poll(()=>inputs().flatMap(d=>d.events??[]).filter(e=>e.type==='mousePressed').length).toBe(1);
  for (const command of inputs().filter(d=>d.events?.some(e=>e.type==='mousePressed'))) reply(JSON.stringify({t:'input',n:command.n}));
  await expect.poll(()=>inputs().flatMap(d=>d.events??[]).filter(e=>e.type==='mouseReleased').length).toBe(1);
  expect(inputs().flatMap(d=>d.events??[]).filter(e=>e.type==='mousePressed')).toHaveLength(1);
  const ids=inputs().map(d=>d.n!);
  expect(ids.every((id,index)=>index===0||id>ids[index-1])).toBeTruthy();
});

for (const failure of ['timeout', 'rejected'] as const) test(`ventana bloquea ${failure}, libera, se reconecta sola y no reenvía`, async ({page}) => {
  await page.clock.install();
  const {screen,commands,reply}=await nativeFlow(page);
  await screen.focus();
  await page.keyboard.press('a');
  await page.clock.runFor(100);
  await expect.poll(()=>commands.filter(d=>d.t==='input').length).toBeGreaterThan(0);
  const original=commands.filter(d=>d.t==='input');
  const released=commands.filter(d=>d.t==='release').length;
  if(failure==='timeout') await page.clock.runFor(10100);
  else reply(JSON.stringify({t:'error',input:true,n:original[0].n,message:'Cambió la ventana activa'}));
  await expect(screen).toHaveAttribute('aria-disabled','true');
  const warning=page.locator('.remote-input-warning');
  await expect(warning).toBeVisible();
  await expect(page.getByRole('button',{name:'Reconectar entrada sin reenviar'})).toHaveCount(0);
  await expect.poll(()=>commands.filter(d=>d.t==='release').length).toBeGreaterThan(released);
  const opens=commands.filter(d=>d.t==='open').length;
  await page.clock.runFor(1100);
  await expect.poll(()=>commands.filter(d=>d.t==='open').length).toBeGreaterThan(opens);
  await expect(screen).not.toHaveAttribute('aria-disabled','true');
  await expect(warning).toBeVisible();
  await page.clock.runFor(40000);
  await expect(warning).toHaveCount(0);
  for(const command of original) reply(JSON.stringify({t:'input',n:command.n}));
  await screen.focus();
  await page.keyboard.press('b');
  await page.clock.runFor(100);
  await expect.poll(()=>commands.filter(d=>d.t==='input').length).toBeGreaterThan(original.length);
  const after=commands.filter(d=>d.t==='input');
  expect(after.slice(0,original.length)).toEqual(original);
  expect(after.slice(original.length).some(c=>JSON.stringify(c.events)===JSON.stringify(original[0].events))).toBe(false);
});

test('ventana libera tecla retenida al blur y antes de cambiar destino', async ({page}) => {
  const {screen,commands,reply}=await nativeFlow(page);
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(()=>commands.filter(d=>d.t==='input').length).toBe(1);
  reply(JSON.stringify({t:'input',n:commands.find(d=>d.t==='input')!.n}));
  const before=commands.length;
  await page.getByRole('button',{name:'Controles de Chrome remoto'}).click();
  await expect.poll(()=>commands.slice(before).some(d=>d.t==='release')).toBeTruthy();
  await page.getByRole('combobox',{name:'Ventana de Chrome'}).selectOption('456');
  await expect.poll(()=>commands.filter(d=>d.t==='open').length).toBe(2);
  const opened=commands.findLastIndex(d=>d.t==='open');
  expect(commands[opened-1].t).toBe('release');
  await page.keyboard.up('Shift');
});

test('ventana reconecta sin reproducir una tecla cuyo ACK se perdió', async ({page}) => {
  await page.clock.install();
  const {screen,commands,reply,close}=await nativeFlow(page);
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(()=>commands.filter(d=>d.t==='input').length).toBe(1);
  const first=commands.find(d=>d.t==='input')!;
  close();
  await expect(screen).toHaveAttribute('aria-disabled','true');
  await page.clock.runFor(600);
  await expect.poll(()=>commands.filter(d=>d.t==='open').length).toBe(2);
  await expect(screen).not.toHaveAttribute('aria-disabled','true');
  expect(commands.filter(d=>d.t==='input')).toEqual([first]);
  reply(JSON.stringify({t:'input',n:first.n}));
  await page.keyboard.up('Shift');
  await page.keyboard.press('b');
  await expect.poll(()=>commands.filter(d=>d.t==='input').length).toBeGreaterThan(1);
  const ids=commands.filter(d=>d.t==='input').map(d=>d.n!);
  expect(ids.every((id,index)=>index===0||id>ids[index-1])).toBeTruthy();
});
