import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, isMissingRoute } from "../api";
import type { Peer } from "../types";
import { usePeers } from "./PcStrip";
import "../remote-browser.css";

type Tab = { id: string; title: string; url: string };
type Reply = {
  windows?: {id: string; title: string}[];
  profiles?: {id: string; name: string}[]; prepared?: boolean;
  connecting?: boolean; autoApproving?: boolean; connectionError?: string; mode?: 'existing' | 'lienzo';
  running?: boolean; tabs?: Tab[]; id?: string; image?: string; width?: number; height?: number;
  back?: boolean; forward?: boolean; text?: string; dialog?: {type: string; message: string; defaultPrompt?: string} | null;
};
type Command = Record<string, unknown>;
/** Lo que manda el worker por el canal vivo (browser_window.py --stream): texto JSON o un cuadro binario. */
type StreamMessage = { t: string; n?: number; capture_ms?: number; encode_ms?: number; text?: string; message?: string; input?: boolean; cursor?: string; window?: string; windows?: {id: string; title: string}[] };
const FRAME_HEADER = 17; // >IHHHHHHB: seq, x, y, ancho, alto, ancho total, alto total, flags
// Cuadro v2 (browser_window.frame_v2): despues de la cabecera, la copia del scroll (>hHHHHH: dy, x0,
// x1, top, bottom, parches) y cada parche como >HHHHI (x, y, ancho, alto, largo) + PNG.
const FRAME_V2 = 0x80, SCROLL_BYTES = 12, PATCH_BYTES = 12;
type V2Frame = {scroll: {dy: number; x0: number; x1: number; top: number; bottom: number} | null; patches: {x: number; y: number; blob: Blob}[]};

/** Lee un cuadro v2 y verifica que la copia y cada parche caigan adentro de la imagen. */
function parseV2(buffer: ArrayBuffer, fullWidth: number, fullHeight: number): V2Frame {
  const view = new DataView(buffer);
  if (buffer.byteLength < FRAME_HEADER + SCROLL_BYTES) throw new Error('Cuadro de Chrome remoto incompleto');
  let pos = FRAME_HEADER;
  const dy = view.getInt16(pos), x0 = view.getUint16(pos + 2), x1 = view.getUint16(pos + 4);
  const top = view.getUint16(pos + 6), bottom = view.getUint16(pos + 8), count = view.getUint16(pos + 10);
  pos += SCROLL_BYTES;
  let scroll: V2Frame['scroll'] = null;
  if (dy) {
    if (x0 >= x1 || x1 > fullWidth || top >= bottom || bottom > fullHeight || top - dy < 0 || bottom - dy > fullHeight)
      throw new Error('Corrimiento de Chrome remoto inválido');
    scroll = {dy, x0, x1, top, bottom};
  }
  const patches: V2Frame['patches'] = [];
  for (let i = 0; i < count; i++) {
    if (pos + PATCH_BYTES > buffer.byteLength) throw new Error('Cuadro de Chrome remoto incompleto');
    const x = view.getUint16(pos), y = view.getUint16(pos + 2), w = view.getUint16(pos + 4), h = view.getUint16(pos + 6), n = view.getUint32(pos + 8);
    pos += PATCH_BYTES;
    if (!w || !h || x + w > fullWidth || y + h > fullHeight || pos + n > buffer.byteLength) throw new Error('Dimensiones de Chrome remoto inválidas');
    patches.push({x, y, blob: new Blob([new Uint8Array(buffer, pos, n)], {type: 'image/png'})});
    pos += n;
  }
  if (pos !== buffer.byteLength) throw new Error('Cuadro de Chrome remoto inválido');
  return {scroll, patches};
}
const modifiers = (e: {altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean}) =>
  Number(e.altKey) + Number(e.ctrlKey) * 2 + Number(e.metaKey) * 4 + Number(e.shiftKey) * 8;
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(n)));
const WORKER_BUSY = 'Chrome está atendiendo otro pedido; esperá un momento';
const READ_RETRY_DELAYS = [500, 1000, 1500];
const isWorkerBusy = (e: unknown) => e instanceof ApiError && e.status === 409 && e.body.error === WORKER_BUSY;

function waitForBrowserRetry(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException('La vista se cerró', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, {once: true});
  });
}

/** Tope de lo pegado en la ventana real (browser_window.PASTE_MAX_CHARS); en bytes, el pedido al
 *  worker no pasa de 64 KiB (browser_stream.MAX_COMMAND) aun con escapes JSON. */
const PASTE_MAX_CHARS = 16000;
const PASTE_MAX_BYTES = 48000;

async function writeClipboard(text: string) {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  // Los visores abiertos por HTTP en la LAN no tienen Clipboard API.
  const focused = document.activeElement as HTMLElement | null;
  const field = document.createElement('textarea');
  field.value = text;
  field.style.cssText = 'position:fixed;left:-10000px;top:0';
  document.body.append(field);
  try {
    field.select();
    if (!document.execCommand('copy')) throw new Error('El navegador no permitió copiar al portapapeles local');
  } finally { field.remove(); focused?.focus(); }
}

export function RemoteBrowser() {
  const peers = usePeers();
  const [native, setNative] = useState(true);
  const [controls, setControls] = useState(false);
  const [toolbarSlot, setToolbarSlot] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!controls) return;
    let timer: ReturnType<typeof setTimeout>;
    const activity = (event?: Event) => {
      const target = event?.target as Element | undefined;
      if (target?.closest('.remote-screen')) { setControls(false); return; }
      clearTimeout(timer);
      timer = setTimeout(() => setControls(false), 5000);
    };
    activity();
    document.addEventListener('pointerdown', activity);
    document.addEventListener('keydown', activity);
    return () => { clearTimeout(timer); document.removeEventListener('pointerdown', activity); document.removeEventListener('keydown', activity); };
  }, [controls]);
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("pc") ?? "");
  if (!selected && peers.length) {
    const initial = peers.find(p => !p.local) ?? peers.find(p => p.local);
    if (initial) setSelected(initial.pc_id);
  }
  const pc = selected;
  const peer = peers.find(p => p.pc_id === pc);
  const choose = (id: string) => {
    setSelected(id);
    history.replaceState(null, "", `/chrome?pc=${encodeURIComponent(id)}`);
  };
  return <main className={`remote-browser${native ? ' remote-browser-native' : ''}${controls ? ' remote-controls-open' : ''}`}>
    <button className="remote-controls-toggle" aria-label="Controles de Chrome remoto" aria-expanded={controls} onClick={()=>setControls(!controls)}>⋮</button>
    <div className="remote-controls-menu" aria-label="Opciones de Chrome remoto" onKeyDown={e=>{if(e.key==='Escape')setControls(false);}}>
    <div className="remote-top">
      <a href="/" className="remote-home" title="Volver al tablero">Lienzo</a>
      <span className="remote-brand">Chrome remoto</span>
      <label className="remote-pc">PC
        <select aria-label="PC del navegador" value={pc} onChange={e => choose(e.target.value)}>
          {!peers.length && <option value="">Buscando PCs…</option>}
          {peers.map(p => <option key={p.pc_id} value={p.pc_id}>{p.name}{p.local ? " (esta PC)" : ""}{p.alive ? "" : " · desconectada"}</option>)}
        </select>
      </label>
    </div>
    <div className="remote-mode"><button aria-pressed={native} onClick={() => setNative(true)}>Chrome real · ventana completa</button><button aria-pressed={!native} onClick={() => setNative(false)}>Vista por pestañas</button></div>
    <div ref={setToolbarSlot} />
    </div>
    {peer ? <ChromeMode key={peer.pc_id} peer={peer} native={native} toolbarSlot={toolbarSlot} /> : <div className="remote-empty">No se encuentra la PC. Revisá la conexión desde el tablero.</div>}
  </main>;
}

function ChromeMode({peer, native, toolbarSlot}: {peer: Peer; native: boolean; toolbarSlot: HTMLDivElement | null}) {
  return native ? <ChromeWindow peer={peer} toolbarSlot={toolbarSlot} /> : <BrowserDesktop peer={peer} />;
}

/** Tamaño físico que se le pide a la ventana remota: el área visible por la escala de pantalla. */
function physicalSize(box: DOMRect | undefined): {width: number; height: number} | undefined {
  if (!box || box.width < 320 || box.height < 200) return undefined;
  const scale = Math.min(globalThis.devicePixelRatio || 1, 3840 / box.width, 2160 / box.height);
  return {width: Math.round(box.width * scale), height: Math.round(box.height * scale)};
}

