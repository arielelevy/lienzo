"""Diagnóstico del rollout abierto; no acredita el hilo visible de la TUI.

Un resultado sólo vale para la consulta actual. No guardar como prueba de hilo activo.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import uuid

import procinfo


class _Handle(ctypes.Structure):
    _fields_ = [
        ("object", ctypes.c_void_p),
        ("pid", ctypes.c_size_t),
        ("handle", ctypes.c_size_t),
        ("access", wt.ULONG),
        ("trace", wt.USHORT),
        ("type", wt.USHORT),
        ("attributes", wt.ULONG),
        ("reserved", wt.ULONG),
    ]


def _handles(pid):
    import msvcrt

    with open(__file__, "rb") as reference:
        return _file_handles(pid, msvcrt.get_osfhandle(reference.fileno()))


def _file_handles(pid, reference):
    """SystemExtendedHandleInformation; crecimiento acotado, sin inspeccionar otros PID."""
    size = 1024 * 1024
    while size <= 64 * 1024 * 1024:
        buf = ctypes.create_string_buffer(size)
        needed = wt.ULONG()
        status = procinfo._nt.NtQuerySystemInformation(64, buf, size, ctypes.byref(needed))
        if status == 0:
            count = ctypes.c_size_t.from_buffer(buf).value
            offset = 2 * ctypes.sizeof(ctypes.c_size_t)
            if offset + count * ctypes.sizeof(_Handle) > size:
                raise OSError("tabla de handles incompleta")
            rows = (_Handle * count).from_buffer(buf, offset)
            types = {row.type for row in rows if row.pid == os.getpid() and row.handle == reference}
            if len(types) != 1:
                raise OSError("no se pudo identificar el tipo File")
            file_type = types.pop()
            return [row.handle for row in rows if row.pid == pid and row.type == file_type]
        if status & 0xFFFFFFFF != 0xC0000004:
            raise OSError(f"NtQuerySystemInformation: {status & 0xFFFFFFFF:#x}")
        size = max(size * 2, needed.value)
    raise OSError("tabla de handles excede 64 MiB")


def _snapshot(pid, *, observation=False):
    k32 = procinfo._k32
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.DuplicateHandle.argtypes = [
        wt.HANDLE,
        wt.HANDLE,
        wt.HANDLE,
        ctypes.POINTER(wt.HANDLE),
        wt.DWORD,
        wt.BOOL,
        wt.DWORD,
    ]
    k32.GetFileType.argtypes = [wt.HANDLE]
    k32.GetFinalPathNameByHandleW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD]
    k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
    h = procinfo.open_process(pid, 0x0040 | procinfo.PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        raise OSError("no se pudo abrir el proceso")
    try:
        times = [wt.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
            raise OSError("no se pudo medir la creación del proceso")
        start = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        paths = set()
        for source in _handles(pid):
            copied = wt.HANDLE()
            if not k32.DuplicateHandle(h, source, k32.GetCurrentProcess(), ctypes.byref(copied), 0, False, 2):
                if observation:
                    continue  # A partial inventory can locate a transcript, never authorize sending.
                raise OSError("no se pudo duplicar un handle: snapshot incompleto")
            try:
                if k32.GetFileType(copied) != 1:  # sólo disco; nunca consultar pipes
                    continue
                buf = ctypes.create_unicode_buffer(32768)
                length = k32.GetFinalPathNameByHandleW(copied, buf, len(buf), 0)
                if not 0 < length < len(buf):
                    if observation:
                        continue
                    raise OSError("no se pudo resolver un handle de disco: snapshot incompleto")
                path = buf.value
                if os.path.basename(path).startswith("rollout-") and path.endswith(".jsonl"):
                    paths.add(path)
            finally:
                procinfo.close_handle(copied)
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != procinfo.STILL_ACTIVE:
            raise OSError("el proceso terminó durante la consulta")
        return start, paths
    finally:
        procinfo.close_handle(h)


def _probe(pid: int, *, observation=False) -> dict:
    """Rechaza identidad incierta aunque un rollout siga abierto tras /new o /clear."""
    no = lambda reason: {"verified": False, "reason": reason}
    if not procinfo._WIN:
        return no("identidad por handles no disponible fuera de Windows")
    if procinfo.process_agent(pid) != "codex":
        return no("el proceso no es una TUI Codex verificable")
    try:
        start, paths = _snapshot(pid, observation=True) if observation else _snapshot(pid)
        if len(paths) != 1:
            return no(f"se observaron {len(paths)} rollouts abiertos: identidad incierta")
        path = next(iter(paths))
        with open(path, encoding="utf-8") as fh:
            row = json.loads(fh.readline(65536))
        payload = row.get("payload")
        if row.get("type") != "session_meta" or not isinstance(payload, dict):
            return no("cabecera del rollout inválida")
        if payload.get("originator") not in ("codex-tui", "codex_cli_rs"):
            return no("rollout abierto sin origen TUI comprobado")
        thread = payload.get("id")
        if not isinstance(thread, str) or not thread:
            return no("rollout sin id de hilo")
        try:
            canonical_thread = str(uuid.UUID(thread))
        except ValueError:
            return no("rollout con id de hilo inválido")
        if canonical_thread != thread:
            return no("rollout con id de hilo inválido")
        # La lectura de la cabecera puede coincidir con /new, /clear o la salida del proceso.
        # Una segunda observación debe conservar la misma incarnación y el único rollout.
        current_start, current_paths = _snapshot(pid, observation=True) if observation else _snapshot(pid)
        if current_start != start or current_paths != paths:
            return no("identidad Codex cambió durante la lectura del rollout")
        if observation:
            return {
                "verified": False,
                "observed": True,
                "pid": pid,
                "process_start": start,
                "thread": thread,
                "path": path,
                "reason": "transcripción observada por handles del proceso; el hilo visible de la TUI sigue sin verificar",
            }
        # Repro real 2026-10-17: /new conservó el handle del hilo anterior.
        # queue lo aceptó y ejecutó un turno oculto; ni un ACK ni dos snapshots
        # estables acreditan que ese hilo siga visible. No hay aquí un vínculo
        # autoritativo TUI/hilo ni una operación atómica de envío condicionada a él.
        return no(
            "rollout abierto estable, pero sin prueba del hilo visible de la TUI; "
            "/new o /clear pueden conservar el hilo anterior; envío CLI deshabilitado"
        )
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        return no(f"no se pudo verificar identidad Codex: {exc}")


def probe(pid: int) -> dict:
    """Authorization probe: an observed transcript is never sufficient."""
    return _probe(pid)


def transcript_identity(pid: int) -> dict:
    """Read-only discovery, also usable when unrelated handles cannot be copied."""
    proof = probe(pid)
    if proof["verified"]:
        return proof
    observed = _probe(pid, observation=True)
    if observed.get("observed"):
        return observed
    import codex_observation
    import codex_status

    return codex_observation.observe(pid) or codex_status.discover(pid) or proof
