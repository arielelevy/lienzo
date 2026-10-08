import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, isMissingRoute } from "../api";
import type { Peer } from "../types";
import { usePeers } from "./PcStrip";
import "../remote-browser.css";

type Tab = { id: string; title: string; url: string };
type Reply = {
  windows?: {id: string; title: string}[]; format?: 'png' | 'jpeg';
  profiles?: {id: string; name: string}[]; prepared?: boolean;
  connecting?: boolean; connectionError?: string; mode?: 'existing' | 'lienzo';
  running?: boolean; tabs?: Tab[]; id?: string; image?: string; width?: number; height?: number;
  back?: boolean; forward?: boolean; text?: string; dialog?: {type: string; message: string; defaultPrompt?: string} | null;
};
type Command = Record<string, unknown>;
const modifiers = (e: {altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean}) =>
  Number(e.altKey) + Number(e.ctrlKey) * 2 + Number(e.metaKey) * 4 + Number(e.shiftKey) * 8;
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(n)));

export function RemoteBrowser() {
  const peers = usePeers();
  const [native, setNative] = useState(true);
  const [controls, setControls] = useState(false);
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
    {native && <button className="remote-controls-toggle" aria-label="Controles de Chrome remoto" aria-expanded={controls} onClick={()=>setControls(!controls)}>⋮</button>}
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
    {peer ? <ChromeMode key={peer.pc_id} peer={peer} native={native} setNative={setNative} /> : <div className="remote-empty">No se encuentra la PC. Revisá la conexión desde el tablero.</div>}
  </main>;
}

function ChromeMode({peer, native, setNative}: {peer: Peer; native: boolean; setNative: (value: boolean)=>void}) {
  return <><div className="remote-mode"><button aria-pressed={native} onClick={() => setNative(true)}>Chrome real · ventana completa</button><button aria-pressed={!native} onClick={() => setNative(false)}>Vista por pestañas</button></div>{native ? <ChromeWindow peer={peer} /> : <BrowserDesktop peer={peer} />}</>;
}