/** Ventana completa de Chrome por el canal vivo: la PC dueña empuja cada cuadro apenas cambia y el
 *  mouse sale por el mismo socket, sin esperar la imagen. */
function ChromeWindow({peer, toolbarSlot}: {peer: Peer; toolbarSlot: HTMLDivElement | null}) {
  const [windows, setWindows] = useState<NonNullable<Reply['windows']>>([]);
  const [window, setWindow] = useState('');
  const [profiles, setProfiles] = useState<NonNullable<Reply['profiles']>>([]);
  const [profile, setProfile] = useState('');
  const [error, setError] = useState('');
  const [inputError, setInputError] = useState('');
  const [inputBlocked, setInputBlocked] = useState(false);
  const [inputEpoch, setInputEpoch] = useState(0);
  const [stats, setStats] = useState({input: 0, fps: 0, kbps: 0, remote: ''});
  const [notice, setNotice] = useState('');
  const [copied, setCopied] = useState(false);
  const [cursor, setCursor] = useState('default');
  const [busy, setBusy] = useState(false);
  const [size, setSize] = useState<{width: number; height: number} | null>(null);
  const [canvas] = useState(() => document.createElement('canvas'));
  const viewport = useRef<HTMLDivElement>(null);
  const socket = useRef<WebSocket | null>(null);
  const sender = useRef<((events: Command[]) => Promise<unknown>) | null>(null);
  const live = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const call = useCallback((command: Command): Promise<Reply> => api.post<Reply>('/browser', {pc: peer.pc_id, ...command}), [peer.pc_id]);
  const report = useCallback((e: unknown) => { if (live.current) setError((e as Error).message); }, []);
  useEffect(() => { document.title = windows.find(w=>w.id === window)?.title.replace(/ - Google Chrome$/, '') || `Chrome · ${peer.name}`; }, [windows, window, peer.name]);
  const refresh = useCallback(async () => {
    const r = await call({action: 'windows'});
    if (!live.current) return [];
    setWindows(r.windows ?? []);
    setWindow(current => r.windows?.some(w => w.id === current) ? current : r.windows?.[0]?.id ?? '');
    setError('');
    return r.windows ?? [];
  }, [call]);
  const openProfile = useCallback(async (chosen: string, previousWindows: NonNullable<Reply['windows']>, cancelled = () => !live.current) => {
    setBusy(true);
    try {
      const previous = new Set(previousWindows.map(w => w.id));
      await call({action: 'prepare', profile: chosen, setup: false});
      for (let i = 0; i < 8; i++) {
        if (cancelled()) return;
        const r = await call({action: 'windows'});
        if (cancelled()) return;
        setWindows(r.windows ?? []);
        const opened = r.windows?.find(w => !previous.has(w.id));
        if (opened) { setWindow(opened.id); setError(''); return; }
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      if (!cancelled() && !(await refresh()).length) throw new Error('Chrome no mostró una ventana. Volvé a intentar abrir el perfil.');
    } catch (e) { if (!cancelled()) report(e); }
    finally { if (!cancelled()) setBusy(false); }
  }, [call, refresh, report]);
  useEffect(() => {
    if (!peer.alive) return;
    let cancelled = false;
    void Promise.all([call({action: 'profiles'}), call({action: 'windows'})]).then(async ([p, w]) => {
      if (cancelled || !live.current) return;
      const available = p.profiles ?? [];
      let saved = '';
      try { saved = localStorage.getItem(`chrome-profile:${peer.pc_id}`) ?? ''; }
      catch (e) { console.warn('No se pudo leer el perfil recordado de Chrome', e); }
      const chosen = available.find(p => p.id === saved)?.id ?? available[0]?.id ?? '';
      setProfiles(available); setProfile(chosen);
      setWindows(w.windows ?? []); setWindow(w.windows?.[0]?.id ?? '');
      setError('');
      if (w.windows && !w.windows.length && chosen) await openProfile(chosen, [], () => cancelled || !live.current);
    }).catch(e => { if (!cancelled) report(e); });
    return () => { cancelled = true; };
  }, [call, peer.alive, peer.pc_id, openProfile, report]);
  const windowRef = useRef(window);
  useEffect(() => { windowRef.current = window; }, [window]);
  const openWindow = useCallback((ws: WebSocket | null) => {
    if (ws?.readyState !== WebSocket.OPEN || !windowRef.current) return;
    ws.send(JSON.stringify({t:'release'}));
    // v: 2 pide cuadros con copia de scroll y varios parches; un worker viejo lo ignora y manda v1
    ws.send(JSON.stringify({t: 'open', window: windowRef.current, v: 2, ...physicalSize(viewport.current?.getBoundingClientRect())}));
  }, []);
  // cambiar de ventana no abre otro canal ni otro worker: se le pide la nueva al mismo
  useEffect(() => { openWindow(socket.current); }, [window, openWindow]);
  useEffect(() => {
    if (!peer.alive || error) return;
    let cancelled = false;
    let attempts = 0;
    let retry: ReturnType<typeof setTimeout>;
    let resize: ReturnType<typeof setTimeout>;
    const sentAt = new Map<number, number>();
    const awaiting = new Map<number, {resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout>}>();
    let inputSequence = 0;
    let blocked = false;
    const rejectInputs = (error: Error) => {
      for (const entry of awaiting.values()) { clearTimeout(entry.timer); entry.reject(error); }
      awaiting.clear(); sentAt.clear();
    };
    const blockInputs = (error: Error) => {
      blocked = true; setInputBlocked(true);
      rejectInputs(error);
      const ws = socket.current;
      if (ws?.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({t:'release'})); }
        catch { ws.close(); } // el cierre también libera sólo las teclas/botones propios del worker
      }
    };
    let frames = 0, bytes = 0, since = performance.now();
    let drawing: Promise<void> = Promise.resolve();
    const connect = () => {
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/browser/stream?pc=${encodeURIComponent(peer.pc_id)}`);
      ws.binaryType = 'arraybuffer';
      socket.current = ws;
      let opened = false;
      ws.onopen = () => {
        opened = true;
        blocked = false; setInputBlocked(false); setInputEpoch(value => value + 1);
        openWindow(ws);
        if (document.hidden) ws.send(JSON.stringify({t: 'pause'}));
      };
      ws.onmessage = event => {
        if (cancelled || socket.current !== ws) return;
        if (typeof event.data === 'string') {
          let m: StreamMessage;
          try {
            const value: unknown = JSON.parse(event.data);
            if (!value || typeof value !== 'object' || !('t' in value) || typeof value.t !== 'string') throw new Error('Mensaje de Chrome remoto inválido');
            if ('message' in value && typeof value.message !== 'string') throw new Error('Mensaje de Chrome remoto inválido');
            if ('cursor' in value && typeof value.cursor !== 'string') throw new Error('Mensaje de Chrome remoto inválido');
            m = value as StreamMessage;
          } catch { report(new Error('Mensaje de Chrome remoto inválido')); return; }
          if (m.t === 'clipboard-ready') setCopied(true);
          else if (m.t === 'clipboard') {
            if (typeof m.text !== 'string') { setInputError('Texto copiado inválido'); return; }
            void writeClipboard(m.text).catch(e => { if (!cancelled) setInputError(`No se pudo copiar en esta PC: ${(e as Error).message}`); });
          }
          else if (m.t === 'opened') { attempts = 0; setNotice(''); setCopied(false); }
          // tiempos de la PC de allá (browser_window.Streamer._measure): dónde se va cada cuadro
          else if (m.t === 'stats' && typeof m.capture_ms === 'number' && typeof m.encode_ms === 'number') setStats(s => ({...s, remote: `captura ${Math.round(m.capture_ms!)} ms · armado ${Math.round(m.encode_ms!)} ms`}));
          else if (m.t === 'cursor' && m.cursor && ['default', 'pointer', 'text', 'wait', 'crosshair', 'nwse-resize', 'nesw-resize', 'ew-resize', 'ns-resize', 'move', 'not-allowed', 'progress', 'help'].includes(m.cursor)) setCursor(m.cursor);
          else if (m.t === 'input') {
            const entry = awaiting.get(m.n ?? -1);
            if (!entry) return;
            awaiting.delete(m.n!); clearTimeout(entry.timer); entry.resolve();
            const started = sentAt.get(m.n ?? -1);
            sentAt.delete(m.n ?? -1);
            if (started !== undefined) setStats(s => ({...s, input: Math.round(performance.now() - started)}));
          } else if (m.t === 'error') {
            if (m.input) {
              setInputError(m.message ?? '');
              if (awaiting.has(m.n ?? -1)) {
                blockInputs(new Error(m.message ?? 'La entrada remota no se confirmó'));
              }
              return;
            }
            if (m.message?.includes('ya no está disponible')) {
              // la ventana vista se cerró allá: se relee el catálogo y se abre la que quede
              void refresh().then(() => openWindow(socket.current)).catch(report);
              return;
            }
            setNotice('');
            report(new Error(m.message ?? 'Chrome remoto falló'));
          }
          return;
        }
        if (!(event.data instanceof ArrayBuffer) || event.data.byteLength <= FRAME_HEADER) {
          report(new Error('Cuadro de Chrome remoto incompleto')); return;
        }
        const data = new DataView(event.data);
        const seq = data.getUint32(0), x = data.getUint16(4), y = data.getUint16(6);
        const fullWidth = data.getUint16(12), fullHeight = data.getUint16(14), full = data.getUint8(16) & 1;
        const width = data.getUint16(8), height = data.getUint16(10);
        const v1 = !(data.getUint8(16) & FRAME_V2);  // en v2 x/y/ancho/alto van en 0: mandan los parches
        if (!fullWidth || !fullHeight || (v1 && (!width || !height || x + width > fullWidth || y + height > fullHeight))) {
          report(new Error('Dimensiones de Chrome remoto inválidas')); return;
        }
        let frame: V2Frame;
        try {
          frame = !v1 ? parseV2(event.data, fullWidth, fullHeight)
            : {scroll: null, patches: [{x, y, blob: new Blob([new Uint8Array(event.data as ArrayBuffer, FRAME_HEADER)], {type: 'image/png'})}]};
        } catch (e) { report(e); return; }
        bytes += event.data.byteLength;
        drawing = drawing.then(async () => {
          if (cancelled) return;
          // los parches se decodifican en paralelo; la copia del scroll va antes de pegarlos
          const bitmaps = await Promise.all(frame.patches.map(p => createImageBitmap(p.blob)));
          try {
            if (cancelled) return;
            if (full || canvas.width !== fullWidth || canvas.height !== fullHeight) { canvas.width = fullWidth; canvas.height = fullHeight; }
            const ctx = canvas.getContext('2d');
            const s = frame.scroll;
            // drawImage de un canvas sobre si mismo copia el origen antes de pintar: vale con solapamiento
            if (ctx && s) ctx.drawImage(canvas, s.x0, s.top - s.dy, s.x1 - s.x0, s.bottom - s.top, s.x0, s.top, s.x1 - s.x0, s.bottom - s.top);
            frame.patches.forEach((p, i) => ctx?.drawImage(bitmaps[i], p.x, p.y));
          } finally { bitmaps.forEach(b => b.close()); }
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({t: 'ack', n: seq}));
          setSize(s => s && s.width === fullWidth && s.height === fullHeight ? s : {width: fullWidth, height: fullHeight});
          frames += 1;
          const elapsed = performance.now() - since;
          if (elapsed >= 1000) {
            setStats(s => ({...s, fps: Math.round(frames * 1000 / elapsed), kbps: Math.round(bytes / elapsed)}));
            frames = 0; bytes = 0; since = performance.now();
          }
        }).catch(e => { if (!cancelled) report(e); });
      };
      ws.onclose = () => {
        if (cancelled || socket.current !== ws) return;
        blocked = true; setInputBlocked(true);
        rejectInputs(new Error('Se cerró el canal de entrada; no se reenvió'));
        socket.current = null;
        if (!opened && attempts === 0) { report(new Error('Esta PC no abrió el canal de Chrome remoto. Reiniciá Lienzo y volvé a probar.')); return; }
        if (++attempts > 5) { setNotice(''); report(new Error('Se perdió la conexión con Chrome remoto')); return; }
        setNotice('Reconectando…');
        retry = setTimeout(connect, Math.min(4000, 500 * 2 ** attempts));
      };
    };
    connect();
    // una solapa oculta no hace capturar a la otra PC: se pausa y se retoma al volver
    const visibility = () => {
      const ws = socket.current;
      if (ws?.readyState === WebSocket.OPEN) {
        if (document.hidden) ws.send(JSON.stringify({t:'release'}));
        ws.send(JSON.stringify({t: document.hidden ? 'pause' : 'resume'}));
      }
    };
    document.addEventListener('visibilitychange', visibility);
    const observer = new ResizeObserver(() => {
      clearTimeout(resize);
      resize = setTimeout(() => {
        const next = physicalSize(viewport.current?.getBoundingClientRect());
        if (next && socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({t: 'size', ...next}));
      }, 150);
    });
    if (viewport.current) observer.observe(viewport.current);
    const send = (events: Command[]) => {
      const ws = socket.current;
      if (blocked || ws?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Chrome remoto está reconectando'));
      if (awaiting.size >= 128) {
        const error = new Error('La conexión no sigue el ritmo de entrada; no se reenvió');
        blockInputs(error);
        return Promise.reject(error);
      }
      const n = ++inputSequence;
      return new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          blockInputs(new Error('La entrada remota no se confirmó; no se reenvió'));
        }, 10000);
        awaiting.set(n, {resolve, reject, timer}); sentAt.set(n, performance.now());
        try { ws.send(JSON.stringify({t: 'input', n, events})); }
        catch (error) {
          blockInputs(error instanceof Error ? error : new Error(String(error)));
        }
      });
    };
    sender.current = send;
    return () => {
      cancelled = true;
      rejectInputs(new Error('La vista se cerró; no se reenvió'));
      clearTimeout(retry); clearTimeout(resize);
      observer.disconnect();
      document.removeEventListener('visibilitychange', visibility);
      sender.current = null;
      const ws = socket.current;
      socket.current = null;
      if (ws && ws.readyState <= WebSocket.OPEN) { try { ws.send(JSON.stringify({t: 'release'})); } catch { /* ya cerrado */ } ws.close(); }
    };
  }, [peer.alive, peer.pc_id, error, canvas, refresh, report, openWindow]);
  const chooseProfile = (id: string) => {
    setProfile(id);
    try { localStorage.setItem(`chrome-profile:${peer.pc_id}`, id); }
    catch (e) { report(new Error(`No se pudo recordar el perfil: ${(e as Error).message}`)); }
  };
  const toolbar = <div className="remote-native-toolbar">
    <label>Perfil <select aria-label="Perfil del Chrome real" value={profile} onChange={e=>chooseProfile(e.target.value)}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <button disabled={busy || !peer.alive || !profile} onClick={()=>void openProfile(profile, windows)}>Abrir perfil</button>
    <label>Ventana <select aria-label="Ventana de Chrome" value={window} onChange={e=>{setWindow(e.target.value);setError('');}}>{windows.map(w=><option key={w.id} value={w.id}>{w.title}</option>)}</select></label>
    <button disabled={!peer.alive || busy} onClick={()=>void refresh().catch(report)}>Actualizar ventanas</button>
    <button aria-label="Pantalla completa" onClick={()=>{void (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(report);}}>⛶</button>
    <small aria-label="Demora de Chrome remoto">Mouse {stats.input ? `${stats.input} ms` : '—'} · Imagen {stats.fps ? `${stats.fps} cuadros/s · ${stats.kbps} kB/s` : '—'}{stats.remote && ` · ${stats.remote}`}</small>
  </div>;
  return <>{toolbarSlot && createPortal(toolbar, toolbarSlot)}<div className="remote-viewport" ref={viewport}>
    {!peer.alive ? <div className="remote-empty"><h1>{peer.name} está desconectada</h1></div>
      : error ? <div className="remote-empty" role="alert"><h1>No se pudo mostrar Chrome</h1><p>{error}</p><button onClick={()=>void refresh().catch(report)}>Reconectar</button></div>
      : !window ? <div className="remote-empty"><h1>Chrome en {peer.name}</h1><p>{busy ? 'Abriendo tu perfil de Chrome…' : 'Buscando tu ventana de Chrome…'}</p></div>
      : size ? <RemoteScreen key={window} native enabled={!inputBlocked} inputEpoch={inputEpoch} cursor={cursor} canvas={canvas} width={size.width} height={size.height}
          onRelease={()=>{if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify({t:'release'}));}}
          send={events => { const r = sender.current?.(events) ?? Promise.reject(new Error('Chrome remoto está reconectando')); setInputError(''); return r; }}
          onError={e => { if (live.current) setInputError((e as Error).message); }} onAddress={()=>{}} onCopy={()=>{
            if (socket.current?.readyState !== WebSocket.OPEN) { setInputError('Chrome remoto está reconectando'); return; }
            setInputError(''); socket.current.send(JSON.stringify({t: 'copy'}));
          }} />
      : <div className="remote-empty">Cargando ventana de Chrome…</div>}
    {inputError && <div className="remote-input-warning" role="alert">{inputError}{inputBlocked && <button onClick={()=>socket.current?.close()}>Reconectar entrada sin reenviar</button>}<button aria-label="Cerrar aviso de entrada" onClick={()=>setInputError('')}>×</button></div>}
    {notice && <div className="remote-capture-notice" role="status">{notice}</div>}
    {/* una copia hecha allá (menú contextual, botón de la página) se anuncia sin su contenido y se
        trae sólo con este clic. El texto llega después por el canal: igual que con Ctrl+C, un
        navegador que exige el gesto en el mismo instante puede negar la escritura y se avisa */}
    {copied && <div className="remote-capture-notice" role="status" style={{left: 'auto', right: 9}}>Copiaste algo en {peer.name}
      <button onClick={() => {
        setCopied(false);
        if (socket.current?.readyState !== WebSocket.OPEN) { setInputError('Chrome remoto está reconectando'); return; }
        setInputError(''); socket.current.send(JSON.stringify({t: 'pull'}));
      }}>Copiar acá</button><button aria-label="Descartar lo copiado allá" onClick={() => setCopied(false)}>×</button></div>}
  </div><div className="remote-status">{peer.name} · Chrome real · Usás el mouse y teclado de esa PC. Cerrar esta vista deja Chrome abierto.</div></>;
}

/** Canal de pestañas del HOST CDP existente. No comparte decoder ni framing con Win32. */
function useTabStream(peer: Peer, tab: string, enabled: boolean, viewport: React.RefObject<HTMLDivElement | null>, onState: (reply: Reply, tab: string) => void) {
  const [canvas] = useState(() => document.createElement('canvas'));
  const [frame, setFrame] = useState<{tab: string; generation: number; width: number; height: number} | null>(null);
  const [generation, setGeneration] = useState(0);
  const [opened, setOpened] = useState(0);
  const [connected, setConnected] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [inputError, setInputError] = useState('');
  const [hidden, setHidden] = useState('');
  const [blocked, setBlocked] = useState(false);
  const selected = useRef(tab);
  const generationCounter = useRef(0);
  const stateHandler = useRef(onState);
  const open = useRef<(() => void) | null>(null);
  const send = useRef<((events: Command[]) => Promise<unknown>) | null>(null);
  const release = useRef<(() => Promise<unknown>) | null>(null);
  const canInput = useRef(false);
  const hiddenNow = useRef(false);
  const ready = enabled && connected && generation === opened && frame?.generation === generation && !blocked;
  useEffect(() => { canInput.current = ready; }, [ready]);
  useEffect(() => { hiddenNow.current = !!hidden; }, [hidden]);
  useEffect(() => { stateHandler.current = onState; }, [onState]);
  useEffect(() => { selected.current = tab; open.current?.(); }, [tab]);
  useEffect(() => {
    if (!enabled) return;
    let disposed = false, attempts = 0, inputId = 0;
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>, resize: ReturnType<typeof setTimeout>;
    let current = 0, signature = '', lastSeq = 0, decoding = false;
    let basis: {width: number; height: number} | null = null;
    type Image = {generation: number; seq: number; width: number; height: number; jpeg: ArrayBuffer; channel: WebSocket};
    let latest: Image | null = null;
    const pending = new Map<number, {generation: number; hover: boolean; resolve: () => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout>}>();
    const uint = (v: unknown): v is number => Number.isInteger(v) && Number(v) > 0 && Number(v) <= 0xffffffff;
    const inputFailure = (message: string) => { if (!disposed) { setInputError(message); setBlocked(true); } };
    const uncertain = () => {
      if (!pending.size) return;
      const e = new Error('Entrada sin confirmación. No se reenvió; revisá la página antes de continuar.');
      inputFailure(e.message);
      for (const p of pending.values()) { clearTimeout(p.timer); p.reject(e); }
      pending.clear();
    };
    const request = (kind: 'input' | 'release-input', events?: Command[]): Promise<void> => {
      if (ws?.readyState !== WebSocket.OPEN || !current || (kind === 'input' && !canInput.current)) return Promise.reject(new Error('La entrada está pausada; no se envió el pedido.'));
      if (pending.size >= (kind === 'input' ? 32 : 64) || (events && (!events.length || events.length > 64))) return Promise.reject(new Error('Demasiadas entradas pendientes; no se envió el pedido.'));
      const n = ++inputId, gen = current, channel = ws;
      // la entrada se mapeó sobre el tamaño CSS del último cuadro dibujado: si la pestaña cambió, el host no la manda
      const message = JSON.stringify({t: kind, n, generation: gen, ...(events ? {events} : {}), ...(kind === 'input' && basis ? {basis} : {})});
      if (new TextEncoder().encode(message).length > 65536) return Promise.reject(new Error('La entrada es demasiado grande; no se envió el pedido.'));
      const result = new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(n); const e = new Error('Entrada sin confirmación. No se reenvió; revisá la página antes de continuar.');
          inputFailure(e.message); reject(e);
        }, 10000);
        const hover = kind === 'input' && !!events?.length && events.every(e => e.kind === 'mouse' && e.type === 'mouseMoved' && e.buttons === 0 && e.button === 'none');
        pending.set(n, {generation: gen, hover, resolve, reject, timer});
        try { channel.send(message); }
        catch (e) { clearTimeout(timer); pending.delete(n); inputFailure('No se confirmó la entrada; no se reenvió.'); reject(e); }
      });
      return result;
    };
    const releaseInput = () => {
      if (current && ws?.readyState === WebSocket.OPEN) void request('release-input').catch(e => inputFailure((e as Error).message));
    };
    const select = (force = false) => {
      if (disposed || ws?.readyState !== WebSocket.OPEN || !selected.current) return;
      const rect = viewport.current?.getBoundingClientRect();
      const width = clamp(rect?.width ?? 1280, 320, 1920), height = clamp(rect?.height ?? 800, 240, 1080);
      const next = `${selected.current}:${width}:${height}`;
      if (!force && signature === next) return;
      if (!force && current && signature.startsWith(`${selected.current}:`)) {
        // misma pestaña, otro tamaño de visor: sólo cambia la escala de la captura; sin open ni release
        signature = next;
        ws.send(JSON.stringify({t: 'size', generation: current, width, height}));
        return;
      }
      if (generationCounter.current === 0xffffffff) { setError('Se agotaron las generaciones del canal. Volvé a abrir la vista.'); return; }
      releaseInput(); // generación vieja antes del open; su ACK sigue correlacionado aunque cambie current
      current = ++generationCounter.current; signature = next; lastSeq = 0; latest = null; basis = null; canInput.current = false;
      setGeneration(current); setOpened(0); setError(''); setHidden(''); setNotice('Cargando pestaña…');
      ws.send(JSON.stringify({t: 'open', tab: selected.current, generation: current, width, height}));
    };
    const draw = async () => {
      if (decoding) return;
      decoding = true;
      try {
        while (latest && !disposed) {
          const image = latest; latest = null;
          try {
            const bitmap = await createImageBitmap(new Blob([image.jpeg], {type: 'image/jpeg'}));
            try {
              if (disposed || ws !== image.channel || image.generation !== current) continue;
              // el JPEG es la pestaña escalada (nunca más grande que su tamaño CSS por DPR) con la misma proporción
              const ratio = (bitmap.width / bitmap.height) / (image.width / image.height);
              if (!bitmap.width || bitmap.width > image.width * 4 || bitmap.height > image.height * 4 || Math.abs(ratio - 1) > 0.02) throw new Error('Las dimensiones JPEG no coinciden con el cuadro de Chrome');
              const context = canvas.getContext('2d');
              if (!context) throw new Error('No se pudo dibujar la pestaña de Chrome');
              if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) { canvas.width = bitmap.width; canvas.height = bitmap.height; }
              context.drawImage(bitmap, 0, 0);
              basis = {width: image.width, height: image.height};
              setFrame({tab: selected.current, generation: current, width: image.width, height: image.height});
              setNotice(''); setError(''); attempts = 0;
              if (image.channel.readyState === WebSocket.OPEN) image.channel.send(JSON.stringify({t: 'ack', generation: current, n: image.seq}));
            } finally { bitmap.close(); }
          } catch (e) {
            if (!disposed && ws === image.channel && image.generation === current) setError(`Captura detenida: ${(e as Error).message}`);
          }
        }
      } finally { decoding = false; }
    };
    const connect = () => {
      if (disposed) return;
      const channel = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/browser/stream?pc=${encodeURIComponent(peer.pc_id)}&mode=tabs`);
      channel.binaryType = 'arraybuffer'; ws = channel; signature = '';
      channel.onopen = () => {
        if (disposed || ws !== channel) return;
        setConnected(true); select(true);
        if (document.hidden) channel.send(JSON.stringify({t: 'pause'}));
      };
      channel.onmessage = event => {
        if (disposed || ws !== channel) return;
        try {
          if (typeof event.data !== 'string') {
            if (!(event.data instanceof ArrayBuffer) || event.data.byteLength <= 12 || event.data.byteLength > 12 + 4 * 1024 * 1024) throw new Error('Cuadro JPEG de Chrome inválido o demasiado grande');
            const data = new DataView(event.data);
            const gen = data.getUint32(0), seq = data.getUint32(4), width = data.getUint16(8), height = data.getUint16(10);
            if (!uint(gen) || !uint(seq) || !width || !height || width > 3840 || height > 2160) throw new Error('Cabecera de pestaña inválida');
            if (gen !== current || seq <= lastSeq) return;
            lastSeq = seq;
            latest = {generation: gen, seq, width, height, jpeg: event.data.slice(12), channel};
            void draw(); // un decoder y un único slot latest; nunca una cadena de promesas de imágenes
            return;
          }
          const m = JSON.parse(event.data);
          if (!m || typeof m !== 'object' || typeof m.t !== 'string') throw new Error('Mensaje de pestaña inválido');
          if (m.generation !== undefined && !uint(m.generation)) throw new Error('Generación de pestaña inválida');
          if (m.t === 'input' || (m.t === 'error' && m.input)) {
            if (!Number.isSafeInteger(m.n) || m.n < 1 || !uint(m.generation)) { uncertain(); throw new Error('Resultado de entrada inválido'); }
            const p = pending.get(m.n);
            if (!p || p.generation !== m.generation) return; // nunca confirma otro input; incluye release de generación anterior
            if (m.t === 'input' && m.outcome !== undefined && (m.outcome !== 'superseded' || !p.hover)) { uncertain(); throw new Error('Confirmación de reemplazo inválida'); }
            if (m.t === 'error' && (typeof m.message !== 'string' || !['rejected', 'uncertain'].includes(m.outcome))) { uncertain(); throw new Error('Resultado de entrada inválido'); }
            clearTimeout(p.timer); pending.delete(m.n);
            if (m.t === 'input') p.resolve();
            else { const e = new Error(`${m.message}. ${m.outcome === 'uncertain' ? 'Entrada sin confirmación' : 'Entrada rechazada'}; no se reenvió.`); inputFailure(e.message); p.reject(e); }
            return;
          }
          if (m.generation !== undefined && m.generation !== current) return;
          if (m.t === 'opened') {
            if (m.generation !== current || m.tab !== selected.current || m.format !== 'jpeg' || !uint(m.width) || !uint(m.height) || m.width > 3840 || m.height > 2160) throw new Error('Selección de pestaña inválida');
            setOpened(current);
          } else if (m.t === 'state') {
            if (m.generation !== current || (m.tabs !== undefined && (!Array.isArray(m.tabs) || m.tabs.some((t: Tab) => !t || typeof t.id !== 'string' || typeof t.title !== 'string' || typeof t.url !== 'string')))
              || (m.back !== undefined && typeof m.back !== 'boolean') || (m.forward !== undefined && typeof m.forward !== 'boolean')
              || ['running', 'connecting', 'autoApproving', 'prepared'].some(k => m[k] !== undefined && typeof m[k] !== 'boolean')
              || (m.connectionError !== undefined && typeof m.connectionError !== 'string')
              || (m.mode !== undefined && !['existing', 'lienzo'].includes(m.mode))
              || (m.hidden !== undefined && typeof m.hidden !== 'boolean') || (m.hiddenMessage !== undefined && typeof m.hiddenMessage !== 'string')
              || (m.dialog != null && (typeof m.dialog.type !== 'string' || typeof m.dialog.message !== 'string' || (m.dialog.defaultPrompt !== undefined && typeof m.dialog.defaultPrompt !== 'string')))) throw new Error('Estado de pestaña inválido');
            // sólo el estado periódico (tab-state) trae hidden; el de un diálogo no lo cambia
            if (m.hidden !== undefined) setHidden(m.hidden ? (m.hiddenMessage || 'Chrome no está pintando esa pestaña') : '');
            stateHandler.current(m, selected.current);
          } else if (m.t === 'error') {
            if (typeof m.message !== 'string') throw new Error('Error de captura inválido');
            setError(m.message); setNotice('Captura detenida; la entrada usa un canal independiente.');
          } else throw new Error('Mensaje de pestaña desconocido');
        } catch (e) { setError((e as Error).message); }
      };
      channel.onclose = () => {
        if (disposed || ws !== channel) return;
        // la generación era de este canal: el worker del canal nuevo no la conoce y rechazaría su release
        ws = null; signature = ''; latest = null; current = 0; basis = null; canInput.current = false; setConnected(false); setOpened(0); setHidden(''); uncertain();
        if (++attempts > 5) { setNotice('Reconexión detenida. Revisá la conexión y volvé a intentar.'); return; }
        setNotice(`Reconectando lectura (${attempts}/5)… La última imagen puede estar desactualizada.`);
        retry = setTimeout(connect, Math.min(4000, 500 * 2 ** (attempts - 1)));
      };
    };
    open.current = () => { clearTimeout(retry); if (ws?.readyState === WebSocket.OPEN) select(true); else if (!ws || ws.readyState === WebSocket.CLOSED) { attempts = 0; connect(); } };
    // pestaña oculta: Chrome no confirma la rueda y el host la rechaza; no se manda, el aviso ya lo dice
    send.current = events => {
      const sent = hiddenNow.current ? events.filter(e => !(e.kind === 'mouse' && e.type === 'mouseWheel')) : events;
      return sent.length ? request('input', sent) : Promise.resolve();
    };
    release.current = () => request('release-input');
    const visibility = () => { if (ws?.readyState === WebSocket.OPEN) { if (document.hidden) releaseInput(); ws.send(JSON.stringify({t: document.hidden ? 'pause' : 'resume'})); } };
    const observer = new ResizeObserver(() => { clearTimeout(resize); resize = setTimeout(() => select(), 150); });
    if (viewport.current) observer.observe(viewport.current);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('blur', releaseInput);
    canInput.current = false;
    connect();
    return () => {
      releaseInput();
      disposed = true; canInput.current = false; open.current = null; send.current = null; release.current = null;
      clearTimeout(retry); clearTimeout(resize); observer.disconnect(); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('blur', releaseInput);
      latest = null; uncertain();
      if (ws) { ws.onclose = null; if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({t: 'release'})); ws.close(); }
    };
  }, [enabled, peer.pc_id, viewport, canvas]);
  return {canvas, frame, ready, notice, error, inputError, hidden,
    retry: () => open.current?.(),
    allowInput: () => { setInputError(''); setBlocked(false); },
    send: (events: Command[]) => send.current?.(events) ?? Promise.reject(new Error('El canal de pestañas está cerrado; no se envió el pedido.')),
    releaseInput: () => { void release.current?.().catch(e => { setInputError((e as Error).message); setBlocked(true); }); },
    reportInput: (e: unknown) => { setInputError((e as Error).message); setBlocked(true); },
  };
}

