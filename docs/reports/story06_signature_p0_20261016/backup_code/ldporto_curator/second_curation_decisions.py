"""Portable V4.4 decision contract, shared verbatim with the standalone Curator."""
from abc import ABC, abstractmethod
from copy import deepcopy
import math

SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'SECOND_CURATION_DECISIONS V4.4',
    'type': 'object', 'additionalProperties': False,
    'required': ['schema_version', 'source_sha256', 'provider', 'actions'],
    'properties': {
        'schema_version': {'const': '4.4.0'}, 'source_sha256': {'type': 'string', 'minLength': 1},
        'input_package_sha256': {'type': ['string', 'null']},
        'provider': {'enum': ['manual_json', 'local_ollama', 'chatgpt_api', 'other_llm']},
        'notes': {'type': 'array', 'items': {'type': 'string'}},
        'actions': {'type': 'array', 'maxItems': 500, 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['decision_id', 'action', 'candidate_ids', 'reason'],
            'properties': {
                'decision_id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,100}$'},
                'action': {'enum': ['approve', 'reject', 'promote', 'demote', 'commercial', 'merge', 'split',
                                    'expand', 'shrink', 'alternate', 'duplicate']},
                'candidate_ids': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'type': 'string'}},
                'reason': {'type': 'string', 'minLength': 1}, 'title': {'type': 'string'},
                'rank': {'type': 'integer', 'minimum': 1}, 'commercial_override': {'type': 'boolean'},
                'suggested_layout': {'enum': ['single_speaker', 'speaker_reaction', 'two_shot', 'split_screen', 'source_preserve']},
                'evidence_segment_ids': {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string'}},
                'windows': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['start', 'end'],
                    'properties': {'start': {'type': 'number', 'minimum': 0}, 'end': {'type': 'number', 'exclusiveMinimum': 0}}}}
            }}}
    }
}


def compile_decisions(document, catalog, metadata, segments=None):
    import jsonschema
    jsonschema.validate(document, SCHEMA)
    if document['source_sha256'] != metadata.get('sha256'):
        raise ValueError('Second curation source hash mismatch')
    candidates = {row['candidate_id']: row for row in catalog['candidates']}
    approved, blocked, seen = {}, set(), set()
    duration = float(metadata['duration'])
    for action in document['actions']:
        if action['decision_id'] in seen:
            raise ValueError('Duplicate decision_id')
        seen.add(action['decision_id'])
        ids = action['candidate_ids']
        if not set(ids) <= candidates.keys():
            raise ValueError('Unresolved candidate reference')
        rows = [candidates[cid] for cid in ids]
        available = set(sid for row in rows for sid in row.get('segment_ids', []))
        available.update(s['segment_id'] for s in segments or [])
        if not set(action.get('evidence_segment_ids', [])) <= available:
            raise ValueError('Unresolved evidence reference')
        name = action['action']
        if name in {'reject', 'demote', 'commercial'}:
            for key in list(approved):
                if set(approved[key]['candidate_ids']).intersection(ids):
                    del approved[key]
            if name == 'commercial':
                blocked.update(ids)
            continue
        if name == 'duplicate':
            for key in list(approved):
                if set(approved[key]['candidate_ids']).intersection(ids[1:]):
                    del approved[key]
            continue
        manual_override = action.get('commercial_override') and document['provider'] == 'manual_json'
        if not manual_override and (blocked.intersection(ids) or any(
                row.get('content_type') in {'advertisement', 'sponsor_read', 'merchandising', 'commercial_promotion', 'event_promotion', 'self_promotion'}
                or (row.get('commercial_classification') or {}).get('eligibility') == 'excluded' for row in rows)):
            continue
        if name == 'merge' and len(ids) < 2:
            raise ValueError('Merge requires two or more candidates')
        if name == 'split' and len(action.get('windows', [])) < 2:
            raise ValueError('Split requires explicit windows')
        if name in {'expand', 'shrink'} and not action.get('windows'):
            raise ValueError('Boundary edits require explicit windows')
        windows = action.get('windows') or [{'start': min(row['start'] for row in rows), 'end': max(row['end'] for row in rows)}]
        for key in list(approved):
            if set(approved[key]['candidate_ids']).intersection(ids):
                del approved[key]
        if name == 'alternate':
            groups = {row.get('duplicate_group_id') for row in rows if row.get('duplicate_group_id')}
            for key in list(approved):
                if approved[key].get('duplicate_group_id') in groups:
                    del approved[key]
        previous_end = -1.
        for index, window in enumerate(windows):
            start, end = float(window['start']), float(window['end'])
            if not math.isfinite(start + end) or not 0 <= start < end <= duration or start < previous_end:
                raise ValueError('Invalid or overlapping decision interval')
            previous_end = end
            if name == 'shrink' and (start < min(r['start'] for r in rows) or end > max(r['end'] for r in rows)):
                raise ValueError('Shrink extends original interval')
            refs = [s['segment_id'] for s in segments or [] if s['end'] > start and s['start'] < end] or sorted(available)
            key = action['decision_id'] + f'_{index + 1:02}'
            approved[key] = {'decision_id': key, 'candidate_ids': ids, 'start': start, 'end': end,
                'rank': action.get('rank', len(approved) + 1), 'title': action.get('title') or rows[0].get('topic') or 'Trecho selecionado',
                'reason': action['reason'], 'evidence_segment_ids': refs, 'suggested_layout': action.get('suggested_layout'),
                'curation_source': 'SECOND_CURATOR' if document['provider'] == 'manual_json' else 'AI_SECOND_CURATOR',
                'original_ranks': [row.get('original_rank', row.get('rank')) for row in rows],
                'action': name, 'commercial_override': bool(manual_override), 'needs_review': True,
                'duplicate_group_id': rows[0].get('duplicate_group_id')}
    return sorted(approved.values(), key=lambda r: (r['rank'], r['decision_id']))


class SecondCuratorProvider(ABC):
    @abstractmethod
    def curate(self, package):
        """Return this contract; rendering/approval remains local and independent."""


class ManualJsonProvider(SecondCuratorProvider):
    def __init__(self, document):
        self.document = deepcopy(document)

    def curate(self, package):
        compile_decisions(self.document, package['catalog'], package['metadata'], package.get('segments'))
        return deepcopy(self.document)
