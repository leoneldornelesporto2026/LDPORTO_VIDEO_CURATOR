"""Consolidate verified R6 cover/ASR draft bytes into an editable R57 asset staging area.

No inference, content fabrication, approvals, ZIP creation or media rendering.
Incomplete captions remain NULL in the R57 asset binding JSON. Every copied
file is tied to a verified Analyzer ZIP, Reel selection and Story proposal.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import tempfile

from .core import fingerprint, json_bytes, sha256_bytes, sha256_file
from .r6_asset_bindings import _verify_asset, asset_template
from .r6_caption_drafts import prepare_caption_drafts
from .r6_cover_drafts import _validate_exported as validate_cover_export
from .workspace import application_root

SCHEMA = 'ldporto-r6-asset-staging-1.0'
MAX_FILE_COUNT = 360
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
BINDINGS_NAME = 'R6_ASSET_BINDINGS_DRAFT.json'
MANIFEST_NAME = 'R6_ASSET_STAGING_MANIFEST.json'


def _safe_file(path):
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError('Arquivo de rascunho ausente ou é link')
    if getattr(path.lstat(), 'st_file_attributes', 0) & getattr(
            stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
        raise ValueError('Reparse point proibido')
    return path


def _read_manifest(folder, name):
    folder = Path(folder).expanduser()
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError('Pasta de rascunhos inválida')
    file = _safe_file(folder / name)
    if not 0 < file.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ValueError('Manifesto de rascunhos ausente ou grande demais')
    result = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Manifesto não é objeto JSON')
    return folder, result


def prepare_asset_staging(inbox, draft, story_proposal, covers_dir,
                          *, captions_dir=None):
    """Validate all input manifests and return exact file-copy instructions.

    By design this function never saves any file or promotes draft quality.
    """
    bindings = asset_template(inbox, draft, story_proposal)
    source = bindings['provenance']
    expected = {(row['kind'], row['id']): row for row in bindings['clips']}
    cover_dir, cover_report = _read_manifest(covers_dir, 'COVER_DRAFT_MANIFEST.json')
    validate_cover_export(cover_dir, cover_report)
    for key, value in (
        ('source_sha256', source['source_sha256']),
        ('source_zip_sha256', source['source_zip_sha256']),
        ('r6_draft_sha256', source['r6_draft_sha256']),
        ('story_proposal_sha256', source['story_proposal_sha256']),
    ):
        if cover_report.get(key) != value:
            raise ValueError('Capas não pertencem a este roteiro R6: ' + key)
    if (cover_report.get('human_approved') is not False
            or cover_report.get('publication_ready') is not False
            or cover_report.get('render_executed') is not False):
        raise ValueError('Manifesto de capas contém aprovação indevida')
    cover_hash = sha256_file(cover_dir / 'COVER_DRAFT_MANIFEST.json')
    source_paths = {}
    copied = []
    seen = set()
    for row in cover_report.get('clips', []):
        if not isinstance(row, dict):
            raise ValueError('Corte de capa inválido')
        key = row.get('kind'), row.get('id')
        if key not in expected or key in seen:
            raise ValueError('Capa de corte desconhecido ou repetido')
        seen.add(key)
        relative = f'{key[0]}/{key[1]}/CAPA_RASCUNHO.png'
        if row.get('relative_path') != relative:
            raise ValueError('Caminho de capa não corresponde ao corte')
        file = _safe_file(cover_dir / relative)
        if file.stat().st_size != row.get('png_bytes') or sha256_file(file) != row.get('png_sha256'):
            raise ValueError('Capa mudou desde a extração')
        source_paths[(key[0], key[1], 'thumbnail')] = file
    if captions_dir is not None:
        caption_dir, caption_report = _read_manifest(
            captions_dir, 'CAPTION_DRAFT_MANIFEST.json')
        original_files, expected_report = prepare_caption_drafts(
            inbox, draft, story_proposal)
        if caption_report != expected_report:
            raise ValueError('Manifesto de transcrição diverge da fonte R6')
        for relative, raw in original_files.items():
            file = _safe_file(caption_dir / relative)
            if file.stat().st_size != len(raw) or sha256_file(file) != sha256_bytes(raw):
                raise ValueError('Legenda ASR original mudou desde a extração: ' + relative)
        caption_hash = sha256_file(caption_dir / 'CAPTION_DRAFT_MANIFEST.json')
    else:
        caption_hash = None
        original_files = {}
        caption_dir = None

    for row in bindings['clips']:
        kind, cid = row['kind'], row['id']
        for field, filename in (
            ('thumbnail', 'CAPA_RASCUNHO.png'),
            ('caption_ass', 'captions_unverified.ass'),
            ('caption_srt', 'captions_unverified.srt'),
        ):
            relative = f'{kind}/{cid}/{filename}'
            if field == 'thumbnail':
                path = source_paths.get((kind,cid,'thumbnail'))
            elif relative in original_files:
                path = _safe_file(caption_dir / relative)
            else:
                path = None
            if path is None:
                continue
            data_bytes = path.stat().st_size
            if data_bytes <= 0:
                raise ValueError('Asset vazio: ' + relative)
            row['assets'][field] = relative
            copied.append({
                'path': relative,
                'source_path': str(path.resolve(strict=True)),
                'sha256': sha256_file(path),
                'bytes': data_bytes,
                'role': field,
                'id': cid, 'kind': kind,
                'human_reviewed': False,
            })
    if len(copied) > MAX_FILE_COUNT or sum(x['bytes'] for x in copied) > MAX_TOTAL_BYTES:
        raise ValueError('Lote de assets excede os limites de staging')
    missing = [
        f"{row['kind']}/{row['id']}:{field}"
        for row in bindings['clips'] for field, path in row['assets'].items()
        if path is None
    ]
    return {
        'schema_version': SCHEMA,
        'status': 'ALL_FILES_STAGED_AS_DRAFT_REVIEW_PENDING' if not missing
                  else 'INCOMPLETE_DRAFT_FILES_NO_R57_ZIP',
        'provenance': source,
        'cover_manifest_sha256': cover_hash,
        'caption_manifest_sha256': caption_hash,
        'clip_count': len(bindings['clips']),
        'assets_available': len(copied),
        'assets_required': len(bindings['clips']) * 3,
        'missing_assets': missing,
        'files': copied,
        'bindings': bindings,
        'r57_import_ready': False, 'render_ready': False,
        'human_approved': False, 'captions_verified': False,
        'story_boundaries_reviewed': False, 'publication_ready': False,
        'r57_zip_generated': False, 'media_included': False,
        'files_modified': False,
    }


def _check_existing(folder, report):
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError('Destino de staging inválido')
    manifest_path = _safe_file(folder / MANIFEST_NAME)
    existing = json.loads(manifest_path.read_text(encoding='utf-8'))
    if existing != report:
        raise ValueError('Staging anterior possui manifesto divergente; sem sobrescrever')
    bindings = _safe_file(folder / BINDINGS_NAME)
    if json.loads(bindings.read_text(encoding='utf-8')) != report['bindings']:
        raise ValueError('Bindings anteriores foram alterados')
    descendants = list(folder.rglob('*'))
    if any(x.is_symlink() or (
            getattr(x.lstat(), 'st_file_attributes', 0) &
            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
           for x in descendants):
        raise ValueError('Links/junctions proibidos no staging')
    expected_paths = {x['path'] for x in report['files']} | {
        MANIFEST_NAME, BINDINGS_NAME}
    actual_paths = {x.relative_to(folder).as_posix()
                    for x in descendants if x.is_file()}
    if actual_paths != expected_paths:
        raise ValueError('Arquivos de staging inesperados/ausentes')
    for row in report['files']:
        target = _safe_file(folder / row['path'])
        if target.stat().st_size != row['bytes'] or sha256_file(target) != row['sha256']:
            raise ValueError('Asset de staging mudou; não sobrescrever: ' + row['path'])
    return folder


def save_asset_staging(inbox, draft, story_proposal, covers_dir,
                       *, captions_dir=None, destination_root=None):
    """Copy verified bytes to a new, no-overwrite review area and prefill R57 paths."""
    report = prepare_asset_staging(
        inbox, draft, story_proposal, covers_dir, captions_dir=captions_dir)
    if not report['files']:
        raise ValueError('Nenhum asset existente para consolidar')
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    out_root = root / report['provenance']['source_sha256'][:16]
    identity = {
        'source': report['provenance'], 'files': [
            (x['path'], x['sha256']) for x in report['files']],
        'cover_manifest_sha256': report['cover_manifest_sha256'],
        'caption_manifest_sha256': report['caption_manifest_sha256'],
    }
    destination = out_root / ('ASSETS_R6_STAGING_' + fingerprint(identity)[:20])
    # Covers, captions and staging are distinct siblings under output/r6_bridge
    # in the normal GUI workflow. Reject only paths where the actual staging
    # directory would overlap a source directory, not their shared ancestor.
    protected = [Path(inbox).expanduser().resolve(),
                 Path(covers_dir).expanduser().resolve()]
    if captions_dir is not None:
        protected.append(Path(captions_dir).expanduser().resolve())
    for original in protected:
        if (destination == original or destination.is_relative_to(original)
                or original.is_relative_to(destination)):
            raise ValueError('Destino de staging sobrepõe originais R6/rascunhos')
    if destination.exists():
        return _check_existing(destination, report)
    out_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.r6-asset-stage-', dir=out_root))
    published = False
    try:
        for asset in report['files']:
            src = _safe_file(asset['source_path'])
            relative = asset['path']
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if (src.stat().st_size != asset['bytes']
                    or sha256_file(src) != asset['sha256']):
                raise ValueError('Arquivo original mudou durante staging: ' + relative)
            shutil.copyfile(src, target, follow_symlinks=False)
            if sha256_file(target) != asset['sha256']:
                raise ValueError('Cópia do asset divergente: ' + relative)
            _verify_asset(stage, relative, asset['role'])
        (stage / BINDINGS_NAME).write_bytes(json_bytes(report['bindings']))
        (stage / MANIFEST_NAME).write_bytes(json_bytes(report))
        if destination.exists():
            raise ValueError('Staging criado em paralelo; não sobrescrever')
        stage.rename(destination)
        published = True
        return _check_existing(destination, report)
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
