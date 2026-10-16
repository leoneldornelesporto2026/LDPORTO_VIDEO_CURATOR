"""Opt-in cleanup of registered scratch files; existing user data stays intact."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import uuid


CLEANUP_MANIFEST = '.ldporto_temporary_files.json'
CLEANUP_POLICY = 'registered_scratch_only_v1'
_PROTECTED_DIRS = frozenset({
    'output', '.cache', 'source_cache', '.venv', 'backups', 'backup',
    'projects', 'projetos', 'revisions', 'revisoes', 'editing_history',
    'approvals', 'renders', 'final_renders', 'evidence', 'evidencias',
    'analysis', 'analyzer', 'source', 'originals', 'original_media',
    'docs', '.git',
})
_ARTIFACT_MARKERS = (
    'series_index.json', 'EDIT_DECISIONS.json', 'APPROVAL.json',
    'FIRST_TEST_APPROVED.flag', 'source_manifest.json',
    'SECOND_CURATION_MANIFEST.json', 'analysis.json', 'completion.json',
)
_LOCKS = ('RUNNING.lock', '.PLAN_OPERATION.lock', '.PLAN_STATE.lock')
_SCRATCH_EXTENSIONS = frozenset({'.png', '.wav', '.tmp'})


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True  # An unknown owner is never presumed dead.
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
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
            if not isinstance(row, dict) or not isinstance(row.get('path'), str):
                return True
            if row.get('path') == str(path) and _pid_alive(row.get('pid')):
                return True
        except (OSError, ValueError):
            return True  # Interrupted lease metadata cannot authorize cleanup.
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


def _is_link(path):
    info = Path(path).lstat()
    return Path(path).is_symlink() or bool(getattr(info, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _without_links(path):
    """Check lexical ancestors before resolve can conceal a Windows junction."""
    path = Path(os.path.abspath(path))
    for node in (path, *path.parents):
        if _is_link(node):
            raise ValueError(f'Links/junctions preservados: {node}')
    return path.resolve(strict=True)


def _sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _registrations(root):
    """A folder name is not proof that its contents can be regenerated.

    No legacy files are auto-registered. A future scratch-file producer must
    record the exact relative path, bytes and SHA256 of its own generated file.
    Invalid or interrupted manifests fail closed without changing any file.
    """
    path = root / CLEANUP_MANIFEST
    try:
        _without_links(path)
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('schema') != 'LDP_GENERATED_SCRATCH_V1':
            return {}, None
        rows = {}
        for row in document['files']:
            name = row['path']
            rel = PurePosixPath(name)
            if (rel.is_absolute() or '\\' in name or ':' in name or '..' in rel.parts
                    or rel.as_posix() != name or len(rel.parts) < 2
                    or rel.parts[0] not in {'temporary_frames', 'render_staging'}
                    or rel.suffix.lower() not in _SCRATCH_EXTENSIONS
                    or name.casefold() in rows
                    or row.get('purpose') != 'regenerable_scratch'
                    or not isinstance(row.get('bytes'), int) or isinstance(row['bytes'], bool)
                    or row['bytes'] < 0 or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
                return {}, None
            rows[name.casefold()] = row
        return rows, _sha256(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}, None


def _protected_reason(path, root):
    try:
        actual = _without_links(path)
        if not actual.is_file() or not actual.is_relative_to(root):
            return 'outside_root_or_not_regular_file'
        if any(part.casefold() in _PROTECTED_DIRS or part.casefold().startswith('backup_')
                for part in actual.parts[:-1]):
            return 'protected_directory'
        relative = actual.relative_to(root)
        if (len(relative.parts) < 2 or relative.parts[0] not in {'temporary_frames', 'render_staging'}
                or actual.suffix.lower() not in _SCRATCH_EXTENSIONS):
            return 'unproven_or_persistent_artifact'
        # Protect projects and Analyzer evidence even outside their usual roots.
        for directory in (actual.parent, *actual.parent.parents):
            if any((directory / name).exists() for name in _ARTIFACT_MARKERS):
                return 'project_or_analyzer_evidence'
            # Even a stale/unknown lock is not cleanup authorization.
            if any((directory / name).exists() for name in _LOCKS):
                return 'operation_lock_present'
        if media_in_use(actual):
            return 'media_in_use'
    except (OSError, ValueError):
        return 'unreadable_or_redirected_path'
    return None


def _removable(path, root, source=None, registrations=None):
    if _protected_reason(path, root):
        return False
    actual = Path(path).resolve()
    if source and actual == Path(source).resolve():
        return False
    if registrations is None:
        registrations, _ = _registrations(root)
    row = registrations.get(actual.relative_to(root).as_posix().casefold())
    return bool(row and actual.stat().st_size == row['bytes'] and _sha256(actual) == row['sha256'])


def _files_without_links(root):
    files, skipped = [], []
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(directory) / name
            if _is_link(path):
                directories.remove(name)
                skipped.append(str(path))
        for name in names:
            path = Path(directory) / name
            if _is_link(path):
                skipped.append(str(path))
            elif path.is_file():
                files.append(path)
    return files, skipped


def cleanup_preview(root, source=None, include_source=False):
    root = _without_links(root)
    if not root.is_dir():
        raise ValueError('A pasta de preview deve ser um diretório existente')
    # Kept for API compatibility; selecting a source never authorizes its removal.
    source = Path(source).resolve() if source else None
    paths, skipped_links = _files_without_links(root)
    registrations, manifest_sha256 = _registrations(root)
    removable, preserved_candidates, total = [], [], 0
    for path in paths:
        info = path.stat()
        size = info.st_size
        total += size
        if _removable(path, root, source, registrations):
            removable.append({'path':str(path.resolve()), 'bytes':size,
                'mtime_ns':info.st_mtime_ns, 'sha256':_sha256(path)})
        elif path.suffix.lower() in {'.png', '.wav', '.tmp', '.npz', '.npy', '.pkl'}:
            preserved_candidates.append({'path':str(path), 'bytes':size,
                'reason':_protected_reason(path, root) or 'no_matching_scratch_registration'})
    reclaimable = sum(row['bytes'] for row in removable)
    return {'schema_version':'4.4.0', 'root':str(root), 'optional_source':str(source) if source else None,
            'current_bytes':total, 'reclaimable_bytes':reclaimable, 'preserved_bytes':total-reclaimable,
            'requires_confirmation':True, 'removable':removable,
            'policy':CLEANUP_POLICY, 'registration_manifest_sha256':manifest_sha256,
            'source_removal_disabled':True, 'preserved_candidates':preserved_candidates,
            'skipped_links':skipped_links,
            'protected':'output, caches, originals, projects, revisions, approvals, manifests, backups, Analyzer evidence and all unregistered files'}


def execute_cleanup(preview, confirmed=False):
    if confirmed is not True:
        raise ValueError('Confirme o preview da limpeza antes de remover arquivos')
    if preview.get('policy') != CLEANUP_POLICY:
        raise ValueError('Preview antigo ou inválido; gere um novo preview protegido')
    root = _without_links(preview['root'])
    source = Path(preview['optional_source']).resolve() if preview.get('optional_source') else None
    registrations, manifest_sha256 = _registrations(root)
    if manifest_sha256 != preview.get('registration_manifest_sha256'):
        return {'removed_bytes':0, 'removed':[], 'skipped':[row['path'] for row in preview['removable']]}
    removed, skipped = [], []
    for row in preview['removable']:
        path = Path(row['path'])
        try:
            stat = path.stat()
            if (stat.st_size != row['bytes'] or stat.st_mtime_ns != row['mtime_ns']
                    or not _removable(path, root, source, registrations)
                    or _sha256(path) != row.get('sha256')):
                skipped.append(row['path'])
                continue
            path.unlink()
            removed.append(row)
        except (OSError, ValueError):
            skipped.append(row['path'])
    return {'removed_bytes':sum(r['bytes'] for r in removed), 'removed':removed, 'skipped':skipped}