function BrowserDesktop({peer}: {peer: Peer}) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [tab, setTab] = useState("");
  const [running, setRunning] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [autoApproving, setAutoApproving] = useState(false);
  const [mode, setMode] = useState<Reply['mode']>('existing');
  const [profiles, setProfiles] = useState<NonNullable<Reply['profiles']>>([]);
  const [profile, setProfile] = useState('');
  const [prepared, setPrepared] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readNotice, setReadNotice] = useState('');
  const [readStopped, setReadStopped] = useState(false);
  const [readEpoch, setReadEpoch] = useState(0);
  const [inputNotice, setInputNotice] = useState('');
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [frame, setFrame] = useState<Reply & {tab?: string}>({});
  const address = useRef<HTMLInputElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { document.title = `Chrome · ${peer.name} · Lienzo`; }, [peer.name]);

  const call = useCallback((command: Command, signal?: AbortSignal): Promise<Reply> => {
    const execute = () => {
      if (!mounted.current || signal?.aborted) throw new DOMException('La vista se cerró', 'AbortError');
      return api.get<Reply>('/browser', {
        method: 'POST', headers: {'X-Lienzo': '1', 'Content-Type': 'application/json'},
        body: JSON.stringify({pc: peer.pc_id, ...command}), signal,
      });
    };
    if (command.action === "frame") return Promise.resolve().then(execute); // la imagen no hace esperar al teclado
    const request = chain.current.then(execute);
    chain.current = request.catch(() => undefined); // la cola sigue; el consumidor informa cada error.
    return request;
  }, [peer.pc_id]);
  const report = useCallback((e: unknown) => {
    if (isWorkerBusy(e)) {
      if (mounted.current) setInputNotice(`${WORKER_BUSY}. El pedido no se reintentó.`);
      return;
    }
    if (mounted.current) setError(isMissingRoute(e)
      ? "Actualizá y reiniciá Lienzo en esta PC para usar Chrome remoto."
      : (e as Error).message);
  }, []);
  const reportRead = useCallback((e: unknown) => {
    if (isWorkerBusy(e)) {
      if (mounted.current) { setReadNotice('Chrome sigue ocupado. Actualizá la vista para volver a intentar.'); setReadStopped(true); }
    } else report(e);
  }, [report]);
  // Sólo estas consultas se pueden repetir. Inputs, navegación y conexión nunca pasan por acá.
  const read = useCallback(async (command: Command & {action: 'state' | 'profiles' | 'frame'}, signal: AbortSignal): Promise<Reply> => {
    for (let attempt = 0; ; attempt++) {
      try {
        const result = await call(command, signal);
        if (signal.aborted) throw new DOMException('La vista se cerró', 'AbortError');
        if (attempt > 0) { setReadNotice(''); setReadStopped(false); }
        return result;
      } catch (e) {
        if (signal.aborted || !isWorkerBusy(e) || attempt >= READ_RETRY_DELAYS.length) throw e;
        setReadNotice(`${WORKER_BUSY}. Reintentando lectura (${attempt + 1}/${READ_RETRY_DELAYS.length})…`);
        await waitForBrowserRetry(READ_RETRY_DELAYS[attempt], signal);
      }
    }
  }, [call]);
  const update = useCallback((result: Reply) => {
    if (!mounted.current) return;
    if (result.running !== undefined) setRunning(result.running);
    if (result.connecting !== undefined) setConnecting(result.connecting);
    if (result.autoApproving !== undefined) setAutoApproving(result.autoApproving);
    if (result.mode) setMode(result.mode);
    if (result.profiles) { setProfiles(result.profiles); setProfile(p => p || result.profiles?.[0]?.id || ''); }
    if (result.prepared) setPrepared(true);
    if (result.connectionError) setError(result.connectionError);
    if (result.tabs) {
      const next = result.tabs;
      setTabs(next);
      setTab(current => next.some(t => t.id === current) ? current : (next[0]?.id ?? ""));
    }
  }, []);
  const streamEnabled = peer.health?.capabilities?.includes('browser.tabs.stream.v1') === true;
  const streamState = useCallback((result: Reply, selectedTab: string) => { update(result); setFrame(previous => ({...previous, ...result, tab: selectedTab})); }, [update]);
  const stream = useTabStream(peer, tab, streamEnabled && running && !!tab && peer.alive && !error, viewport, streamState);
  useEffect(() => {
    const controller = new AbortController();
    if (peer.alive) void (async () => {
      for (const action of ['state', 'profiles'] as const) {
        const result = await read({action}, controller.signal);
        if (controller.signal.aborted) return;
        update(result);
      }
    })().catch(e => { if (!controller.signal.aborted) reportRead(e); });
    return () => controller.abort();
  }, [read, peer.alive, update, reportRead, readEpoch]);

  const action = useCallback(async (command: Command) => {
    setBusy(true);
    try {
      const r = await call(command);
      if (!mounted.current) return;
      update(r);
      if (r.id) setTab(r.id);
      setError(r.connectionError ?? "");
      setInputNotice('');
    } catch (e) { report(e); }
    finally { if (mounted.current) setBusy(false); }
  }, [call, update, report]);

  useEffect(() => {
    if (!connecting || !peer.alive) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const r = await read({action: "state"}, controller.signal); if (!controller.signal.aborted) update(r); }
      catch (e) {
        if (!controller.signal.aborted) { if (!isWorkerBusy(e)) setConnecting(false); reportRead(e); }
        return;
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1000);
    };
    timer = setTimeout(poll, 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [read, connecting, peer.alive, update, reportRead, readEpoch]);

  useEffect(() => {
    if (streamEnabled || !running || !tab || !peer.alive || error) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.hidden) { timer = setTimeout(poll, 1000); return; }
      const rect = viewport.current?.getBoundingClientRect();
      const started = performance.now();
      try {
        const r = await read({action: "frame", tab, width: clamp(rect?.width ?? 1280, 320, 1920), height: clamp(rect?.height ?? 800, 240, 1080)}, controller.signal);
        if (controller.signal.aborted) return;
        setFrame(previous => ({...previous, ...r, tab, image: r.image ?? (previous.tab === tab ? previous.image : undefined)}));
        update(r);
        // el proximo pedido sale enseguida; el minimo evita martillar una pagina quieta
        timer = setTimeout(poll, Math.max(0, 100 - (performance.now() - started)));
      } catch (e) {
        if (!controller.signal.aborted) reportRead(e);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [streamEnabled, read, running, tab, peer.alive, error, update, reportRead, readEpoch]);

  const active = tabs.find(t => t.id === tab);
  const shownUrl = active?.url === "about:blank" ? "" : (active?.url ?? "");
  const ready = running && peer.alive && !!tab && !error;
  const navigate = () => {
    const text = draft.trim();
    if (!text) { setEditing(false); return; }
    const url = /^(localhost|[\w.-]+\.\w+|\d+(?:\.\d+){3}):\d+(?:\/|$)/i.test(text) ? `http://${text}`
      : /^[a-z][a-z\d+.-]*:/i.test(text) ? text
      : /\s/.test(text) || (!text.includes(".") && !text.startsWith("localhost"))
        ? `https://www.google.com/search?q=${encodeURIComponent(text)}` : `https://${text}`;
    setEditing(false);
    void action({action: "navigate", tab, url});
    address.current?.blur();
    viewport.current?.querySelector<HTMLElement>(".remote-screen")?.focus();
  };
  const selectTab = (id: string) => {
    setTab(id); setEditing(false); setError(""); setReadNotice(''); setReadStopped(false);
    void action({action: "activate", tab: id});
  };
  return <>
    <div className="remote-tabs" role="tablist" aria-label="Pestañas remotas">
      {tabs.map(t => <div className={`remote-tab ${t.id === tab ? "selected" : ""}`} key={t.id}>
        <button role="tab" aria-selected={t.id === tab} onClick={() => selectTab(t.id)} disabled={!peer.alive || busy} title={t.url}>
          <span aria-hidden="true">◉</span><span>{t.title || "Nueva pestaña"}</span>
        </button>
        <button className="remote-close-tab" aria-label={`Cerrar ${t.title || "pestaña"}`} disabled={!peer.alive || busy} onClick={() => {
          void action({action: "close", tab: t.id}).then(() => call({action: "state"}).then(update).catch(report));
        }}>×</button>
      </div>)}
      {running && <button className="remote-new" aria-label="Nueva pestaña remota" disabled={busy || !peer.alive} onClick={() => void action({action: "new", url: "about:blank"})}>+</button>}
    </div>
    <div className="remote-toolbar">
      <button aria-label="Atrás" title="Atrás" disabled={!ready || !frame.back || busy} onClick={() => void action({action: "history", tab, direction: -1})}>←</button>
      <button aria-label="Adelante" title="Adelante" disabled={!ready || !frame.forward || busy} onClick={() => void action({action: "history", tab, direction: 1})}>→</button>
      <button aria-label="Recargar página remota" title="Recargar" disabled={!ready || busy} onClick={() => void action({action: "reload", tab})}>↻</button>
      <form onSubmit={e => { e.preventDefault(); navigate(); }}>
        <span aria-hidden="true">◎</span>
        <input ref={address} aria-label="Dirección o búsqueda" placeholder="Buscar en Google o escribir una URL" value={editing ? draft : shownUrl} disabled={!running || !tab || !peer.alive}
          onFocus={e => { setDraft(shownUrl); setEditing(true); e.target.select(); }} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Escape") { setEditing(false); e.currentTarget.blur(); } }} />
      </form>
      <button title="Pantalla completa (también podés usar F11)" aria-label="Pantalla completa" onClick={() => {
        const promise = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
        void promise.catch(report);
      }}>⛶</button>
      {running && <button className="remote-stop" disabled={busy || !peer.alive} onClick={() => void action({action: "stop"})}>{mode === 'existing' ? 'Desconectar' : 'Cerrar Chrome'}</button>}
    </div>
    <div className="remote-viewport" ref={viewport}>
      {ready && streamEnabled && stream.frame?.tab === tab && !(frame.tab === tab && frame.dialog) && <RemoteScreen key={tab} canvas={stream.canvas} stream enabled={stream.ready} inputEpoch={stream.frame.generation} onRelease={stream.releaseInput}
        width={stream.frame.width} height={stream.frame.height} send={stream.send} onError={stream.reportInput} onAddress={() => address.current?.focus()}
        onCopy={() => { void call({action: 'copy', tab}).then(r => writeClipboard(r.text ?? '')).catch(stream.reportInput); }} />}
      {ready && !streamEnabled && !frame.dialog && frame.tab === tab && frame.image && <RemoteScreen key={tab} image={frame.image} width={frame.width ?? 1280} height={frame.height ?? 800}
        send={events => call({action: "input", tab, events})} onError={report} onAddress={() => address.current?.focus()}
        onCopy={() => { void call({action: "copy", tab}).then(r => writeClipboard(r.text ?? "")).catch(report); }} />}
      {!peer.alive ? <div className="remote-empty"><h1>{peer.name} está desconectada</h1><p>{peer.diagnostico || "La PC no responde. Revisá que esté encendida y con Lienzo abierto."}</p><p>Cuando vuelva a conectarse, podés abrir Chrome desde acá.</p></div>
        : error ? <div className="remote-empty" role="alert"><h1>No se pudo conectar con Chrome</h1><p>{error}</p><button onClick={() => { setError(''); void action({action: "state"}); }} disabled={busy}>Revisar conexión</button><button onClick={() => void action({action: "stop"})} disabled={busy}>Volver a elegir</button></div>
        : connecting ? <div className="remote-empty"><h1>{autoApproving ? "Lienzo está autorizando Chrome" : "Aceptá la conexión en Chrome"}</h1><p>{autoApproving ? `El Lienzo de ${peer.name} está buscando el aviso y pulsando Permitir en esa misma PC.` : `Chrome muestra un aviso en ${peer.name}. Elegí Permitir para compartir esa sesión con Lienzo.`}</p><button onClick={() => void action({action: "stop"})} disabled={busy}>Cancelar conexión</button></div>
        : !running ? <div className="remote-empty remote-setup"><span className="remote-chrome-mark" aria-hidden="true">◉</span><h1>Chrome en {peer.name}</h1>
          <p>Usá el Chrome de esa PC con tus sesiones abiertas.</p>
          {profiles.length > 0 && <div className="remote-profile"><label>Perfil para abrir <select aria-label="Perfil de Chrome" value={profile} onChange={e => { setProfile(e.target.value); setPrepared(false); }}>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button disabled={busy} onClick={() => void action({action: 'prepare', profile})}>Abrir perfil en esa PC</button></div>}
          {prepared && <p role="status">Se pidió abrir el perfil en {peer.name}. Habilitá la conexión en la página que muestra Chrome.</p>}
          <p>En ese Chrome, habilitá <code>chrome://inspect/#remote-debugging</code>. Al conectar, aceptá su aviso.</p>
          <button className="remote-launch" disabled={busy} onClick={() => void action({action: "connect", autoApprove: true})}>Conectar Chrome abierto</button>
          <small>Chrome decide qué perfil comparte. Con varios abiertos usa su perfil predeterminado; abrir uno desde acá no cambia esa selección.</small>
          <details><summary>Usar un perfil separado de Lienzo</summary><p>Funciona sin monitor y conserva sus propios inicios de sesión.</p><button disabled={busy} onClick={() => void action({action: 'start'})}>Abrir Chrome</button></details>
        </div>
        : !tab ? <div className="remote-empty"><h1>No hay pestañas abiertas</h1><button disabled={busy} onClick={() => void action({action: "new", url: "about:blank"})}>Nueva pestaña</button></div>
        : (streamEnabled ? stream.frame?.tab !== tab : frame.tab !== tab || !frame.image) ? <div className="remote-empty">Cargando página…</div> : null}
      {ready && frame.tab === tab && frame.dialog && <BrowserDialog dialog={frame.dialog} onAnswer={(accept, text) => void action({action: "dialog", tab, accept, text})} />}
      {streamEnabled && (stream.notice || stream.error || stream.inputError || stream.hidden) && <div className="remote-capture-notice">
        {stream.hidden && <div role="alert">{stream.hidden}. La imagen sigue por capturas, más lenta, y la rueda no se envía. Elegila en la lista para traerla al frente, restaurá esa ventana o arrancá Chrome con la bandera anti-oclusión.</div>}
        {(stream.notice || stream.error) && <div role={stream.error ? 'alert' : 'status'}>{stream.error}{stream.notice && <span> {stream.notice}</span>}<button onClick={stream.retry}>Actualizar captura</button></div>}
        {stream.inputError && <div role="alert">{stream.inputError}<button onClick={stream.allowInput}>Habilitar entrada sin reenviar</button></div>}
      </div>}
      {(readNotice || inputNotice) && <div className="remote-capture-notice">
        {readNotice && <div role="status">{readNotice}{readStopped && <button onClick={() => { setReadNotice(''); setReadStopped(false); setReadEpoch(n => n + 1); }}>Actualizar vista</button>}</div>}
        {inputNotice && <div role="alert">{inputNotice}</div>}
      </div>}
    </div>
    {!streamEnabled && <small>Vista compatible por HTTP · la PC no anuncia el canal de pestañas en vivo.</small>}
    <div className="remote-status"><span className={peer.alive ? "remote-online" : ""}>●</span> {peer.name}<span>{busy ? "Procesando…" : running ? "Chrome remoto" : "Chrome cerrado"}</span><small>F11 · Pantalla completa</small></div>
  </>;
}

