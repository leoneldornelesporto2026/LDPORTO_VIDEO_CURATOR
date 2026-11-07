"""Lossless reuse of existing Analyzer R6 evidence, not editorial asset generation.

Reads a fully validated original R6 handoff. Exports only existing, source-hashed
contact sheets and literal transcript files for human review. A contact sheet is
NOT a final thumbnail; ASR transcripts are NOT approved clip captions.
No inference, FFmpeg, downloads, R57 assets, imports, previews or publication.
"""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from zipfile import ZipFile

from .analyzer_inbox import inspect_delivery
from .core import fingerprint, json_bytes, sha256_bytes, sha256_file
from .r6_r57_bridge import prepare_r57_bridge
from .workspace import application_root

MAX_REUSE_FILE_BYTES = 12 * 1024 * 1024
MAX_REUSE_TOTAL_BYTES = 128 * 1024 * 1024
VERSION = 'ldporto-r6-evidence-reuse-1.0'
LITERAL_TRANSCRIPT_FILES = {
    'transcript/transcript.srt': 'source/transcript_original_unverified.srt',
    'transcript/relevant_segments.jsonl': 'source/relevant_segments_unverified.jsonl',
}


def _verified_evidence(inbox, draft):
    """Inventory real ZIP members without writing, reprocessing or inferring missing data."""
    plan = prepare_r57_bridge(inbox, draft)
    inspection = inspect_delivery(inbox)
    zip_path = Path(inspection['package_path'])
    zip_sha = inspection['zip_sha256']
    if zip_sha != plan['provenance']['source_zip_sha256']:
        raise ValueError('R6 ZIP diverge do roteiro de seleção')
    files = []
    reels = []
    total = 0
    with ZipFile(zip_path) as archive:
        members = set(archive.namelist())
        catalog = json.loads(archive.read('editorial/candidate_catalog.json'))
        by_id = {row['candidate_id']: row for row in catalog['candidates']}
        for clip in plan['r57_reel_slots']:
            reel_id, cid = clip['id'], clip['r6_candidate_id']
            row = by_id.get(cid)
            if not isinstance(row, dict):
                raise ValueError('Candidato R6 não existe: ' + str(cid))
            if (abs(row['start'] - clip['source_start']) > .001 or
                    abs(row['end'] - clip['source_end']) > .001):
                raise ValueError('Evidência temporal diverge da seleção')
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', cid)
                    or '..' in cid):
                raise ValueError('ID inseguro para evidência visual')
            visual = 'visuals/' + cid + '/contact_sheet.jpg'
            declared = row.get('visual_refs') or []
            available = visual in members and isinstance(declared, list) and visual in declared
            entry = {
                'reel_id': reel_id, 'candidate_id': cid,
                'source_start': clip['source_start'], 'source_end': clip['source_end'],
                'visual_evidence_status': 'NOT_IN_R6_PACKAGE',
                'visual_file': None,
                'caption_status': 'ORIGINAL_ASR_REQUIRES_MANUAL_CLIP_TIMING_AND_REVIEW',
                'thumbnail_ready': False,
                'editorial_approved': False,
            }
            if available:
                info = archive.getinfo(visual)
                if not 0 < info.file_size <= MAX_REUSE_FILE_BYTES:
                    raise ValueError('Evidência visual maior que o limite')
                content = archive.read(visual)
                try:
                    from PIL import Image
                    with Image.open(BytesIO(content)) as image:
                        if image.format != 'JPEG':
                            raise ValueError('Contact sheet não é JPEG')
                        if (not 1 <= image.width <= 10000 or
                                not 1 <= image.height <= 10000 or
                                image.width * image.height > 40_000_000):
                            raise ValueError('Dimensões de contact sheet fora do limite')
                        image.verify()
                except OSError as exc:
                    raise ValueError('Contact sheet JPEG inválido') from exc
                output_name = 'reels/' + reel_id + '/contact_sheet_original.jpg'
                files.append({
                    'zip_member': visual, 'output_relative_path': output_name,
                    'sha256': sha256_bytes(content), 'bytes': len(content),
                    'evidence_role': 'CONTACT_SHEET_FOR_HUMAN_REVIEW_NOT_THUMBNAIL',
                })
                entry['visual_evidence_status'] = 'EXISTING_R6_CONTACT_SHEET'
                entry['visual_file'] = output_name
                total += len(content)
            reels.append(entry)
        for source, output in LITERAL_TRANSCRIPT_FILES.items():
            if source not in members:
                continue
            info = archive.getinfo(source)
            if not 0 < info.file_size <= MAX_REUSE_FILE_BYTES:
                raise ValueError('Arquivo literal de transcrição excede limite')
            content = archive.read(source)
            try:
                decoded = content.decode('utf-8-sig')
            except UnicodeDecodeError as exc:
                raise ValueError('Transcrição existente não é UTF-8') from exc
            if '\x00' in decoded:
                raise ValueError('Transcrição contém NUL')
            files.append({
                'zip_member': source, 'output_relative_path': output,
                'sha256': sha256_bytes(content), 'bytes': len(content),
                'evidence_role': 'ORIGINAL_UNVERIFIED_ANALYZER_TRANSCRIPT',
            })
            total += len(content)
    if total > MAX_REUSE_TOTAL_BYTES:
        raise ValueError('Evidências excedem limite de reutilização')
    if sha256_file(zip_path) != zip_sha:
        raise ValueError('ZIP R6 alterado durante inventário')
    result = {
        'schema_version': VERSION,
        'type': 'REUSE_OF_EXISTING_ANALYZER_EVIDENCE_ONLY',
        'status': ('SOURCE_EVIDENCE_AVAILABLE_REVIEW_PENDING' if files
                   else 'NO_REUSABLE_EVIDENCE_IN_R6'),
        'provenance': dict(plan['provenance']),
        'reels': reels,
        'files': files,
        'reel_count': len(reels),
        'reused_visual_count': sum(x['visual_file'] is not None for x in reels),
        'missing_visual_count': sum(x['visual_file'] is None for x in reels),
        'existing_transcript_count': sum(x['zip_member'].startswith('transcript/') for x in files),
        'new_frames_decoded': False, 'inference_executed': False,
        'transcript_rewritten': False,
        'r57_asset_bindings_modified': False, 'r57_import_ready': False,
        'human_approved': False, 'render_ready': False,
        'publication_ready': False, 'media_included': False,
    }
    return zip_path, result


