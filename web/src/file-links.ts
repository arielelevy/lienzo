import { defaultUrlTransform } from "react-markdown";

/** Conserva enlaces externos; lleva rutas físicas al visor de Lienzo. */
export function fileLink(href: string, base?: string): string {
  const normalized = href.replace(/\\/g, "/");
  if (/^(?:file:\/\/\/|\/?[a-z]:\/)/i.test(normalized)) {
    const path = normalized.replace(/^file:\/\/\//i, "").replace(/^\/([a-z]:\/)/i, "$1");
    return `/archivo?path=${encodeURIComponent(path)}`;
  }
  if (base && normalized && !/^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(normalized)) {
    const url = new URL(normalized, `https://local.invalid/${base.replace(/^\//, "")}`);
    return `/archivo?path=${encodeURIComponent(decodeURIComponent(url.pathname).replace(/^\/([a-z]:\/)/i, "$1"))}${url.hash}`;
  }
  return defaultUrlTransform(href);
}
