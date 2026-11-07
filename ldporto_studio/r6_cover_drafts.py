"""Preview-only cover drafts derived from the SHA-exact original Analyzer video.

Strict R6 Reel selection and bounded Story proposals drive timestamps.
FFmpeg extracts one real video frame per chosen clip, padded to portrait.
No cropping, synthetic visuals, title overlay, face tracking or rights approval.
Never modifies Analyzer R6 ZIP, original MP4 or existing R57 projects.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from .core import fingerprint, json_bytes, sha256_file
from .r6_media_audit import _safe_media
from .r6_r57_bridge import prepare_r57_bridge
from .rendering import binaries, probe_media
from .workspace import application_root

SCHEMA = 'ldporto-r6-cover-drafts-1.0'
MAX_CLIPS = 120
COVER_WIDTH = 720
COVER_HEIGHT = 1280
COMMAND_TIMEOUT = 150
MAX_PNG_BYTES = 20 * 1024 * 1024
KINDS = ('all', 'reels', 'stories')


def _check_link(path):
    if (path.is_symlink() or (
            getattr(path.lstat(), 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))):
        raise ValueError('Link/junction não permitido no caminho de capas')


def prepare_cover_drafts(inbox, draft, story_proposal, media, *, kind='all'):
    """Verify original bytes and describe exact midpoint frames, without writing."""
    if kind not in KINDS:
        raise ValueError('Tipo de corte inválido')
    plan = prepare_r57_bridge(inbox, draft, story_proposal_path=story_proposal)
    original = Path(media).expanduser()
    if not _safe_media(original):
        raise ValueError('Mídia local ausente, vazia, vinculada ou inválida')
    _check_link(original)
    media_path = original.resolve(strict=True)
    expected_sha = plan['provenance']['source_sha256']
    if sha256_file(media_path).lower() != expected_sha:
        raise ValueError('SHA256 da mídia difere da fonte exata do Analyzer')
    source_meta = probe_media(media_path)
    source_duration = float(plan['provenance']['source_duration_seconds'])
    if not source_meta['has_video'] or not math.isfinite(source_meta['duration']):
        raise ValueError('Fonte sem vídeo decodificável')
    if source_meta['duration'] + 0.5 < source_duration:
        raise ValueError('Duração real do vídeo é menor que a registrada no Analyzer')
    if source_meta['width'] <= 0 or source_meta['height'] <= 0:
        raise ValueError('Dimensões da mídia original inválidas')
    selected = []
    if kind in ('all', 'reels'):
        selected += [('reels', clip) for clip in plan['r57_reel_slots']]
    if kind in ('all', 'stories'):
        selected += [('stories', clip) for clip in plan['r57_story_boundary_proposals']]
    if not selected or len(selected) > MAX_CLIPS:
        raise ValueError('Seleção de capas vazia ou acima de 120 cortes; escolha um tipo')
    rows = []
    for category, clip in selected:
        begin, end = float(clip['source_start']), float(clip['source_end'])
        if not (0 <= begin < end <= source_duration + 0.002):
            raise ValueError('Intervalo de capa fora do vídeo')
        timestamp = round((begin + end) / 2.0, 3)
        if timestamp >= source_meta['duration']:
            raise ValueError('Quadro de capa fora da duração decodificável')
        rows.append({
            'id': clip['id'], 'kind': category,
            'source_start': begin, 'source_end': end,
            'frame_timestamp': timestamp,
            'relative_path': category + '/' + clip['id'] + '/CAPA_RASCUNHO.png',
            'frame_selected_by': 'MIDPOINT_TECHNICAL_NOT_EDITORIAL',
            'thumbnail_approved': False,
        })
    return {
        'schema_version': SCHEMA,
        'status': 'FRAME_PROPOSALS_FROM_EXACT_VIDEO_REVIEW_REQUIRED',
        'source_sha256': expected_sha,
        'source_zip_sha256': plan['provenance']['source_zip_sha256'],
        'r6_draft_sha256': plan['provenance']['r6_draft_sha256'],
        'story_proposal_sha256': sha256_file(story_proposal),
        'source_duration_seconds': source_duration,
        'media_path': str(media_path),
        'media_bytes': media_path.stat().st_size,
        'cover_width': COVER_WIDTH, 'cover_height': COVER_HEIGHT,
        'composition': 'PRESERVE_SOURCE_FULL_FRAME_WITH_PORTRAIT_PADDING',
        'clips': rows, 'clip_count': len(rows),
        'images_created': 0, 'frame_extraction_executed': False,
        'render_executed': False,
        'human_approved': False, 'caption_verified': False,
        'camera_verified': False, 'rights_verified': False,
        'r57_import_ready': False, 'publication_ready': False,
        'original_media_modified': False,
    }


def _validate_exported(folder, report):
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError('Diretório anterior de capas inválido')
    manifest_path = folder / 'COVER_DRAFT_MANIFEST.json'
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError('Manifesto anterior de capas ausente')
    saved = json.loads(manifest_path.read_text(encoding='utf-8'))
    if saved != report:
        raise ValueError('Manifesto anterior não corresponde à fonte')
    descendants = list(folder.rglob('*'))
    if any(p.is_symlink() or (
            getattr(p.lstat(), 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
    ) for p in descendants):
        raise ValueError('Link/junction detectado na pasta de capas')
    expected = {'COVER_DRAFT_MANIFEST.json'} | {
        r['relative_path'] for r in report['clips']}
    actual = {p.relative_to(folder).as_posix() for p in descendants if p.is_file()}
    if expected != actual:
        raise ValueError('Conteúdo da pasta de capas difere do manifesto')
    for row in report['clips']:
        file = folder / row['relative_path']
        if (not file.is_file() or file.stat().st_size != row['png_bytes']
                or sha256_file(file) != row['png_sha256']):
            raise ValueError('PNG de capa previamente salvo foi modificado')
    return folder


def export_cover_drafts(inbox, draft, story_proposal, media, *,
                        kind='all', confirm_review_only=False,
                        destination_root=None):
    """Explicit FFmpeg extraction with isolated atomic, no-overwrite destination."""
    if confirm_review_only is not True:
        raise ValueError('Use --confirm-review-only para autorizar apenas rascunhos de capas')
    report = prepare_cover_drafts(inbox, draft, story_proposal, media, kind=kind)
    source = Path(report['media_path'])
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    input_dir = Path(inbox).expanduser().resolve()
    if (root == input_dir or root.is_relative_to(input_dir)
            or input_dir.is_relative_to(root)
            or root == source or root.is_relative_to(source.parent)):
        raise ValueError('Destino de capas sobrepõe a entrada R6 ou pasta da mídia')
    output_base = root / report['source_sha256'][:16]
    immutable = {key:value for key,value in report.items()
                 if key not in ('images_created','frame_extraction_executed','render_executed')}
    destination = output_base / ('COVERS_R6_DRAFT_' + fingerprint(immutable)[:20])
    if destination.exists():
        saved = json.loads(
            (destination / 'COVER_DRAFT_MANIFEST.json').read_text(encoding='utf-8'))
        for key, value in report.items():
            if key not in ('images_created', 'frame_extraction_executed', 'status'):
                if saved.get(key) != value:
                    raise ValueError('Capas anteriores pertencem a outro roteiro ou mídia')
        return _validate_exported(destination, saved)
    ffmpeg, _ = binaries()
    output_base.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.cover-draft-staging-', dir=output_base))
    published = False
    try:
        from PIL import Image
        for row in report['clips']:
            file = stage / row['relative_path']
            file.parent.mkdir(parents=True, exist_ok=True)
            filters = (
                f'scale={COVER_WIDTH}:{COVER_HEIGHT}:force_original_aspect_ratio=decrease,'
                f'pad={COVER_WIDTH}:{COVER_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1'
            )
            command = [
                ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error',
                '-ss', f"{row['frame_timestamp']:.3f}", '-i', str(source),
                '-frames:v', '1', '-an', '-vf', filters,
                '-f', 'image2', '-vcodec', 'png', '-n', str(file),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=COMMAND_TIMEOUT)
            if result.returncode != 0 or not file.is_file():
                raise ValueError('FFmpeg não extraiu capa do intervalo ' + row['id']
                                 + ': ' + (result.stderr or '')[-500:])
            if not 0 < file.stat().st_size <= MAX_PNG_BYTES:
                raise ValueError('PNG vazio ou acima do limite: ' + row['id'])
            with Image.open(file) as im:
                if im.format != 'PNG' or im.size != (COVER_WIDTH, COVER_HEIGHT):
                    raise ValueError('PNG de capa inválido/dimensões divergentes')
                im.verify()
            row['png_sha256'] = sha256_file(file)
            row['png_bytes'] = file.stat().st_size
        # Recheck exact input and planning documents prior to publishing.
        if (sha256_file(source) != report['source_sha256'] or
                sha256_file(draft) != report['r6_draft_sha256'] or
                sha256_file(story_proposal) != report['story_proposal_sha256']):
            raise ValueError('Vídeo ou roteiro alterado durante extração de capas')
        report.update({
            'status': 'COVER_DRAFTS_FROM_SOURCE_PENDING_HUMAN_REVIEW',
            'images_created': len(report['clips']),
            'frame_extraction_executed': True,
            'render_executed': False,
        })
        (stage / 'COVER_DRAFT_MANIFEST.json').write_bytes(json_bytes(report))
        _validate_exported(stage, report)
        if destination.exists():
            raise ValueError('Destino de capas criado simultaneamente; não sobrescrever')
        stage.rename(destination)
        published = True
        return _validate_exported(destination, report)
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
