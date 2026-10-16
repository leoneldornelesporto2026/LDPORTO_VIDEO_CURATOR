"""Package only the audited caption update; never package user media or caches."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def reject_links(path):
    """Windows junctions and symlinks must never redirect packaged content."""
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        raise ValueError(f'Links/junctions não permitidos no pacote: {path}')


def validate_tree(path):
    reject_links(path)
    for child in Path(path).rglob('*'):
        reject_links(child)


def workspace_path(path, label):
    """Check lexical ancestors before resolving so links cannot hide themselves."""
    path = Path(os.path.abspath(path))
    workspace = ROOT.resolve()
    if not path.is_relative_to(workspace):
        raise ValueError(f'{label} deve permanecer dentro do projeto: {path}')
    for node in (path, *path.parents):
        reject_links(node)
        if node == workspace:
            break
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f'{label} fora do projeto: {path}')
    return resolved


def copy_verified(source, target):
    """Freeze the bytes that were actually copied, refusing concurrent edits."""
    expected = sha(source)
    shutil.copy2(source, target)
    copied = sha(target)
    if copied != expected or sha(source) != expected:
        raise RuntimeError(f'Arquivo mudou durante a cópia do pacote: {source}')
    return copied


def build(destination, evidence=None):
    destination = workspace_path(destination, 'Destino do pacote')
    workspace = ROOT.resolve()
    for folder in ('ldporto_curator', 'tests', 'scripts', 'output', '.cache', '.venv', 'source_cache', '.git'):
        if destination.is_relative_to(workspace / folder):
            raise ValueError(f'Destino do pacote não pode modificar código ou dados protegidos: {destination}')
    archive = destination.parent / 'UPDATE_LEGENDAS_STORIES_P0.zip'
    if archive.exists() or archive.with_suffix('.zip.sha256').exists():
        raise FileExistsError(archive)
    if evidence is not None:
        evidence = workspace_path(evidence, 'Evidência')
        if not evidence.is_relative_to(workspace / 'docs/reports') or not evidence.is_dir():
            raise ValueError('A evidência deve ser uma pasta existente em docs/reports')
        if destination.is_relative_to(evidence) or evidence.is_relative_to(destination):
            raise ValueError('Pasta do pacote e pasta de evidência não podem se sobrepor')
        validate_tree(evidence)
    source_files = []
    for folder in ('ldporto_curator', 'tests', 'scripts'):
        validate_tree(ROOT / folder)
        source_files.extend(file for file in sorted((ROOT / folder).rglob('*'))
                            if file.is_file() and '__pycache__' not in file.parts
                            and file.suffix in {'.py', '.json', '.jsonl', '.ps1'})
    for name in ('README.md', 'docs/architecture/LEGENDAS_WORD_ALIGNED.md'):
        file = workspace_path(ROOT / name, 'Documentação da atualização')
        if not file.is_file():
            raise FileNotFoundError(file)
        source_files.append(file)
    if (ROOT / 'pytest.ini').is_file():
        source_files.append(workspace_path(ROOT / 'pytest.ini', 'Configuração de testes'))
    baseline = json.loads((ROOT / 'docs/reports/organizacao_20261015/inventory_before.json').read_text(encoding='utf-8'))
    before = {row['path']: row.get('sha256') for row in baseline['files']}
    destination.mkdir(parents=True, exist_ok=False)
    selected = []
    for file in source_files:
        name = file.relative_to(ROOT).as_posix()
        if sha(file) == before.get(name):
            continue
        target = destination / 'payload' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        copied_hash = copy_verified(file, target)
        selected.append({'path': name, 'sha256': copied_hash, 'before_sha256': before.get(name), 'bytes': target.stat().st_size})
    manifest = {'schema': 'LDP_CAPTION_PATCH_V1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'baseline': 'ETAPA00_20261015', 'files': selected,
                'preserved': ['output', '.cache', '.venv', 'source_cache', 'config.yaml', 'approvals', 'original_media'],
                'approval_granted': False, 'automatic_batch_render': False}
    (destination / 'UPDATE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    copy_verified(ROOT / 'scripts/INSTALL_CAPTIONS_P0.ps1', destination / 'INSTALL_CAPTIONS_P0.ps1')
    if evidence is not None:
        shutil.copytree(evidence, destination / 'evidence', symlinks=True,
                        ignore=shutil.ignore_patterns('UPDATE_*.zip', 'update_package'))
        validate_tree(destination / 'evidence')
    for filename in ('ORGANIZACAO_PROJETO.md',):
        copy_verified(ROOT / 'docs/reports' / filename, destination / filename)
    (destination / 'LEIA_PRIMEIRO.txt').write_text(
        'L.D.PORTO — correção de legendas P0\n\n'
        'Feche o Curator antes de atualizar. Extraia este ZIP em uma pasta separada.\n'
        'Confira o SHA256 do ZIP no arquivo SHA256 fornecido ao lado dele.\n'
        'Verificar sem alterações:\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File .\\INSTALL_CAPTIONS_P0.ps1 -TargetRoot "C:\\caminho\\LDPORTO_VIDEO_CURATOR" -VerifyOnly\n'
        'Instalar: mesmo comando sem -VerifyOnly. Os hashes do baseline devem coincidir.\n'
        'Se o código já estiver atualizado, o instalador apenas confere os hashes.\n'
        'Rollback: use -Rollback "backups/captions_p0_<id>/TRANSACTION.json" com o mesmo -TargetRoot.\n'
        'O rollback recusa arquivos editados depois da instalação. Backups são preservados.\n'
        'Nenhuma mídia, cache, configuração local ou aprovação é instalada ou removida.\n'
        'O pacote contém pendências de revisão humana; não concede aprovação/publicação.\n', encoding='utf-8')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(destination).as_posix())
    archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n', encoding='ascii')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    print(build(args.destination, args.evidence))