function BrowserDialog({dialog, onAnswer}: {dialog: NonNullable<Reply["dialog"]>; onAnswer: (accept: boolean, text: string) => void}) {
  const [text, setText] = useState(dialog.defaultPrompt ?? "");
  return <div className="remote-dialog" role="dialog" aria-label="Mensaje de la página"><div>
    <p>{dialog.message}</p>
    {dialog.type === "prompt" && <input aria-label="Respuesta a la página" value={text} onChange={e => setText(e.target.value)} />}
    <button onClick={() => onAnswer(false, "")}>Cancelar</button><button onClick={() => onAnswer(true, text)}>Aceptar</button>
  </div></div>;
}

/** Superficie con mouse y teclado. En modo nativo (`canvas`) la imagen la dibuja el dueño del canvas y
 *  cada evento sale enseguida; los movimientos se juntan por cuadro de animación. En modo pestaña
 *  (`image`) se agrupan en lotes cada 30 ms sobre HTTP. */
function RemoteScreen({image, canvas, cursor, format = 'jpeg', native = false, stream = false, enabled = true, inputEpoch, onRelease, width, height, send, onError, onAddress, onCopy}: {
  canvas?: HTMLCanvasElement;
  image?: string; cursor?: string; format?: 'png' | 'jpeg'; native?: boolean; stream?: boolean; enabled?: boolean; inputEpoch?: number; onRelease?: () => void; width: number; height: number; send: (events: Command[]) => Promise<unknown>; onError: (e: unknown) => void; onAddress: () => void; onCopy: () => void;
}) {
  const direct = native || stream;
  const element = useRef<HTMLDivElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!canvas || !holder.current) return;
    canvas.setAttribute('aria-label', stream ? 'Contenido de la pestaña remota' : 'Contenido de la ventana remota');
    holder.current.replaceChildren(canvas);
  }, [canvas, stream]);
  const pending = useRef<Command[]>([]);
  const sending = useRef(false);
  const live = useRef(false);
  const scheduled = useRef(0);
  const sender = useRef(send);
  const errorHandler = useRef(onError);
  const touch = useRef<{id: number; x: number; y: number; lastX: number; lastY: number; scrolling: boolean} | null>(null);
  const pressedButton = useRef<number | null>(null);
  useEffect(() => { if (stream || native) { pending.current = []; pressedButton.current = null; touch.current = null; } }, [stream, native, inputEpoch]);
  useEffect(() => { sender.current = send; }, [send]);
  useEffect(() => { errorHandler.current = onError; }, [onError]);
  const inFlight = useRef(0);
  const flushAgain = useRef<() => void>(() => {});
  const flush = useCallback(() => {
    scheduled.current = 0;
    if (!live.current || !pending.current.length) return;
    // control de flujo: movimientos y ruedas esperan el ACK del anterior y mientras tanto se suman;
    // teclas y clics salen enseguida (con una remota lenta, uno por cuadro agotaba las 32 pendientes)
    const coalescible = pending.current.every(e => e.type === "mouseMoved" || e.type === "mouseWheel");
    const hover = pending.current.every(e => e.kind === 'mouse' && e.type === 'mouseMoved' && e.buttons === 0 && e.button === 'none');
    if (inFlight.current && (!direct || (coalescible && (!hover || inFlight.current >= (native ? 1 : 4))))) return;
    const batch = pending.current.splice(0, 64);
    inFlight.current++; sending.current = true;
    void sender.current(batch).catch(e => { pending.current = []; errorHandler.current(e); }).finally(() => {
      inFlight.current--; sending.current = inFlight.current > 0;
      if (!inFlight.current && pending.current.length && live.current) flushAgain.current();
    });
  }, [direct, native]);
  useEffect(() => { flushAgain.current = flush; }, [flush]);
  useEffect(() => {
    live.current = true;
    const timer = direct ? undefined : setInterval(flush, 30);
    return () => { live.current = false; if (timer) clearInterval(timer); if (scheduled.current) cancelAnimationFrame(scheduled.current); pending.current = []; };
  }, [flush, direct]);
  const enqueue = (event: Command) => {
    if (!live.current || !enabled) return;
    if (pending.current.length >= 128) { pending.current = []; onError(new Error("La conexión no sigue el ritmo del teclado. Reconectá antes de continuar.")); return; }
    const last = pending.current.at(-1);
    if (event.type === "mouseMoved" && last?.type === "mouseMoved") pending.current.pop();
    // un arrastre táctil da 60-120 ruedas por segundo: se suman en una sola por cuadro, como el mouse
    if (event.type === "mouseWheel" && last?.type === "mouseWheel") {
      pending.current.pop();
      event = {...event, deltaX: clamp(Number(last.deltaX) + Number(event.deltaX), -4000, 4000), deltaY: clamp(Number(last.deltaY) + Number(event.deltaY), -4000, 4000)};
    }
    pending.current.push(event);
    if (!direct) return;
    if (event.type === "mouseMoved" || event.type === "mouseWheel") { if (!scheduled.current) scheduled.current = requestAnimationFrame(flush); }
    else flush();
  };
  const mouse = (e: React.MouseEvent, type: string, options?: {deltaX?: number; deltaY?: number; button?: number}) => {
    const box = element.current!.getBoundingClientRect();
    const scale = Math.min(box.width / width, box.height / height);
    // ventana real y pestañas por canal vivo: imagen encajada (letterbox) sobre el tamaño real
    const fit = native || stream;
    const shownWidth = fit ? width * scale : box.width;
    const shownHeight = fit ? height * scale : box.height;
    const x = e.clientX - box.left - (box.width - shownWidth) / 2;
    const y = e.clientY - box.top - (box.height - shownHeight) / 2;
    if (fit && type !== 'mouseReleased' && (x < 0 || y < 0 || x >= shownWidth || y >= shownHeight)) return;
    enqueue({kind: "mouse", type, x: clamp(x * width / shownWidth, 0, fit ? width-1 : width),
      y: clamp(y * height / shownHeight, 0, fit ? height-1 : height),
      // el arrastre táctil trae button -1: la rueda y el movimiento no llevan botón
      button: type === "mouseMoved" || type === "mouseWheel" ? "none" : ["left", "middle", "right"][options?.button ?? e.button],
      buttons: e.buttons, modifiers: modifiers(e), clickCount: clamp(e.detail, type === 'mousePressed' || type === 'mouseReleased' ? 1 : 0, 3),
      ...(type === "mouseWheel" ? {deltaX: clamp(options?.deltaX ?? (e as React.WheelEvent).deltaX, -4000, 4000), deltaY: clamp(options?.deltaY ?? (e as React.WheelEvent).deltaY, -4000, 4000)} : {}),
    });
  };
  const key = (e: React.KeyboardEvent, type: string) => {
    if (!enabled) return;
    if (e.key === "F11" || (e.ctrlKey && e.key.toLowerCase() === "v")) return;
    e.preventDefault(); e.stopPropagation();
    if (!native && e.ctrlKey && e.key.toLowerCase() === "l") { if (type === "keyDown") onAddress(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "c") { if (type === "keyDown" && !e.repeat) onCopy(); return; }
    // Teclados virtuales y herramientas de accesibilidad pueden enviar keyCode=0.
    if (native && !e.keyCode && e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      if (type === 'keyDown') enqueue({kind: 'text', text: e.key});
      return;
    }
    const special: Record<string, number> = {Control: 17, Shift: 16, Alt: 18, Enter: 13, Tab: 9, Escape: 27, Backspace: 8, Delete: 46, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, Home: 36, End: 35, PageUp: 33, PageDown: 34};
    const code = e.keyCode || special[e.key] || (/^[a-z0-9]$/i.test(e.key) ? e.key.toUpperCase().charCodeAt(0) : 0);
    if (native && !code) { if (type === 'keyDown') onError(new Error(`Tecla no admitida: ${e.key}`)); return; }
    enqueue({kind: "key", type, key: e.key, code: e.code, keyCode: code, modifiers: modifiers(e)});
  };
  return <div ref={element} className={`remote-screen${native || stream ? ' remote-screen-native' : ''}`} tabIndex={enabled ? 0 : -1} aria-disabled={!enabled || undefined} role="application" aria-label="Página remota: mouse y teclado"
    style={native ? {cursor} : undefined}
    onBlur={() => { if (stream || native) { pending.current = []; pressedButton.current = null; touch.current = null; onRelease?.(); } }}
    onKeyDown={e => key(e, "keyDown")} onKeyUp={e => key(e, "keyUp")}
    onPointerDown={e => {
      if (!enabled) return;
      e.preventDefault();
      if (!e.isPrimary) return;
      e.currentTarget.setPointerCapture(e.pointerId); e.currentTarget.focus();
      if (e.pointerType === 'touch') touch.current = {id: e.pointerId, x: e.clientX, y: e.clientY, lastX: e.clientX, lastY: e.clientY, scrolling: false};
      else { pressedButton.current = e.button; mouse(e, 'mousePressed'); }
    }}
    onPointerUp={e => {
      e.preventDefault();
      if (!e.isPrimary) return;
      if (e.pointerType === 'touch') {
        if (touch.current?.id === e.pointerId && !touch.current.scrolling) { mouse(e, 'mousePressed', {button: 0}); mouse(e, 'mouseReleased', {button: 0}); }
        touch.current = null;
      } else if (pressedButton.current !== null) { mouse(e, 'mouseReleased', {button: pressedButton.current}); pressedButton.current = null; }
      if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    }}
    onPointerCancel={e => {
      touch.current = null;
      if (pressedButton.current !== null) { mouse(e, 'mouseReleased', {button: pressedButton.current}); pressedButton.current = null; }
    }}
    onPointerMove={e => {
      if (e.pointerType !== 'touch') { mouse(e, 'mouseMoved'); return; }
      const gesture = touch.current;
      if (!gesture || gesture.id !== e.pointerId) return;
      if (Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y) > 8) gesture.scrolling = true;
      if (gesture.scrolling) mouse(e, 'mouseWheel', {deltaX: gesture.lastX - e.clientX, deltaY: gesture.lastY - e.clientY});
      gesture.lastX = e.clientX; gesture.lastY = e.clientY;
    }}
    onWheel={e => mouse(e, "mouseWheel")} onContextMenu={e => e.preventDefault()}
    onPaste={e => {
      e.preventDefault();
      const text = e.clipboardData.getData("text/plain");
      if (!native) { enqueue({kind: "text", text}); return; }
      // ventana real: el texto pasa al portapapeles de allá y Chrome recibe Ctrl+V (browser_window.paste)
      if (!text) { onError(new Error('Sólo se pega texto, y el portapapeles no tenía')); return; }
      if (text.length > PASTE_MAX_CHARS || new TextEncoder().encode(JSON.stringify(text)).length > PASTE_MAX_BYTES) {
        onError(new Error(`El texto pegado supera ${PASTE_MAX_CHARS.toLocaleString('es-AR')} caracteres; no se pegó`)); return;
      }
      enqueue({kind: "paste", text});
    }}>
    {canvas ? <div ref={holder} className="remote-canvas-holder" /> : <img src={`data:image/${format};base64,${image}`} alt="Contenido de la pestaña remota" draggable={false} />}
  </div>;
}
