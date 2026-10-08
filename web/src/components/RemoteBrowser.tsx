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
type StreamMessage = { t: string; n?: number; message?: string; input?: boolean; cursor?: string; window?: string; windows?: {id: string; title: string}[] };
const FRAME_HEADER = 17; // >IHHHHHHB: seq, x, y, ancho, alto, ancho total, alto total, flags
const modifiers = (e: {altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean}) =>
  Number(e.altKey) + Number(e.ctrlKey) * 2 + Number(e.metaKey) * 4 + Number(e.shiftKey) * 8;
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(n)));

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
  const [stats, setStats] = useState({input: 0, fps: 0, kbps: 0});
  const [notice, setNotice] = useState('');
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
    ws.send(JSON.stringify({t: 'open', window: windowRef.current, ...physicalSize(viewport.current?.getBoundingClientRect())}));
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
    let frames = 0, bytes = 0, since = performance.now();
    let drawing: Promise<void> = Promise.resolve();
    const connect = () => {
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/browser/stream?pc=${encodeURIComponent(peer.pc_id)}`);
      ws.binaryType = 'arraybuffer';
      socket.current = ws;
      let opened = false;
      ws.onopen = () => {
        opened = true;
        openWindow(ws);
        if (document.hidden) ws.send(JSON.stringify({t: 'pause'}));
      };
      ws.onmessage = event => {
        if (cancelled) return;
        if (typeof event.data === 'string') {
          const m = JSON.parse(event.data) as StreamMessage;
          if (m.t === 'opened') { attempts = 0; setNotice(''); }
          else if (m.t === 'cursor' && m.cursor && ['default', 'pointer', 'text', 'wait', 'crosshair', 'nwse-resize', 'nesw-resize', 'ew-resize', 'ns-resize', 'move', 'not-allowed', 'progress', 'help'].includes(m.cursor)) setCursor(m.cursor);
          else if (m.t === 'input') {
            const started = sentAt.get(m.n ?? -1);
            sentAt.delete(m.n ?? -1);
            if (started !== undefined) setStats(s => ({...s, input: Math.round(performance.now() - started)}));
          } else if (m.t === 'error') {
            if (m.input) { setInputError(m.message ?? ''); return; }
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
        const data = new DataView(event.data as ArrayBuffer);
        const seq = data.getUint32(0), x = data.getUint16(4), y = data.getUint16(6);
        const fullWidth = data.getUint16(12), fullHeight = data.getUint16(14), full = data.getUint8(16) & 1;
        const blob = new Blob([new Uint8Array(event.data as ArrayBuffer, FRAME_HEADER)], {type: 'image/png'});
        bytes += blob.size;
        drawing = drawing.then(async () => {
          const bitmap = await createImageBitmap(blob);
          if (cancelled) return;
          if (full || canvas.width !== fullWidth || canvas.height !== fullHeight) { canvas.width = fullWidth; canvas.height = fullHeight; }
          canvas.getContext('2d')?.drawImage(bitmap, x, y);
          bitmap.close();
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
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({t: document.hidden ? 'pause' : 'resume'}));
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
      if (ws?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Chrome remoto está reconectando'));
      const n = sentAt.size ? Math.max(...sentAt.keys()) + 1 : 1;
      sentAt.set(n, performance.now());
      if (sentAt.size > 200) sentAt.delete(Math.min(...sentAt.keys()));
      ws.send(JSON.stringify({t: 'input', n, events}));
      return Promise.resolve();
    };
    sender.current = send;
    return () => {
      cancelled = true;
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
    <small aria-label="Demora de Chrome remoto">Mouse {stats.input ? `${stats.input} ms` : '—'} · Imagen {stats.fps ? `${stats.fps} cuadros/s · ${stats.kbps} kB/s` : '—'}</small>
  </div>;
  return <>{toolbarSlot && createPortal(toolbar, toolbarSlot)}<div className="remote-viewport" ref={viewport}>
    {!peer.alive ? <div className="remote-empty"><h1>{peer.name} está desconectada</h1></div>
      : error ? <div className="remote-empty" role="alert"><h1>No se pudo mostrar Chrome</h1><p>{error}</p><button onClick={()=>void refresh().catch(report)}>Reconectar</button></div>
      : !window ? <div className="remote-empty"><h1>Chrome en {peer.name}</h1><p>{busy ? 'Abriendo tu perfil de Chrome…' : 'Buscando tu ventana de Chrome…'}</p></div>
      : size ? <RemoteScreen key={window} native cursor={cursor} canvas={canvas} width={size.width} height={size.height}
          send={events => { const r = sender.current?.(events) ?? Promise.reject(new Error('Chrome remoto está reconectando')); setInputError(''); return r; }}
          onError={e => { if (live.current) setInputError((e as Error).message); }} onAddress={()=>{}} onCopy={()=>{}} />
      : <div className="remote-empty">Cargando ventana de Chrome…</div>}
    {inputError && <div className="remote-input-warning" role="alert">{inputError}<button aria-label="Cerrar aviso de entrada" onClick={()=>setInputError('')}>×</button></div>}
    {notice && <div className="remote-capture-notice" role="status">{notice}</div>}
  </div><div className="remote-status">{peer.name} · Chrome real · Usás el mouse y teclado de esa PC. Cerrar esta vista deja Chrome abierto.</div></>;
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
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [frame, setFrame] = useState<Reply & {tab?: string}>({});
  const address = useRef<HTMLInputElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { document.title = `Chrome · ${peer.name} · Lienzo`; }, [peer.name]);

  const call = useCallback((command: Command): Promise<Reply> => {
    const execute = () => {
      if (!mounted.current) throw new Error("La vista se cerró");
      return api.post<Reply>("/browser", {pc: peer.pc_id, ...command});
    };
    if (command.action === "frame") return Promise.resolve().then(execute); // la imagen no hace esperar al teclado
    const request = chain.current.then(execute);
    chain.current = request.catch(() => undefined); // la cola sigue; el consumidor informa cada error.
    return request;
  }, [peer.pc_id]);
  const report = useCallback((e: unknown) => {
    if (mounted.current) setError(isMissingRoute(e)
      ? "Actualizá y reiniciá Lienzo en esta PC para usar Chrome remoto."
      : (e as Error).message);
  }, []);
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
  useEffect(() => {
    let cancelled = false;
    if (peer.alive) call({action: "state"}).then(r => { if (!cancelled) update(r); }).catch(e => { if (!cancelled) report(e); });
    if (peer.alive) call({action: "profiles"}).then(r => { if (!cancelled) update(r); }).catch(e => { if (!cancelled) report(e); });
    return () => { cancelled = true; };
  }, [call, peer.alive, update, report]);

  const action = useCallback(async (command: Command) => {
    setBusy(true);
    try {
      const r = await call(command);
      if (!mounted.current) return;
      update(r);
      if (r.id) setTab(r.id);
      setError(r.connectionError ?? "");
    } catch (e) { report(e); }
    finally { if (mounted.current) setBusy(false); }
  }, [call, update, report]);

  useEffect(() => {
    if (!connecting || !peer.alive) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const r = await call({action: "state"}); if (!cancelled) update(r); }
      catch (e) { if (!cancelled) { setConnecting(false); report(e); } }
      if (!cancelled) timer = setTimeout(poll, 1000);
    };
    timer = setTimeout(poll, 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [call, connecting, peer.alive, update, report]);

  useEffect(() => {
    if (!running || !tab || !peer.alive || error) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.hidden) { timer = setTimeout(poll, 1000); return; }
      const rect = viewport.current?.getBoundingClientRect();
      const started = performance.now();
      try {
        const r = await call({action: "frame", tab, width: clamp(rect?.width ?? 1280, 320, 1920), height: clamp(rect?.height ?? 800, 240, 1080)});
        if (cancelled) return;
        setFrame(previous => ({...previous, ...r, tab, image: r.image ?? (previous.tab === tab ? previous.image : undefined)}));
        update(r);
        // el proximo pedido sale enseguida; el minimo evita martillar una pagina quieta
        timer = setTimeout(poll, Math.max(0, 100 - (performance.now() - started)));
      } catch (e) {
        if (cancelled) return;
        // 409: el worker está ocupado con un comando largo (pegado, diálogo); la imagen espera, no falla
        if (e instanceof ApiError && e.status === 409) timer = setTimeout(poll, 300);
        else report(e);
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [call, running, tab, peer.alive, error, update, report]);

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
    setTab(id); setEditing(false); setError("");
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
      {ready && !frame.dialog && frame.tab === tab && frame.image && <RemoteScreen key={tab} image={frame.image} width={frame.width ?? 1280} height={frame.height ?? 800}
        send={events => call({action: "input", tab, events})} onError={report} onAddress={() => address.current?.focus()}
        onCopy={() => { void call({action: "copy", tab}).then(r => navigator.clipboard.writeText(r.text ?? "")).catch(report); }} />}
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
        : frame.tab !== tab || !frame.image ? <div className="remote-empty">Cargando página…</div> : null}
      {ready && frame.tab === tab && frame.dialog && <BrowserDialog dialog={frame.dialog} onAnswer={(accept, text) => void action({action: "dialog", tab, accept, text})} />}
    </div>
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
function RemoteScreen({image, canvas, cursor, format = 'jpeg', native = false, width, height, send, onError, onAddress, onCopy}: {
  canvas?: HTMLCanvasElement;
  image?: string; cursor?: string; format?: 'png' | 'jpeg'; native?: boolean; width: number; height: number; send: (events: Command[]) => Promise<unknown>; onError: (e: unknown) => void; onAddress: () => void; onCopy: () => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!canvas || !holder.current) return;
    canvas.setAttribute('aria-label', 'Contenido de la ventana remota');
    holder.current.replaceChildren(canvas);
  }, [canvas]);
  const pending = useRef<Command[]>([]);
  const sending = useRef(false);
  const live = useRef(false);
  const scheduled = useRef(0);
  const sender = useRef(send);
  const errorHandler = useRef(onError);
  const touch = useRef<{id: number; x: number; y: number; lastX: number; lastY: number; scrolling: boolean} | null>(null);
  const pressedButton = useRef<number | null>(null);
  useEffect(() => { sender.current = send; }, [send]);
  useEffect(() => { errorHandler.current = onError; }, [onError]);
  const flush = useCallback(() => {
    scheduled.current = 0;
    if (!live.current || !pending.current.length || (!native && sending.current)) return;
    const batch = pending.current.splice(0, 64);
    sending.current = true;
    void sender.current(batch).catch(e => { pending.current = []; errorHandler.current(e); }).finally(() => { sending.current = false; });
  }, [native]);
  useEffect(() => {
    live.current = true;
    const timer = native ? undefined : setInterval(flush, 30);
    return () => { live.current = false; if (timer) clearInterval(timer); if (scheduled.current) cancelAnimationFrame(scheduled.current); pending.current = []; };
  }, [flush, native]);
  const enqueue = (event: Command) => {
    if (!live.current) return;
    if (pending.current.length >= 128) { pending.current = []; onError(new Error("La conexión no sigue el ritmo del teclado. Reconectá antes de continuar.")); return; }
    if (event.type === "mouseMoved" && pending.current.at(-1)?.type === "mouseMoved") pending.current.pop();
    pending.current.push(event);
    if (!native) return;
    if (event.type === "mouseMoved") { if (!scheduled.current) scheduled.current = requestAnimationFrame(flush); }
    else flush();
  };
  const mouse = (e: React.MouseEvent, type: string, options?: {deltaX?: number; deltaY?: number; button?: number}) => {
    const box = element.current!.getBoundingClientRect();
    const scale = Math.min(box.width / width, box.height / height);
    const shownWidth = native ? width * scale : box.width;
    const shownHeight = native ? height * scale : box.height;
    const x = e.clientX - box.left - (box.width - shownWidth) / 2;
    const y = e.clientY - box.top - (box.height - shownHeight) / 2;
    if (native && type !== 'mouseReleased' && (x < 0 || y < 0 || x >= shownWidth || y >= shownHeight)) return;
    enqueue({kind: "mouse", type, x: clamp(x * width / shownWidth, 0, native ? width-1 : width),
      y: clamp(y * height / shownHeight, 0, native ? height-1 : height),
      button: type === "mouseMoved" ? "none" : ["left", "middle", "right"][options?.button ?? e.button],
      buttons: e.buttons, modifiers: modifiers(e), clickCount: clamp(e.detail, type === 'mousePressed' || type === 'mouseReleased' ? 1 : 0, 3),
      ...(type === "mouseWheel" ? {deltaX: clamp(options?.deltaX ?? (e as React.WheelEvent).deltaX, -4000, 4000), deltaY: clamp(options?.deltaY ?? (e as React.WheelEvent).deltaY, -4000, 4000)} : {}),
    });
  };
  const key = (e: React.KeyboardEvent, type: string) => {
    if (e.key === "F11" || (e.ctrlKey && e.key.toLowerCase() === "v")) return;
    e.preventDefault(); e.stopPropagation();
    if (!native && e.ctrlKey && e.key.toLowerCase() === "l") { if (type === "keyDown") onAddress(); return; }
    if (!native && e.ctrlKey && e.key.toLowerCase() === "c") { if (type === "keyDown") onCopy(); return; }
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
  return <div ref={element} className={`remote-screen${native ? ' remote-screen-native' : ''}`} tabIndex={0} role="application" aria-label="Página remota: mouse y teclado"
    style={native ? {cursor} : undefined}
    onKeyDown={e => key(e, "keyDown")} onKeyUp={e => key(e, "keyUp")}
    onPointerDown={e => {
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
    onPaste={e => { e.preventDefault(); enqueue({kind: "text", text: e.clipboardData.getData("text/plain")}); }}>
    {canvas ? <div ref={holder} className="remote-canvas-holder" /> : <img src={`data:image/${format};base64,${image}`} alt="Contenido de la pestaña remota" draggable={false} />}
  </div>;
}
