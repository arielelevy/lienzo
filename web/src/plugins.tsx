/// <reference types="vite/client" />
import type { ComponentType } from "react";

/** Lo que recibe la vista de un plugin local. */
export interface PluginProps {
  toast: (msg: string, err?: boolean) => void;
}

/** Plugins locales del tablero: `web/src/extensiones/*.tsx`, carpeta que Git ignora (como la de
 *  `lienzo/extensiones/` del server). Cada uno exporta por defecto su vista y habla con su ruta
 *  `/ext/<nombre>/...`. Sin ninguno, el build y el tablero quedan igual. */
const modulos = import.meta.glob<{ default?: ComponentType<PluginProps> }>("./extensiones/*.tsx", { eager: true });
const vistas = Object.keys(modulos)
  .sort()
  .map((ruta) => [ruta, modulos[ruta].default] as const)
  .filter((p): p is readonly [string, ComponentType<PluginProps>] => !!p[1]);

export function Plugins({ toast }: PluginProps) {
  return (
    <>
      {vistas.map(([ruta, Vista]) => (
        <Vista key={ruta} toast={toast} />
      ))}
    </>
  );
}
