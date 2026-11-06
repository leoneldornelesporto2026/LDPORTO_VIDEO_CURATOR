"""Read-only R6 -> R57 editorial bridge preparation; NEVER an executable R57 ZIP.

A real Analyzer inbox and an explicitly selected human R6 draft are revalidated
before constructing this content-addressed, media-free checklist. The R57
execution contract demands assets and continuous Stories not present in a
typical R6 selection. No fabricated assets, automatic approval, or publication.
"""
from __future__ import annotations

import json
from pathlib import Path

from .core import atomic_write, fingerprint, sha256_file
from .r6_review import LAYOUTS, read_analyzer_review
from .r6_workflow import preflight_editorial_draft
from .workspace import application_root

MAX_DRAFT_BYTES = 3 * 1024 * 1024


def prepare_r57_bridge(inbox, draft_path, media_path=None) -> dict:
    """Revalidate the draft and map ONLY selected, real R6 intervals to R57 slots."""
    draft = Path(draft_path).expanduser().resolve(strict=True)
    if not draft.is_file() or draft.stat().st_size > MAX_DRAFT_BYTES:
        raise ValueError('Roteiro R6 ausente ou maior que o limite')
    before = sha256_file(draft)
    # Provenance, source SHA, timestamps, selection and forged approvals are
    # checked against the original ZIP by the existing strict preflight.
    preflight = preflight_editorial_draft(draft, inbox, media_path)
    review = read_analyzer_review(inbox)
    payload = json.loads(draft.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or payload.get('schema_version') != 'ldporto-curator-r6-draft-1.0':
        raise ValueError('Versão do roteiro R6 incompatível')
    rows = payload.get('selected_reels')
    if not isinstance(rows, list) or len(rows) != preflight['selected_count']:
        raise ValueError('Seleção mudou durante a validação')
    if payload.get('selected_stories') != [] or payload.get('selected_story_count') != 0:
        raise ValueError('Stories não podem ser declarados pelo draft R6')
    if sha256_file(draft) != before:
        raise ValueError('Roteiro R6 modificado durante o preflight')

    checked = preflight['checked_reels']
    reels = []
    for row, validated in zip(rows, checked):
        if not isinstance(row, dict) or row.get('id') != validated['id'] or (
                row.get('source_candidate_id') != validated['source_candidate_id']):
            raise ValueError('Mapeamento de Reel inconsistente com o preflight')
        title = row.get('title')
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 130:
            raise ValueError('Título de Reel inválido')
        if row.get('layout') not in LAYOUTS:
            raise ValueError('Layout de Reel inválido')
        cid = validated['id']
        assets = {
            'thumbnail': f'REELS/{cid}/CAPA.png',
            'caption_ass': f'REELS/{cid}/KARAOKE.ass',
            'caption_srt': f'REELS/{cid}/LEGENDA.srt',
        }
        reels.append({
            'id': cid,
            'r6_candidate_id': validated['source_candidate_id'],
            'source_start': validated['start'],
            'source_end': validated['end'],
            'duration_seconds': round(validated['end'] - validated['start'], 3),
            'title_for_review': title.strip(),
            'layout_for_review': row['layout'],
            'assets_required_not_generated': assets,
            'review_flags': validated['review_flags'],
            'required_checks': [
                'review_transcript_and_caption_timing',
                'provide_verified_thumbnail_ass_srt',
                'review_audio_camera_and_source_context',
                'confirm_rights_and_human_preview',
            ],
            'approval': False,
            'render_ready': False,
        })

    # No Stories are fabricated even though R57 requires non-empty, contiguous
    # coverage over the source. The next step needs an actual editorial timeline.
    media = preflight['media_identity']
    media_status = media['status']
    blocking = [
        'R57_STORIES_CONTIGUOUS_FULL_SOURCE_TIMELINE_NOT_PROVIDED',
        'R57_THUMBNAILS_NOT_SUPPLIED_OR_VERIFIED',
        'R57_CAPTIONS_ASS_SRT_NOT_SUPPLIED_OR_VERIFIED',
        'EDITORIAL_AUDIO_CAMERA_CAPTION_REVIEW_PENDING',
        'PREVIEW_APPROVAL_AND_RIGHTS_REVIEW_PENDING',
    ]
    if media_status != 'EXACT_SOURCE_SHA256':
        blocking.append('ORIGINAL_MEDIA_SHA256_NOT_CONFIRMED_FOR_BRIDGE')
    if preflight['selected_overlapping_pairs']:
        blocking.append('R6_SELECTED_REELS_OVERLAP_REQUIRES_REVIEW')
    result = {
        'schema_version': 'ldporto-r6-to-r57-bridge-plan-1.0',
        'type': 'R6_TO_R57_PREPARATION_ONLY_NOT_IMPORTABLE',
        'status': 'BLOCKED_PENDING_EDITORIAL_ASSETS_AND_REVIEW',
        'provenance': {
            'source_sha256': preflight['source_sha256'],
            'source_zip_sha256': preflight['source_zip_sha256'],
            'r6_run_id': review['source']['run_id'],
            'r6_draft_sha256': before,
            'source_duration_seconds': review['source']['duration_seconds'],
            'source_story_candidate_count': review['story_candidate_count'],
        },
        'r57_expected_contract': {
            'required_root_files': [
                'EXECUTION_PLAN.json', 'REELS_EDIT_PLAN.json',
                'STORIES_SEQUENCIAIS_REVISAR.json', 'QUALITY_GATES.json',
                'MANIFEST_SHA256.json',
            ],
            'story_policy': 'nonempty_contiguous_full_source_coverage_up_to_60_seconds_each',
            'reel_count': len(reels),
            'story_count_created': 0,
        },
        'r57_reel_slots': reels,
        'r57_story_slots': [],
        'media_identity': {
            'status': media_status,
            'matches_analyzer': media.get('matches_analyzer'),
            'sha256': media.get('sha256'),
        },
        'preflight_warnings': preflight['warnings'],
        'blocking_reasons': blocking,
        'next_actions': [
            'Review each selected Reel and its source timestamp',
            'Create and review an explicit full-source Story timeline',
            'Supply actual verified thumbnails, ASS and SRT for each clip',
            'Validate source media SHA256, audio, camera and rights',
            'Build a complete manifest and validate the future R57 ZIP independently',
        ],
        'source_preserved': True,
        'r57_zip_generated': False,
        'r57_import_ready': False,
        'render_ready': False,
        'publication_ready': False,
        'human_approved': False,
        'contains_media': False,
    }
    if sha256_file(draft) != before:
        raise ValueError('Roteiro R6 alterado antes da conclusão')
    return result


def export_r57_bridge(inbox, draft_path, media_path=None, destination_root=None) -> Path:
    """Only an explicit call writes an immutable JSON plan, never media or ZIP."""
    plan = prepare_r57_bridge(inbox, draft_path, media_path)
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    folder = root / plan['provenance']['source_sha256'][:16]
    path = folder / ('R6_TO_R57_PLAN_' + fingerprint(plan)[:20] + '.json')
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(existing) != fingerprint(plan):
            raise ValueError('Plano de conversão existente divergente, sem sobrescrever')
        return path
    atomic_write(path, plan)
    return path
