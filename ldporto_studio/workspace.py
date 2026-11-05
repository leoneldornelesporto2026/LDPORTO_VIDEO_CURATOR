"""Keep all generated projects, videos and editorial exports under the application output/.

Legacy external projects may be COPIED in safely; the source is never deleted.
The R57 input ZIP and the Analyzer provenance SHA are never rewritten.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
from uuid import uuid4

from .core import Project, atomic_write, read_json, now, sha256_file


def application_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def project_output_root() -> Path:
    return application_root() / 'output' / 'projects'


def import_existing_project(source_directory, destination_root=None) -> Path:
    """Copy an existing Studio project into output/projects with safe path rebasing.

    Existing downloads, previews, finals and reviews remain intact.
    A name collision is an error; never overwrite a destination or delete the source.
    """
    src = Path(source_directory).expanduser().resolve()
    original = Project(src)  # Validates immutable input before any copy.
    root = Path(destination_root or project_output_root()).expanduser().resolve()
    dest = root / src.name
    if root == src or root.is_relative_to(src) or src.is_relative_to(root):
        raise ValueError('Origem e destino se sobrepõem; operação cancelada')
    if dest.exists():
        raise FileExistsError('Projeto já existe em output/projects; abra-o, sem sobrescrever: ' + str(dest))
    if any(p.is_symlink() for p in src.rglob('*')):
        raise ValueError('O projeto contém links simbólicos; faça a migração manualmente')
    root.mkdir(parents=True, exist_ok=True)
    staging = root / ('.importing-' + src.name + '-' + uuid4().hex[:10])
    staging.mkdir(parents=False, exist_ok=False)
    completed = False
    try:
        # Merge only into newly created staging, never overwrite another project.
        shutil.copytree(src, staging, dirs_exist_ok=True, copy_function=shutil.copy2)

        def mapped(raw):
            if not raw or not isinstance(raw, str):
                return raw
            p = Path(raw).expanduser()
            if not p.is_absolute():
                return raw
            resolved = p.resolve()
            if resolved.is_relative_to(src):
                return str(dest / resolved.relative_to(src))
            return raw

        state = read_json(staging / 'project.json')
        if not isinstance(state, dict):
            raise ValueError('project.json inválido na cópia')
        state['media_path'] = mapped(state.get('media_path'))
        for row in state.get('download_history', []):
            if isinstance(row, dict):
                row['path'] = mapped(row.get('path'))
        association = state.get('source_association')
        if isinstance(association, dict):
            association['download_report'] = mapped(association.get('download_report'))
        state.setdefault('history', []).append({
            'at': now(), 'event': 'COPIED_TO_PROJECT_OUTPUT', 'original': str(src),
            'note': 'Origem preservada; aprovações e SHA256 não foram alterados',
        })
        atomic_write(staging / 'project.json', state)

        # Receipt equality is required to use a reviewed YouTube download.
        for report_file in staging.glob('downloads/attempts/*/download_report.json'):
            data = read_json(report_file)
            if isinstance(data, dict):
                data['path'] = mapped(data.get('path'))
                atomic_write(report_file, data)

        # Copy and source data are still separate. Check copied bytes before cutover.
        archive = staging / 'input' / 'curadoria.zip'
        if sha256_file(archive) != original.package.digest:
            raise ValueError('A cópia da curadoria ZIP divergiu do original')
        if state.get('media_path'):
            internal_media = Path(state['media_path'])
            if internal_media.is_relative_to(dest):
                copied_media = staging / internal_media.relative_to(dest)
                if not copied_media.is_file():
                    raise ValueError('Cópia do vídeo não localizada em output')
                expected_sha = state.get('media_sha256') or original.package.source_sha
                if sha256_file(copied_media) != expected_sha:
                    raise ValueError('Cópia do vídeo alterada durante a migração')
        staging.rename(dest)
        completed = True
        restored = Project(dest)
        if restored.state.get('media_path'):
            restored.verified_media()
        return dest
    finally:
        if not completed and staging.exists():
            shutil.rmtree(staging)
