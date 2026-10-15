"""Import human-review story proposals into a separate, sentence-bounded V5 project.

No source edits, invented ASR, inferred chronology, or automatic approval.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite

from .duration_presets import duration_metadata
from .series_planner import _prepare, _units, _episode, _coverage

MAX_STORY_SECONDS = 59.5  # Leave room for encoder rounding; always below 60 seconds.
SCHEMA = 'LDP_STORIES_REVIEW_V1'


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _numerical_bounds(part, total):
    start, end = part.get('start'), part.get('end')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
           for v in (start, end)) or not 0 <= start < end <= total:
        raise ValueError('Story possui timestamps inválidos ou fora da mídia original')
    return float(start), float(end)


def _split_at_sentences(units):
    """Use whole sentences; never divide a word, sentence or question/answer unit."""
    groups, current = [], []
    for unit in units:
        if unit['boundary_quality'] != 'sentence_or_qa' or unit.get('qa_incomplete'):
            raise ValueError('Não há limite de frase/pergunta-resposta suficientemente seguro')
        if unit['end'] - unit['start'] > MAX_STORY_SECONDS:
            raise ValueError('Uma frase indivisível excede 60 segundos: revisão de áudio necessária')
        if current and unit['end'] - current[0]['start'] > MAX_STORY_SECONDS:
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    return groups


def plan_reviewed_stories(evidence, document):
    """Build a *proposed*, never approved, three-series plan from Analyzer-backed units."""
    if not isinstance(document, dict) or document.get('schema_version') != SCHEMA:
        raise ValueError('Arquivo não é STORIES_SEQUENCIAIS_REVISAR.json (schema incompatível)')
    if document.get('state') != 'PROPOSED_NOT_APPROVED':
        raise ValueError('Estado editorial desconhecido; importação de Stories bloqueada')
    data = _prepare(evidence)
    if document.get('source_sha256') != data['source']['sha256']:
        raise ValueError('SHA256 dos Stories não corresponde ao vídeo analisado')
    all_units = _units(data)
    if not all_units:
        raise ValueError('Sem segmentos ASR confiáveis para delimitar frases')
    series = document.get('series')
    if not isinstance(series, list) or not series or len(series) > 40:
        raise ValueError('Séries ausentes ou quantidade inválida')
    original_segments = {row['segment_id'] for row in data['segments']}
    candidate_ids = {row['candidate_id'] for row in data['candidates']}
    episodes, skipped, adjusted = [], [], []
    used_ids, source_intervals = set(), []
    for series_row in series:
        if not isinstance(series_row, dict) or not isinstance(series_row.get('parts'), list):
            raise ValueError('Série malformada')
        series_id = series_row.get('series_id')
        if not isinstance(series_id, str) or not series_id or series_id in used_ids:
            raise ValueError('Identificação de série duplicada/inválida')
        used_ids.add(series_id)
        number = 0
        last_start = -1
        for part in series_row['parts']:
            if not isinstance(part, dict):
                raise ValueError('Parte de Story inválida')
            start, end = _numerical_bounds(part, data['total'])
            if start < last_start:
                raise ValueError('Stories fora da ordem apresentada na fonte')
            last_start = start
            ids = part.get('source_segment_ids')
            candidate_id = part.get('candidate_id')
            if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                    or not set(ids) <= original_segments or candidate_id not in candidate_ids):
                skipped.append({'series': series_id, 'part': part.get('part'),
                    'reason': 'Evidência/candidato ausente do pacote parcial'})
                continue
            candidate = next(c for c in data['candidates'] if c['candidate_id'] == candidate_id)
            if abs(candidate['start'] - start) > 0.6 or abs(candidate['end'] - end) > 0.6:
                skipped.append({'series': series_id, 'part': part.get('part'),
                    'reason': 'Limites do candidato divergentes da proposta'})
                continue
            matched = [u for u in all_units if any(s['segment_id'] in ids for s in u['segments'])]
            matched_segment_ids = {s['segment_id'] for u in matched for s in u['segments']}
            if not matched or not set(ids) <= matched_segment_ids:
                skipped.append({'series': series_id, 'part': part.get('part'),
                    'reason': 'Frases não localizadas integralmente na evidência'})
                continue
            # A proposed boundary can be inside a sentence; include the full atomic unit.
            if matched[0]['start'] < start - .001 or matched[-1]['end'] > end + .001:
                adjusted.append({'series': series_id, 'part': part.get('part'),
                    'proposed': [start, end], 'sentence_aligned': [matched[0]['start'], matched[-1]['end']]})
            try:
                groups = _split_at_sentences(matched)
            except ValueError as exc:
                skipped.append({'series': series_id, 'part': part.get('part'), 'reason': str(exc)})
                continue
            for group in groups:
                clip_start, clip_end = group[0]['start'], group[-1]['end']
                if source_intervals and any(a < clip_end and b > clip_start for sid,a,b in source_intervals if sid == series_id):
                    raise ValueError('Episódios sobrepostos dentro da mesma série')
                source_intervals.append((series_id, clip_start, clip_end))
                number += 1
                episode = _episode(group, data, _story_preset(), number, series_id)
                episode['story_order'] = len(episodes) + 1
                episode['order'] = number
                episode['series_title'] = str(series_row.get('title') or series_id)
                episode['title_text'] = f"{episode['series_title']} — PARTE {number}"
                episode['thumbnail_title'] = f"PARTE {number} — {episode['series_title']}"
                episode['hook_overlay'] = episode['title_text']
                episode['title_kind'] = 'proposed_needs_editorial_review'
                episode['title_duration'] = 5.0
                episode['subtitle_preset'] = 'LDP_CLEAN'
                episode['camera_mode'] = 'SOURCE_PRESERVE'
                episode['story_original_part'] = part.get('part')
                episode['story_original_candidate_id'] = candidate_id
                episode['narrative_link_confirmed'] = False
                episode['continuation_status'] = 'needs_review'
                episode['ending_label'] = 'sentence_complete_story_payoff_needs_review'
                episode['status'] = 'REVIEW_REQUIRED'
                episode['needs_review'] = True
                episode['human_approval'] = None
                episode['official_render_decision'] = None
                episode['risk_flags'] = sorted(set(episode['risk_flags'] + [
                    'story_narrative_needs_review', 'source_audio_needs_review']))
                opening = str(group[0]['segments'][0].get('text') or '').lstrip()
                if opening and opening[0].islower():
                    episode['risk_flags'].append('possible_mid_sentence_start_requires_audio_review')
                episode['review_questions'] = [
                    'A fala inicial possui contexto e sujeito?',
                    'A parte termina em frase completa, mas também fecha a ideia?',
                    'A continuação para a próxima parte é coerente?',
                    'Áudio, legenda, câmera e título foram conferidos no preview?']
                episodes.append(episode)
    if not episodes:
        raise ValueError('Nenhum Story elegível sem cortar frase; nenhuma edição foi criada')
    for index, episode in enumerate(episodes):
        siblings = [e for e in episodes if e['series_id'] == episode['series_id']]
        location = siblings.index(episode)
        episode['episode_part_label'] = f"Parte {location + 1}/{len(siblings)}"
        episode['previous_episode_id'] = siblings[location-1]['episode_id'] if location else None
        episode['next_episode_id'] = siblings[location+1]['episode_id'] if location+1 < len(siblings) else None
        episode['continuation_required'] = location+1 < len(siblings)
    preset = _story_preset()
    story_map = _coverage(data, episodes)
    return {'schema_version': '5.1.0', 'methodology': 'verified_story_sentence_boundaries_v2',
        'plan_id': 'STORIES_' + _fingerprint([data['source']['sha256'], document, [[e['episode_id'],e['title_text']] for e in episodes]])[:24],
        'source': deepcopy(data['source']), 'source_sha256': data['source']['sha256'],
        'mode': 'SERIE_CRONOLOGICA', 'duration_preset': preset.key, 'duration_label': preset.label,
        'status': 'REVIEW_REQUIRED', 'episodes': episodes, 'extras': [], 'story_map': story_map,
        'coverage': deepcopy(story_map), 'provenance': deepcopy(evidence.get('provenance') or {}),
        'availability': deepcopy(evidence.get('availability') or {}),
        'warnings': ['Séries seguem a ordem do relato, não comprovação da cronologia histórica.',
                     'Fim de frase não comprova desfecho completo. Revisar contexto e áudio.',
                     'Nenhuma aprovação ou permissão de publicação foi atribuída.'],
        'story_import_report': {'episodes': len(episodes), 'series': len({e['series_id'] for e in episodes}),
              'sentence_aligned': adjusted, 'skipped': skipped, 'max_duration_seconds': MAX_STORY_SECONDS,
              'source_transcript_status': (evidence.get('availability') or {}).get('segments', {}).get('status')},
        'official_shortlist': deepcopy(evidence.get('shortlist') or []),
        'official_decisions_modified': False, 'human_approval': None, 'approval_required': True,
        'audit_trail': [{'action': 'import_story_proposals', 'status': 'review_required',
            'source_sha256': data['source']['sha256']}]}


def _story_preset():
    from .duration_presets import get_preset
    return get_preset('story_upto_60')
