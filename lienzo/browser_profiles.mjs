// Sólo metadatos públicos del perfil; nunca se copian datos de sesión.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export function userDataDir() {
  if (process.platform === 'win32') {
    if (!process.env.LOCALAPPDATA) throw new Error('No se encontró la carpeta de Chrome del usuario');
    return join(process.env.LOCALAPPDATA, 'Google/Chrome/User Data');
  }
  return process.platform === 'darwin'
    ? join(homedir(), 'Library/Application Support/Google/Chrome')
    : join(homedir(), '.config/google-chrome');
}

export function profiles(root = userDataDir()) {
  const file = join(root, 'Local State');
  if (!existsSync(file)) return [];
  const info = JSON.parse(readFileSync(file, 'utf8')).profile?.info_cache;
  if (!info || typeof info !== 'object') throw new Error('Chrome no publicó su lista de perfiles');
  return Object.entries(info).filter(([id, value]) =>
    /^(Default|Profile \d+)$/.test(id) && value && typeof value.name === 'string'
  ).map(([id, value]) => ({id, name: value.name}));
}

export function existingEndpoint(root = userDataDir()) {
  const file = join(root, 'DevToolsActivePort');
  if (!existsSync(file)) throw new Error('Abrí tu perfil de Chrome en esa PC y habilitá la conexión en chrome://inspect/#remote-debugging. Después, conectá desde acá y aceptá el aviso que muestra Chrome.');
  if (statSync(file).size > 4096) throw new Error('Chrome publicó una conexión inválida');
  const [port, path] = readFileSync(file, 'utf8').trim().split(/\r?\n/);
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535
      || !/^\/devtools\/browser\/[\w-]+$/.test(path)) throw new Error('Chrome publicó una conexión inválida');
  return `ws://127.0.0.1:${Number(port)}${path}`;
}
