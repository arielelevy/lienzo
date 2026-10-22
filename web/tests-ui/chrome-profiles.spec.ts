import {expect, test, type Page} from '@playwright/test';
import {bloquearEscrituras} from './tablero-fijo';

// Ariel tiene dos perfiles de Chrome abiertos a la vez («Ariel» y «globant.com»): cada pestaña dice de
// cuál es. El host da el contexto de cada pestaña y la lista de ventanas el perfil que Windows le marca.
async function profilesFlow(page: Page, windows: {id: string; title: string; profile?: string}[], mode = 'existing') {
  await bloquearEscrituras(page);
  await page.route('**/auth', r => r.fulfill({json:{configured:false,authenticated:true,local:true}}));
  await page.route('**/peers', r => r.fulfill({json:[{pc_id:'flow',name:'Fixture',alive:true,local:false}]}));
  await page.routeWebSocket('**/browser/stream*', ws => ws.onMessage(() => {}));
  await page.route('**/browser', r => {
    const action = r.request().postDataJSON().action;
    if (action === 'windows') return r.fulfill({json:{windows}});
    if (action === 'profiles') return r.fulfill({json:{profiles:[{id:'Profile 1',name:'Ariel'},{id:'Profile 3',name:'globant.com'}]}});
    return r.fulfill({json:{running:true, mode, image:'/9j/2Q==', width:1280, height:800, tabs:[
      {id:'a', title:'YouTube', url:'https://youtube.test/', context:'c1'},
      {id:'b', title:'Correo', url:'https://mail.test/', context:'c2'},
      {id:'c', title:'Docs', url:'https://docs.test/', context:'c1'},
      {id:'d', title:'Nueva pestaña', url:'chrome://newtab/', context:'c2'},
    ]}});
  });
  await page.goto('/chrome?pc=flow');
  await page.getByRole('button', {name:'Controles de Chrome remoto'}).click();
}

test('las pestañas se agrupan por perfil con su nombre', async ({page}) => {
  await profilesFlow(page, [
    {id:'1', title:'YouTube - Google Chrome', profile:'Ariel'},
    {id:'2', title:'Correo - Google Chrome', profile:'globant.com'},
  ]);
  await page.getByRole('button', {name:'Vista por pestañas', exact:true}).click();
  const strip = page.getByRole('tablist', {name:'Pestañas remotas'});
  await expect(strip.getByText('Ariel', {exact:true})).toBeVisible();
  await expect(strip.getByText('globant.com', {exact:true})).toBeVisible();
  // juntas por perfil, aunque Chrome las liste mezcladas
  await expect(strip.getByRole('tab')).toHaveText([/YouTube/, /Docs/, /Correo/, /Nueva pestaña/]);
  await expect(page.getByRole('tab', {name:'Docs'})).toHaveAccessibleName('Docs · perfil Ariel');
  await expect(page.getByRole('tab', {name:'Nueva pestaña'})).toHaveAccessibleName('Nueva pestaña · perfil globant.com');
});

test('si Windows no dice el perfil, igual se distinguen', async ({page}) => {
  await profilesFlow(page, [{id:'1', title:'YouTube - Google Chrome', profile:'Ariel'}]);
  await page.getByRole('button', {name:'Vista por pestañas', exact:true}).click();
  const strip = page.getByRole('tablist', {name:'Pestañas remotas'});
  await expect(strip.getByText('Ariel', {exact:true})).toBeVisible();
  await expect(strip.getByText('Otro perfil', {exact:true})).toBeVisible();
  await expect(page.getByRole('tab', {name:'Correo'})).toHaveAccessibleName('Correo · Otro perfil');
});

test('la ventana completa dice el perfil de cada ventana', async ({page}) => {
  await profilesFlow(page, [
    {id:'1', title:'YouTube - Google Chrome', profile:'Ariel'},
    {id:'2', title:'Correo - Google Chrome', profile:'globant.com'},
  ]);
  const select = page.getByRole('combobox', {name:'Ventana de Chrome'});
  await expect(select.locator('option')).toHaveText(['YouTube - Google Chrome · Ariel', 'Correo - Google Chrome · globant.com']);
});

test('con el Chrome propio de Lienzo no usa los perfiles del Chrome de la persona', async ({page}) => {
  // las ventanas que lista Windows son del Chrome de la persona; las pestañas, del Chrome aislado de Lienzo
  await profilesFlow(page, [{id:'1', title:'YouTube - Google Chrome', profile:'Ariel'}], 'lienzo');
  await page.getByRole('button', {name:'Vista por pestañas', exact:true}).click();
  const strip = page.getByRole('tablist', {name:'Pestañas remotas'});
  await expect(strip.getByText('Otro perfil 1', {exact:true})).toBeVisible();
  await expect(strip.getByText('Ariel', {exact:true})).toHaveCount(0);
});
