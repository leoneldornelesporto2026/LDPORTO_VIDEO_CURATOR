"""Opt-in cleanup of explicitly regenerable media; editorial artifacts are protected."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import uuid


def _pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        code = wintypes.DWORD()
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        try:
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def media_in_use(path):
    path = Path(path).resolve()
    for marker in path.parent.glob('.ldporto_media_use_*.json'):
        try:
            row = json.loads(marker.read_text(encoding='utf-8'))
            if row.get('path') == str(path) and _pid_alive(int(row['pid'])):
                return True
        except (OSError, ValueError, KeyError):
            continue
    return False


@contextmanager
def media_lease(path):
    path = Path(path).resolve()
    marker = path.parent / ('.ldporto_media_use_' + uuid.uuid4().hex + '.json')
    marker.write_text(json.dumps({'path':str(path), 'pid':os.getpid(), 'started_at':time.time()}), encoding='utf-8')
    try:
        yield
    finally:
        marker.unlink(missing_ok=True)


def _removable(path, root, source):
    lock = root/'RUNNING.lock'
    if lock.is_file():
        try:
            if _pid_alive(int(lock.read_text(encoding='utf-8').strip())):
                return False
        except (OSError, ValueError):
            return False
    if not path.is_file() or path.is_symlink() or media_in_use(path):
        return False
    actual = path.resolve()
    if 'final' in actual.stem.lower().split('_') or any(part.lower() in {'renders', 'final_renders'} for part in actual.parts):
        return False
    if source and actual == source:
        return actual.suffix.lower() in {'.mp4', '.mkv', '.mov', '.webm'}
    if not actual.is_relative_to(root):
        return False
    rel = actual.relative_to(root)
    return (rel.parts[0] == 'audio' and actual.suffix.lower() == '.wav'
            or rel.parts[0] in {'temporary_frames', 'render_staging'} and actual.suffix.lower() in {'.png', '.wav', '.tmp'}
            or rel.parts[0] == '.cache' and actual.suffix.lower() in {'.npz', '.npy', '.pkl'})


def cleanup_preview(root, source=None, include_source=False):
    root = Path(root).resolve(strict=True)
    source = Path(source).resolve(strict=True) if source and include_source else None
    paths = [p for p in root.rglob('*') if p.is_file()]
    if source and source not in paths:
        paths.append(source)
    removable, total = [], 0
    for path in paths:
        size = path.stat().st_size
        total += size
        if _removable(path, root, source):
            removable.append({'path':str(path.resolve()), 'bytes':size, 'mtime_ns':path.stat().st_mtime_ns})
    reclaimable = sum(row['bytes'] for row in removable)
    return {'schema_version':'4.4.0', 'root':str(root), 'optional_source':str(source) if source else None,
            'current_bytes':total, 'reclaimable_bytes':reclaimable, 'preserved_bytes':total-reclaimable,
            'requires_confirmation':True, 'removable':removable,
            'protected':'JSON, transcript, words, SRT, candidates, camera, contact sheets, reports, packages and final renders'}


def execute_cleanup(preview, confirmed=False):
    if confirmed is not True:
        raise ValueError('Confirme o preview da limpeza antes de remover arquivos')
    root = Path(preview['root']).resolve(strict=True)
    source = Path(preview['optional_source']).resolve() if preview.get('optional_source') else None
    removed, skipped = [], []
    for row in preview['removable']:
        path = Path(row['path'])
        try:
            stat = path.stat()
            if stat.st_size != row['bytes'] or stat.st_mtime_ns != row['mtime_ns'] or not _removable(path, root, source):
                skipped.append(row['path'])
                continue
            path.unlink()
            removed.append(row)
        except OSError:
            skipped.append(row['path'])
    return {'removed_bytes':sum(r['bytes'] for r in removed), 'removed':removed, 'skipped':skipped}
