"""Build a camera-only session delta; never collect media, caches or histories."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'docs/reports/camera_final_20261015/code_before.json'
FORBIDDEN = {'output', '.cache', '.venv', '.git', 'source', 'source_cache',
             'backups', 'backup_before', 'history', 'historico', 'revisions',
             'approvals', 'original_media', '__pycache__'}


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def reject_links(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        raise ValueError(f'Links/junctions nao permitidos: {path}')


def workspace_path(path):
    root = Path(os.path.abspath(ROOT))
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise ValueError(f'Caminho fora do projeto: {path}')
    # Check lexical ancestors before resolving, including ancestors of ROOT.
    for node in (path, *path.parents):
        reject_links(node)
    return path


def allowed_path(name):
    """Same conservative portable path contract enforced by the installer."""
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        return False
    parts = name.split('/')
    if any(not part or part in {'.', '..'} or part[-1] in ' .' or
           re.search(r'[\x00-\x1f<>"|?*]', part) or
           re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', part, re.I) or
           part.lower() in FORBIDDEN for part in parts):
        return False
    if name in {'README.md', 'pytest.ini'}:
        return True
    if re.fullmatch(r'(?:ldporto_curator|scripts)/.+\.(?:py|ps1)', name):
        return True
    if re.fullmatch(r'tests/.+\.(?:py|json|jsonl)', name):
        return True
    return bool(re.fullmatch(r'docs/(?:architecture|development|reports)/.+\.md', name))


def copy_verified(source, target):
    expected = sha(source)
    shutil.copy2(source, target)
    if sha(target) != expected or sha(source) != expected:
        raise RuntimeError(f'Arquivo mudou durante a copia: {source}')
    return expected


def build(destination, baseline=None, documentation=()):
    root = workspace_path(ROOT)
    destination = workspace_path(destination)
    if not destination.is_relative_to(root / 'docs/reports') or any(
            part.lower() in FORBIDDEN for part in destination.relative_to(root).parts):
        raise ValueError('Destino deve ser uma pasta nova e separada em docs/reports')
    baseline_path = workspace_path(baseline or root / BASELINE)
    if destination.is_relative_to(baseline_path.parent) or baseline_path.is_relative_to(destination):
        raise ValueError('Pacote nao pode se sobrepor a evidencia/baseline da sessao')
    baseline_bytes = baseline_path.read_bytes()
    baseline_doc = json.loads(baseline_bytes)
    before = {}
    for row in baseline_doc['files']:
        name, checksum = row['path'], row['sha256']
        if name.lower() in before or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('Baseline com caminho duplicado ou SHA256 invalido')
        before[name.lower()] = checksum
    candidates = []
    for folder in ('ldporto_curator', 'scripts', 'tests'):
        base = workspace_path(root / folder)
        # os.walk does not follow directory links; reject them before traversal.
        for directory, children, filenames in os.walk(base, followlinks=False):
            for name in children + filenames:
                reject_links(Path(directory) / name)
            children[:] = sorted(name for name in children if name.lower() not in FORBIDDEN)
            candidates.extend(Path(directory) / name for name in sorted(filenames)
                              if allowed_path((Path(directory) / name).relative_to(root).as_posix()))
    candidates.extend(root / name for name in ('README.md', 'pytest.ini') if (root / name).is_file())
    # Documentation is opt-in: older reports cannot become a session delta merely
    # because the code-only baseline did not inventory them.
    for supplied in documentation:
        path = workspace_path(supplied if Path(supplied).is_absolute() else root / supplied)
        name = path.relative_to(root).as_posix()
        if not name.startswith('docs/') or not allowed_path(name) or not path.is_file():
            raise ValueError(f'Documentacao fora da allowlist: {name}')
        candidates.append(path)
    selected_sources = []
    seen = set()
    for source in sorted(candidates):
        name = source.relative_to(root).as_posix()
        if name.lower() in seen:
            raise ValueError(f'Caminho duplicado: {name}')
        seen.add(name.lower())
        if sha(source) != before.get(name.lower()):
            selected_sources.append((source, name))
    archive = destination.parent / 'UPDATE_CAMERA_FINAL.zip'
    if destination.exists() or archive.exists() or archive.with_suffix('.zip.sha256').exists():
        raise FileExistsError('Destino/ZIP/SHA256 ja existe; preserve o pacote anterior')
    # All path/scope validation above is read-only.
    destination.mkdir(parents=True)
    selected = []
    for source, name in selected_sources:
        target = destination / 'payload' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        selected.append({'path': name, 'sha256': copy_verified(source, target),
                         'before_sha256': before.get(name.lower()), 'bytes': target.stat().st_size})
    if baseline_path.read_bytes() != baseline_bytes:
        raise RuntimeError('Baseline mudou durante o empacotamento')
    manifest = {'schema': 'LDP_CAMERA_PATCH_V1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'baseline': baseline_path.relative_to(root).as_posix(),
                'baseline_sha256': hashlib.sha256(baseline_bytes).hexdigest(), 'files': selected,
                'approval_granted': False, 'automatic_batch_render': False,
                'preserved': sorted(FORBIDDEN - {'__pycache__'}) + ['config.yaml']}
    (destination / 'UPDATE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    copy_verified(workspace_path(root / 'scripts/INSTALL_CAMERA_FINAL.ps1'), destination / 'INSTALL_CAMERA_FINAL.ps1')
    (destination / 'LEIA_PRIMEIRO.txt').write_text(
        'L.D.PORTO - refinamento incremental de camera\n\n'
        'Feche o Curator. Extraia o ZIP em uma pasta separada e confira o SHA256 externo.\n'
        'Verificar: powershell -NoProfile -ExecutionPolicy Bypass -File .\\INSTALL_CAMERA_FINAL.ps1 '
        '-TargetRoot "C:\\caminho\\LDPORTO_VIDEO_CURATOR" -VerifyOnly\n'
        'Instalar: mesmo comando sem -VerifyOnly. Versoes locais divergentes sao recusadas.\n'
        'Rollback: acrescente -Rollback "backups/camera_final_<id>/TRANSACTION.json".\n'
        'Use rollback tambem apos interrupcao; o journal reconhece arquivos antes/depois.\n'
        'Rollback interrompido pode ser repetido. Edicoes locais posteriores sao preservadas por recusa.\n'
        'Backups e journal sao preservados. Nao instala midia, cache, configuracao ou aprovacoes.\n'
        'Nao executa analise, renderizacao, aprovacao editorial ou publicacao.\n', encoding='utf-8')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(destination.rglob('*')):
            reject_links(path)
            if path.is_file():
                package.write(path, path.relative_to(destination).as_posix())
    archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n', encoding='ascii')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--document', type=Path, action='append', default=[])
    args = parser.parse_args()
    print(build(args.destination, args.baseline, args.document))
