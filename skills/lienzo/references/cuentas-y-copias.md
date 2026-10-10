# Cuenta de GitHub, secretos y copias entre PCs

Parte de la skill `lienzo` (se lee desde `SKILL.md` cuando hace falta).

## Cuenta de GitHub por repo

Ariel usa cuentas personales y de trabajo. Elegí la cuenta por repo antes de consultar un repo
privado, pasar una credencial a otra PC o pushear. Para `arielelevy/chesstudia` y
`arielelevy/lienzo`, la cuenta indicada por Ariel es `arielelevy`. En otros repos, mirá el remote
y las instrucciones del proyecto; el dueño del repo puede ser una organización y no alcanza para
deducir la cuenta. `git user.name` y `git user.email` son la firma del commit, no el login.

```powershell
git remote get-url origin
gh auth status
gh auth switch --hostname github.com --user arielelevy
gh api user --jq .login
gh api repos/arielelevy/chesstudia --jq .permissions.push
```

Git y `gh` pueden usar almacenes distintos. Si Git sigue tomando otra cuenta, configurá el helper
solo en ese repo para usar la cuenta activa de `gh`. Revisá primero los helpers locales existentes;
el valor vacío corta los helpers heredados. No cambies el helper global de los demás proyectos.

```powershell
git config --local --get-all credential.helper
git --% config --local credential.helper ""
git config --local --add credential.helper "!gh auth git-credential"
git -c credential.interactive=false ls-remote --heads origin
```

En PowerShell, `--%` conserva el argumento vacío. En bash, usá `git config --local credential.helper ''`.
El switch de `gh` cambia la cuenta activa para ese host en toda la PC. Revalidá `gh api user`
antes de operar otro repo; coordiná el cambio si hay sesiones trabajando con otra cuenta.
Un `Repository not found` puede ser falta de acceso con la cuenta actual o un remote incorrecto.
Un `ls-remote` exitoso prueba lectura; verificá `.permissions.push` para escritura.
Si falta la cuenta o el acceso, frená y pedí el login correspondiente. No borres otras cuentas ni
imprimas tokens. Cambiar de cuenta no autoriza un push: hace falta el pedido de Ariel para ese repo.

## Secretos entre PCs (un token de git)

Nunca pegues un token en un mensaje: queda en claro en los adjuntos y en los transcripts. Para que otra
PC pueda pushear, `c.pasar_credencial_git(pc, "https://host/repo.git")` copia la credencial que ESTA PC
ya tiene guardada: viaja cifrada y la otra la guarda en su almacén de Windows, sin pasar por vos. Para
otro secreto: `c.enviar_secreto(pc, nombre, valor)` (queda 10 min) y `c.leer_secreto(id, pc=pc)` (una
sola vez, desde cualquier PC de la LAN). `git_auth` en `/peers` dice por qué falla: `vencida` (la credencial: pasala con
`pasar_credencial_git`), `sin_red` (no llega al host) o `timeout` (git no terminó): en esos dos, pasar
otra credencial no arregla nada. Arreglalo antes de mandar un encargo que termine en push.
Con varias cuentas de GitHub en `gh`, no hace falta `gh auth switch`: la PC fija cada repo vivo de
github.com a la cuenta con push en su `.git/config` (`cuenta_github.py`), y un 403 por cuenta
equivocada se vuelve a elegir solo en la próxima medición.

La salud también trae `cuotas` por agente (`ok`, `agotada`, «agotada hasta HH:MM»). Lanzar una coda en
una PC con la cuota agotada da 409: lanzala en otra PC o usá otro agente.

## Copiar archivos a otra PC

Para mover datos entre PCs (un volcado de la base, una carpeta de miles de archivos) está el canal
del lienzo, no SMB ni un `scp`: va por el listener de peers, firmado con la clave del par, retoma
tras un corte y verifica cada archivo.

```python
xid = c.copiar(pc, r"\\wsl.localhost\Ubuntu\home\yo\volcado", r"\\wsl.localhost\Ubuntu-24.04\home\otro\recibido")
c.avance(xid)  # estado, pct, mbps, eta_s, archivos_hechos, errores, ultimos
v = c.copiar(pc, origen, destino, esperar=True)  # vuelve cuando termina, ya verificado del otro lado
c.pausar_copia(xid)
c.retomar_copia(xid)
```

- `destino` es siempre una carpeta: un archivo de origen cae como `destino/<nombre>`; una carpeta
  copia su contenido adentro.
- Origen y destino tienen que caer en **`copy_roots`** del `config.json` de cada PC (vacía es
  ninguna). Si da 403, la carpeta no está ahí: agregarla en esa PC y reiniciar no hace falta, se lee en
  cada pedido.
- `estado == "terminado"` quiere decir que cada archivo se releyó del otro lado y coincidió bloque a
  bloque. Recién ahí se puede borrar el origen (por ejemplo, la tabla de un volcado hecho de a una).
  `con_errores`: lo que falló está en `errores`; `c.retomar_copia` lo reintenta sin rehacer lo hecho.
- Una segunda copia de lo mismo manda sólo los bloques distintos. Nunca borra en el destino, salvo
  `espejo=True`: ahí frena en `confirmar_espejo` con la lista `borraria`, y borra sólo después de
  `c.confirmar_espejo(xid)`.
- Se frena solo si cualquiera de las dos PCs baja de 1,5 GB libres (`detalle` dice «memoria baja»):
  no es una falla, sigue cuando se libera. Con muchas sesiones abiertas puede quedar parada un rato.
- Opciones: `hilos` (6), `bs_mib` (8), `mbps` y `disco_mbps` (topes, 0 = sin tope).
- Rutas de WSL: con `\\wsl.localhost\<distro>\...`. Desde Windows se leen por 9p, que rinde bien con
  archivos grandes y mal con miles de chicos.
