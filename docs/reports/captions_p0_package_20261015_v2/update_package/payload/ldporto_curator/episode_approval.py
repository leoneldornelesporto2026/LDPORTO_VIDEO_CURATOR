"""V5 approvals bind one human-reviewed episode and all its rendering inputs."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
import subprocess
from pathlib import Path
from .approval import file_hash
from .utils import load_json, write_json


@lru_cache(maxsize=1)
def _ffmpeg_version():
    try:
        return subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return 'ffmpeg_unavailable'


def renderer_fingerprint():
    root = Path(__file__).parent
    names = ('render.py', 'title_card.py', 'subtitles.py', 'series_workflow.py',
             'subtitle_presets.py', 'title_presets.py', 'thumbnail_presets.py', 'media_effects.py', 'episode_approval.py')
    return hashlib.sha256((''.join(file_hash(root / name) for name in names) + _ffmpeg_version()).encode()).hexdigest()


def episode_signature(episode, source_sha256, cfg=None, *, transcript_fingerprint=None):
    # Bind every editorial/visual input, including currently unsupported extensions.
    excluded = {'state', 'status', 'preview', 'approval', 'human_approval', 'final', 'history',
                'rendered_duration', 'preview_duration', 'duration_rendered', 'render_validation', 'plan_hash',
                'duration_verified_by_ffprobe', 'encoding_tolerance_seconds', 'approval_history',
                'caption_timeline'}
    payload = {k: v for k, v in episode.items() if k not in excluded}
    from .media_effects import effect_input_fingerprints
    return hashlib.sha256(json.dumps({'episode': payload, 'source_sha256': source_sha256,
        'settings': cfg or {}, 'transcript_fingerprint': transcript_fingerprint,
        'effect_inputs': effect_input_fingerprints(episode), 'renderer_fingerprint': renderer_fingerprint()},
        sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def record_episode_preview(directory, media, signature, validation, assets=()):
    directory, media = Path(directory).resolve(), Path(media).resolve()
    if not media.is_relative_to(directory) or not media.is_file():
        raise ValueError('Preview deve estar dentro da pasta do episódio')
    if validation.get('status') != 'validated':
        raise ValueError('Preview ainda não validado')
    rows = []
    for path in (media, *map(Path, assets)):
        path = path.resolve()
        if not path.is_file() or not path.is_relative_to(directory):
            raise ValueError('Asset externo ou ausente')
        rows.append({'path': path.relative_to(directory).as_posix(), 'sha256': file_hash(path)})
    record = {'plan_signature': signature, 'path': media.relative_to(directory).as_posix(),
              'sha256': file_hash(media), 'assets': rows, 'validation': validation,
              'preview_approved_by_human': False}
    write_json(directory / 'PREVIEW_REVIEW_V5.json', record)
    return record


def _matches(directory, record, signature):
    directory = Path(directory).resolve()
    if record.get('plan_signature') != signature or not record.get('assets'):
        return False
    media = (directory / record.get('path', '')).resolve()
    if not media.is_relative_to(directory) or not media.is_file() or file_hash(media) != record.get('sha256'):
        return False
    for row in record['assets']:
        path = (directory / row['path']).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or file_hash(path) != row['sha256']:
            return False
    return True


def approve_episode_preview(directory, signature, *, human_reviewed=False, duration_deviation_accepted=False):
    if human_reviewed is not True:
        raise ValueError('Aprovação exige ação explícita após assistir ao preview')
    directory = Path(directory)
    record = load_json(directory / 'PREVIEW_REVIEW_V5.json', {}) or {}
    if not _matches(directory, record, signature):
        raise ValueError('Preview/plano/assets mudaram; gere e revise outra prévia')
    record = {**record, 'preview_approved_by_human': True,
              'duration_deviation_accepted': duration_deviation_accepted is True,
              'publication_approved': False}
    write_json(directory / 'PREVIEW_APPROVED_V5.json', record)
    return record


def episode_approval_matches(directory, signature):
    record = load_json(Path(directory) / 'PREVIEW_APPROVED_V5.json', {}) or {}
    return record.get('preview_approved_by_human') is True and _matches(directory, record, signature)
