"""R6 Story boundary proposals, explicitly NOT inferred editorial Stories.

Derives only technical, contiguous windows from a validated source duration.
The user must review content/scene choices, actual assets, and preview separately.
Never treats a duration split as an Analyzer Story or as publication approval.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .core import atomic_write, fingerprint, sha256_file
from .r6_review import read_analyzer_review
from .r6_workflow import preflight_editorial_draft
from .workspace import application_root

MAX_STORIES = 300
MAX_PROPOSAL_BYTES = 512 * 1024
PROPOSAL_TYPE = 'R6_STORY_BOUNDARY_PROPOSAL_NOT_EDITORIAL_APPROVAL'
PROPOSAL_VERSION = 'ldporto-r6-story-boundary-proposal-1.0'


def technical_story_windows(duration_seconds):
    """Even technical windows, max 60 seconds, covering source to millisecond precision."""
    if (isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('Duração de fonte inválida para Stories')
    total_ms = round(float(duration_seconds) * 1000)
    if total_ms < 1:
        raise ValueError('Duração insuficiente para segmentação')
    count = (total_ms + 59999) // 60000
    if count > MAX_STORIES:
        raise ValueError('Limite de Stories excedido')
    rows = []
    for index in range(count):
        a = (total_ms * index) // count
        b = (total_ms * (index + 1)) // count
        if b <= a or b - a > 60000:
            raise ValueError('Segmentação de Stories inválida')
        sid = f'STORY_{index + 1:02d}'
        rows.append({
            'id': sid, 'source_start': a / 1000, 'source_end': b / 1000,
            'duration_seconds': round((b - a) / 1000, 3),
            'title_for_review': f'Story {index + 1:02d} — título pendente',
            'layout_for_review': 'preserve',
            'timestamp_origin': 'TECHNICAL_DURATION_SPLIT_NOT_ANALYZER_STORY',
            'editorial_review_required': True,
            'approval': False,
            'render_ready': False,
        })
    return rows


def make_story_proposal(inbox, draft_path) -> dict:
    """Validate R6 selection and source bytes; generate no output or assets."""
    draft = Path(draft_path).expanduser()
    if not draft.is_file() or draft.is_symlink():
        raise ValueError('Roteiro R6 inexistente ou link')
    digest_before = sha256_file(draft)
    preflight = preflight_editorial_draft(draft, inbox)
    review = read_analyzer_review(inbox)
    if sha256_file(draft) != digest_before:
        raise ValueError('Roteiro R6 mudou durante a validação')
    duration = review['source']['duration_seconds']
    windows = technical_story_windows(duration)
    return {
        'schema_version': PROPOSAL_VERSION,
        'type': PROPOSAL_TYPE,
        'status': 'TECHNICAL_BOUNDARIES_REQUIRE_EDITORIAL_REVIEW',
        'provenance': {
            'source_sha256': preflight['source_sha256'],
            'source_zip_sha256': preflight['source_zip_sha256'],
            'r6_run_id': review['source']['run_id'],
            'r6_draft_sha256': digest_before,
            'source_duration_seconds': duration,
            'analyzer_story_candidate_count': review['story_candidate_count'],
        },
        'proposed_story_count': len(windows),
        'story_slots': windows,
        'editorial_review_complete': False,
        'r57_import_ready': False,
        'render_ready': False,
        'publication_ready': False,
        'human_approved': False,
        'contains_media': False,
        'source_preserved': True,
    }


def validate_story_proposal(path, *, preflight, review, draft_sha256):
    """Read a possible manually adjusted proposal; reject gaps, overlaps and provenance tampering."""
    file = Path(path).expanduser()
    if not file.is_file() or file.is_symlink() or file.stat().st_size > MAX_PROPOSAL_BYTES:
        raise ValueError('Proposta de Stories inexistente, insegura ou excessiva')
    before = sha256_file(file)
    proposal = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(proposal, dict) or proposal.get('schema_version') != PROPOSAL_VERSION or proposal.get('type') != PROPOSAL_TYPE:
        raise ValueError('Contrato da proposta de Stories inválido')
    for flag in ('editorial_review_complete', 'r57_import_ready', 'render_ready',
                 'publication_ready', 'human_approved', 'contains_media'):
        if proposal.get(flag) is not False:
            raise ValueError('Proposta afirma revisão ou aprovação indevida: ' + flag)
    source = proposal.get('provenance')
    if not isinstance(source, dict):
        raise ValueError('Proveniência de Stories ausente')
    expected = {
        'source_sha256': preflight['source_sha256'],
        'source_zip_sha256': preflight['source_zip_sha256'],
        'r6_run_id': review['source']['run_id'],
        'r6_draft_sha256': draft_sha256,
        'analyzer_story_candidate_count': review['story_candidate_count'],
    }
    for name, value in expected.items():
        if source.get(name) != value:
            raise ValueError('Proveniência dos Stories divergente: ' + name)
    duration = review['source']['duration_seconds']
    if (isinstance(source.get('source_duration_seconds'), bool)
            or not isinstance(source.get('source_duration_seconds'), (int, float))
            or abs(source['source_duration_seconds'] - duration) > 0.0001):
        raise ValueError('Duração dos Stories não corresponde à fonte')
    rows = proposal.get('story_slots')
    if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_STORIES
            or proposal.get('proposed_story_count') != len(rows)):
        raise ValueError('Contagem de Stories inválida')
    validated = []
    previous = 0.0
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get('id') != f'STORY_{i:02d}':
            raise ValueError('Identificador ou ordem de Story inválido')
        a, b = row.get('source_start'), row.get('source_end')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               for x in (a, b)):
            raise ValueError('Timestamp de Story inválido')
        a, b = float(a), float(b)
        if a < 0 or b <= a or b - a > 60.001 or b > duration + 0.003:
            raise ValueError('Janela de Story fora do contrato R57')
        if abs(a - previous) > 0.003:
            raise ValueError('Stories com gap ou overlap')
        if (isinstance(row.get('duration_seconds'), bool)
                or not isinstance(row.get('duration_seconds'), (int, float))
                or abs(float(row['duration_seconds']) - (b - a)) > 0.003):
            raise ValueError('Duração declarada de Story inválida')
        if (row.get('timestamp_origin') != 'TECHNICAL_DURATION_SPLIT_NOT_ANALYZER_STORY'
                or row.get('editorial_review_required') is not True
                or row.get('approval') is not False or row.get('render_ready') is not False
                or row.get('layout_for_review') != 'preserve'):
            raise ValueError('Story contém origem ou aprovação indevida')
        title = row.get('title_for_review')
        if not isinstance(title, str) or not title.strip() or len(title) > 130:
            raise ValueError('Título sugerido de Story inválido')
        validated.append({
            'id': row['id'], 'source_start': round(a, 3), 'source_end': round(b, 3),
            'duration_seconds': round(b - a, 3), 'title_for_review': title.strip(),
            'layout_for_review': 'preserve', 'editorial_review_required': True,
            'timestamp_origin': row['timestamp_origin'],
        })
        previous = b
    if abs(previous - duration) > 0.003:
        raise ValueError('Stories não cobrem a fonte inteira')
    if sha256_file(file) != before:
        raise ValueError('Proposta de Stories alterada durante a leitura')
    return validated


def export_story_proposal(inbox, draft_path, destination_root=None) -> Path:
    """Idempotent content-addressed JSON only. No ZIP, media or editor approval."""
    data = make_story_proposal(inbox, draft_path)
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    path = root / data['provenance']['source_sha256'][:16] / (
        'R6_STORY_PROPOSAL_' + fingerprint(data)[:20] + '.json')
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(old) != fingerprint(data):
            raise ValueError('Proposta de Stories já existe com conteúdo divergente')
        return path
    atomic_write(path, data)
    return path