def inspect_r6_evidence(inbox, draft):
    """Read-only; no output directories or extracted evidence."""
    return _verified_evidence(inbox, draft)[1]


def _check_existing(folder, report):
    manifest_path = folder / 'EVIDENCE_REUSE_MANIFEST.json'
    if not folder.is_dir() or folder.is_symlink() or not manifest_path.is_file():
        raise ValueError('Diretório de evidências existente inválido; sem sobrescrever')
    if json.loads(manifest_path.read_text(encoding='utf-8')) != report:
        raise ValueError('Manifesto de evidências existente divergente')
    expected = {x['output_relative_path'] for x in report['files']}
    descendants = list(folder.rglob('*'))
    if any(p.is_symlink() or (
            getattr(p.lstat(), 'st_file_attributes', 0) &
            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
    ) for p in descendants):
        raise ValueError('Link/junction detectado na saída de evidências')
    found = {p.relative_to(folder).as_posix() for p in descendants if p.is_file()}
    if found != expected | {'EVIDENCE_REUSE_MANIFEST.json'}:
        raise ValueError('Arquivos inesperados ou ausentes no destino')
    for item in report['files']:
        file = folder / item['output_relative_path']
        if file.is_symlink() or not file.is_file() or file.stat().st_size != item['bytes']:
            raise ValueError('Evidência extraída alterada')
        if sha256_file(file) != item['sha256']:
            raise ValueError('SHA256 da evidência extraída diverge')
    return folder


def export_r6_evidence(inbox, draft, *, destination_root=None):
    """Explicit extraction; stable destination, no overwrites, original ZIP read-only."""
    archive_path, report = _verified_evidence(inbox, draft)
    if not report['files']:
        raise ValueError('Nenhuma evidência reutilizável no ZIP R6; não criar pasta vazia')
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    input_dir = Path(inbox).expanduser().resolve()
    if root == input_dir or root.is_relative_to(input_dir) or input_dir.is_relative_to(root):
        raise ValueError('Destino sobrepõe a entrada R6')
    root = root / report['provenance']['source_sha256'][:16]
    destination = root / ('EVIDENCE_R6_' + fingerprint(report)[:20])
    if destination.exists():
        return _check_existing(destination, report)
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.r6-evidence-stage-', dir=root))
    published = False
    try:
        with ZipFile(archive_path) as archive:
            for item in report['files']:
                raw = archive.read(item['zip_member'])
                if (len(raw) != item['bytes'] or sha256_bytes(raw) != item['sha256']):
                    raise ValueError('Evidência do ZIP mudou durante a extração')
                target = stage / item['output_relative_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output:
                    output.write(raw)
        if sha256_file(archive_path) != report['provenance']['source_zip_sha256']:
            raise ValueError('ZIP original mudou durante extração')
        (stage / 'EVIDENCE_REUSE_MANIFEST.json').write_bytes(json_bytes(report))
        _check_existing(stage, report)
        if destination.exists():
            return _check_existing(destination, report)
        # Same-volume directory move. No silent copy-overwrite fallback.
        stage.rename(destination)
        published = True
        return _check_existing(destination, report)
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