function ChromeWindow({peer}: {peer: Peer}) {
  const [windows, setWindows] = useState<NonNullable<Reply['windows']>>([]);
  const [window, setWindow] = useState('');
  const [profiles, setProfiles] = useState<NonNullable<Reply['profiles']>>([]);
  const [profile, setProfile] = useState('');
  const [frame, setFrame] = useState<Reply & {window?: string}>({});
  const [error, setError] = useState('');
  const [inputError, setInputError] = useState('');
  const [latency, setLatency] = useState({frame: 0, input: 0});
  const [captureNotice, setCaptureNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const live = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => () => { void api.post('/browser', {pc: peer.pc_id, action: 'window-release'}).catch(e => console.error('No se pudo liberar el teclado remoto', e)); }, [peer.pc_id]);
  const call = useCallback((command: Command): Promise<Reply> => {
    const started = performance.now();
    const execute = async () => {
      if (!live.current) throw new Error('La vista se cerró');
      const result = await api.post<Reply>('/browser', {pc: peer.pc_id, ...command});
      if (live.current && (command.action === 'window-frame' || command.action === 'window-input')) {
        const field = command.action === 'window-frame' ? 'frame' : 'input';
        setLatency(current=>({...current,[field]:Math.round(performance.now()-started)}));
      }
      return result;
    };
    if (command.action === 'window-frame') return execute();
    const request = chain.current.then(execute);
    chain.current = request.catch(() => undefined);
    return request;
  }, [peer.pc_id]);
  const report = useCallback((e: unknown) => { if (live.current) setError((e as Error).message); }, []);
  const reportInput = useCallback((e: unknown) => { if (live.current) setInputError((e as Error).message); }, []);
  useEffect(() => { document.title = windows.find(w=>w.id === window)?.title.replace(/ - Google Chrome$/, '') || `Chrome · ${peer.name}`; }, [windows, window, peer.name]);
  const refresh = useCallback(async () => {
    const r = await call({action: 'windows'});
    if (!live.current) return;
    setWindows(r.windows ?? []);
    setWindow(current => r.windows?.some(w => w.id === current) ? current : r.windows?.[0]?.id ?? '');
    setError('');
  }, [call]);
  useEffect(() => {
    if (!peer.alive) return;
    void refresh().catch(report);
    void call({action: 'profiles'}).then(r => {
      if (live.current) { setProfiles(r.profiles ?? []); setProfile(r.profiles?.[0]?.id ?? ''); }
    }).catch(report);
  }, [call, peer.alive, refresh, report]);
  useEffect(() => {
    if (!window || !peer.alive || error) return;
    let cancelled = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.hidden) { timer = setTimeout(poll, 1000); return; }
      try {
        const box = viewport.current?.getBoundingClientRect();
        const scale = box ? Math.min(globalThis.devicePixelRatio || 1, 3840 / box.width, 2160 / box.height) : 1;
        const r = await call({action: 'window-frame', window,
          ...(box && box.width >= 320 && box.height >= 200 ? {width: Math.round(box.width * scale), height: Math.round(box.height * scale)} : {})});
        if (!cancelled) { failures = 0; setCaptureNotice(''); setFrame({...r, window}); timer = setTimeout(poll, 80); }
      } catch (e) {
        if (cancelled) return;
        const message = (e as Error).message;
        if (message.includes('Esa ventana de Chrome ya no está disponible') || message.includes('Chrome está cerrado.')) {
          try { await refresh(); if (!cancelled) timer = setTimeout(poll, 500); }
          catch (refreshError) { if (!cancelled) report(refreshError); }
        } else if ((e instanceof TypeError || (e instanceof ApiError && (e.status >= 500 || e.status === 409))) && ++failures <= 3) {
          setCaptureNotice('Reconectando la imagen…');
          timer = setTimeout(poll, failures * 500);
        } else { setCaptureNotice(''); report(e); }
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [call, window, peer.alive, error, report, refresh]);
  const open = async () => {
    setBusy(true);
    try {
      const previous = new Set(windows.map(w=>w.id));
      await call({action: 'prepare', profile, setup: false});
      for (let i=0; i<8; i++) {
        const r = await call({action: 'windows'});
        if (!live.current) return;
        setWindows(r.windows ?? []);
        const opened = r.windows?.find(w=>!previous.has(w.id));
        if (opened) { setWindow(opened.id); setError(''); return; }
        await new Promise(resolve=>setTimeout(resolve, 500));
      }
      await refresh();
    }
    catch (e) { report(e); }
    finally { if (live.current) setBusy(false); }
  };
  return <><div className="remote-native-toolbar">
    <label>Perfil <select aria-label="Perfil del Chrome real" value={profile} onChange={e=>setProfile(e.target.value)}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <button disabled={busy || !peer.alive || !profile} onClick={()=>void open()}>Abrir perfil</button>
    <label>Ventana <select aria-label="Ventana de Chrome" value={window} onChange={e=>{setWindow(e.target.value);setError('');}}>{windows.map(w=><option key={w.id} value={w.id}>{w.title}</option>)}</select></label>
    <button disabled={!peer.alive || busy} onClick={()=>void refresh().catch(report)}>Actualizar ventanas</button>
    <button aria-label="Pantalla completa" onClick={()=>{void (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(report);}}>⛶</button>
    <small aria-label="Demora de Chrome remoto">Mouse {latency.input ? `${latency.input} ms` : '—'} · Imagen {latency.frame ? `${latency.frame} ms` : '—'}</small>
  </div><div className="remote-viewport" ref={viewport}>
    {!peer.alive ? <div className="remote-empty"><h1>{peer.name} está desconectada</h1></div>
      : error ? <div className="remote-empty" role="alert"><h1>No se pudo mostrar Chrome</h1><p>{error}</p><button onClick={()=>void refresh().catch(report)}>Reconectar</button></div>
      : !window ? <div className="remote-empty"><h1>Chrome en {peer.name}</h1><p>Elegí tu perfil y tocá Abrir perfil. Acá vas a ver la ventana completa, con sus pestañas, menús y avisos.</p></div>
      : frame.window === window && frame.image ? <RemoteScreen key={window} native image={frame.image} format={frame.format} width={frame.width ?? 1280} height={frame.height ?? 800} send={async events=>{const r=await call({action:'window-input',window,events});setInputError('');return r;}} onError={reportInput} onAddress={()=>{}} onCopy={()=>{}} />
      : <div className="remote-empty">Cargando ventana de Chrome…</div>}
    {inputError && <div className="remote-input-warning" role="alert">{inputError}<button aria-label="Cerrar aviso de entrada" onClick={()=>setInputError('')}>×</button></div>}
    {captureNotice && <div className="remote-capture-notice" role="status">{captureNotice}</div>}
  </div><div className="remote-status">{peer.name} · Chrome real · Usás el mouse y teclado de esa PC. Cerrar esta vista deja Chrome abierto.</div></>;
}

function BrowserDesktop({peer}: {peer: Peer}) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [tab, setTab] = useState("");
  const [running, setRunning] = useState(false);
  const [connecting, setConnecting] = useState(false);
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
    const request = chain.current.then(() => {
      if (!mounted.current) throw new Error("La vista se cerró");
      return api.post<Reply>("/browser", {pc: peer.pc_id, ...command});
    });
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
      try {
        const r = await call({action: "frame", tab, width: clamp(rect?.width ?? 1280, 320, 1920), height: clamp(rect?.height ?? 800, 240, 1080)});
        if (cancelled) return;
        setFrame(previous => ({...previous, ...r, tab, image: r.image ?? (previous.tab === tab ? previous.image : undefined)}));
        update(r);
        timer = setTimeout(poll, 220);
      } catch (e) { if (!cancelled) report(e); }
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
        : connecting ? <div className="remote-empty"><h1>Aceptá la conexión en Chrome</h1><p>Chrome muestra un aviso en {peer.name}. Elegí Permitir para compartir esa sesión con Lienzo.</p><button onClick={() => void action({action: "stop"})} disabled={busy}>Cancelar conexión</button></div>
        : !running ? <div className="remote-empty remote-setup"><span className="remote-chrome-mark" aria-hidden="true">◉</span><h1>Chrome en {peer.name}</h1>
          <p>Usá el Chrome de esa PC con tus sesiones abiertas.</p>
          {profiles.length > 0 && <div className="remote-profile"><label>Perfil para abrir <select aria-label="Perfil de Chrome" value={profile} onChange={e => { setProfile(e.target.value); setPrepared(false); }}>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button disabled={busy} onClick={() => void action({action: 'prepare', profile})}>Abrir perfil en esa PC</button></div>}
          {prepared && <p role="status">Se pidió abrir el perfil en {peer.name}. Habilitá la conexión en la página que muestra Chrome.</p>}
          <p>En ese Chrome, habilitá <code>chrome://inspect/#remote-debugging</code>. Al conectar, aceptá su aviso.</p>
          <button className="remote-launch" disabled={busy} onClick={() => void action({action: "connect"})}>Conectar Chrome abierto</button>
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

function RemoteScreen({image, format = 'jpeg', native = false, width, height, send, onError, onAddress, onCopy}: {
  image: string; format?: 'png' | 'jpeg'; native?: boolean; width: number; height: number; send: (events: Command[]) => Promise<unknown>; onError: (e: unknown) => void; onAddress: () => void; onCopy: () => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const pending = useRef<Command[]>([]);
  const sending = useRef(false);
  const live = useRef(false);
  const sender = useRef(send);
  useEffect(() => { sender.current = send; }, [send]);
  useEffect(() => {
    live.current = true;
    const timer = setInterval(() => {
      if (sending.current || !pending.current.length) return;
      const batch = pending.current.splice(0, 64);
      sending.current = true;
      void sender.current(batch).catch(e => { pending.current = []; onError(e); }).finally(() => { sending.current = false; });
    }, native ? 8 : 30);
    return () => { live.current = false; clearInterval(timer); pending.current = []; };
  }, [onError, native]);
  const enqueue = (event: Command) => {
    if (!live.current) return;
    if (pending.current.length >= 128) { pending.current = []; onError(new Error("La conexión no sigue el ritmo del teclado. Reconectá antes de continuar.")); return; }
    if (event.type === "mouseMoved" && pending.current.at(-1)?.type === "mouseMoved") pending.current.pop();
    pending.current.push(event);
  };
  const mouse = (e: React.MouseEvent, type: string) => {
    const box = element.current!.getBoundingClientRect();
    const scale = Math.min(box.width / width, box.height / height);
    const shownWidth = native ? width * scale : box.width;
    const shownHeight = native ? height * scale : box.height;
    const x = e.clientX - box.left - (box.width - shownWidth) / 2;
    const y = e.clientY - box.top - (box.height - shownHeight) / 2;
    if (native && type !== 'mouseReleased' && (x < 0 || y < 0 || x >= shownWidth || y >= shownHeight)) return;
    enqueue({kind: "mouse", type, x: clamp(x * width / shownWidth, 0, native ? width-1 : width),
      y: clamp(y * height / shownHeight, 0, native ? height-1 : height),
      button: type === "mouseMoved" ? "none" : ["left", "middle", "right"][e.button],
      buttons: e.buttons, modifiers: modifiers(e), clickCount: clamp(e.detail, 0, 3),
      ...(type === "mouseWheel" ? {deltaX: clamp((e as React.WheelEvent).deltaX, -4000, 4000), deltaY: clamp((e as React.WheelEvent).deltaY, -4000, 4000)} : {}),
    });
  };
  const key = (e: React.KeyboardEvent, type: string) => {
    if (e.key === "F11" || (e.ctrlKey && e.key.toLowerCase() === "v")) return;
    e.preventDefault(); e.stopPropagation();
    if (!native && e.ctrlKey && e.key.toLowerCase() === "l") { if (type === "keyDown") onAddress(); return; }
    if (!native && e.ctrlKey && e.key.toLowerCase() === "c") { if (type === "keyDown") onCopy(); return; }
    enqueue({kind: "key", type, key: e.key, code: e.code, keyCode: e.keyCode, modifiers: modifiers(e)});
  };
  return <div ref={element} className={`remote-screen${native ? ' remote-screen-native' : ''}`} tabIndex={0} role="application" aria-label="Página remota: mouse y teclado"
    onKeyDown={e => key(e, "keyDown")} onKeyUp={e => key(e, "keyUp")}
    onPointerDown={e => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); e.currentTarget.focus(); mouse(e, "mousePressed"); }}
    onPointerUp={e => { e.preventDefault(); mouse(e, "mouseReleased"); e.currentTarget.releasePointerCapture(e.pointerId); }} onPointerMove={e => mouse(e, "mouseMoved")}
    onWheel={e => mouse(e, "mouseWheel")} onContextMenu={e => e.preventDefault()}
    onPaste={e => { e.preventDefault(); enqueue({kind: "text", text: e.clipboardData.getData("text/plain")}); }}>
    <img src={`data:image/${format};base64,${image}`} alt="Contenido de la pestaña remota" draggable={false} />
  </div>;
}
