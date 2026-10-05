# Lienzo por Tailscale: qué hacer en cada PC

Para cuando las dos PCs están en una red que no las deja verse (un Wi-Fi público con aislamiento
de clientes: la otra PC no responde ni ARP). Con Tailscale cada PC tiene una IP 100.x.y.z que llega
desde la otra en cualquier red, y el lienzo la encuentra solo (commit `9fc9f4a`, 2026-10-05).

Hacer esto **en las dos PCs**:

1. **Instalar Tailscale** desde <https://tailscale.com/download> y entrar con **la misma cuenta** en
   las dos. Comprobar que se ven:

   ```powershell
   tailscale status        # tiene que listar la otra PC, con su IP 100.x
   tailscale ping <nombre-de-la-otra-pc>
   ```

2. **Traer el código**:

   ```powershell
   cd D:\Apps\lienzo
   git pull
   ```

3. **Instalar de nuevo, con la regla de firewall de Tailscale.** Abrir PowerShell **como
   administrador**:

   ```powershell
   cd D:\Apps\lienzo
   py -3.14 install.py --peer
   ```

   Tiene que decir `agregada regla de firewall Lienzo Peer TCP Tailscale` y `... Beacon UDP
   Tailscale`. Sin administrador no toca el firewall y avisa.

4. **Reiniciar el lienzo**: cerrar la ventana `lienzo` y abrir `lienzo-server.cmd` de nuevo.

## Cómo saber que anduvo

- En `~/.lienzo/lienzo.log` aparece `listener de peers por Tailscale en http://100.x.y.z:7322`
  (si Tailscale se prendió después, en menos de un minuto).
- En menos de un minuto la otra PC pasa a ● en la tira del tablero, y el log dice
  `peer <nombre>: espejo reconectado por beacon a 100.x.y.z`.
- Si las PCs nunca se emparejaron, la otra aparece en «🖥 Varias PCs» → «En esta red» y se empareja
  con la palabra de siempre.

## Si no aparece

El chip caído de la otra PC dice el motivo:

| En la tira | Qué hacer |
|---|---|
| no llega por Tailscale | Tailscale apagado o con otra cuenta en alguna de las dos: `tailscale status` |
| la PC está en la red pero no contesta el puerto | faltó el paso 3 (como administrador) en esa PC |
| el puerto está cerrado | el lienzo no corre en esa PC (paso 4) |
| sin ARP: la red aísla a los equipos | todavía no pasó a Tailscale: esperar un minuto o revisar el paso 1 |
| la última IP conocida es de otra red | idem: todavía no llegó ningún anuncio por Tailscale |
