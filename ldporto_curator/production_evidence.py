"""Adapt verified production containers to the existing Curator evidence/camera.

This module neither discovers external evidence nor runs perception. Source times
stay absolute until the existing Director produces a clip-relative render plan.
Availability, a geometric certificate and human approval remain separate facts.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
import zipfile
from pathlib import Path, PurePosixPath

from .evidence_source import _assemble, load_evidence


def _document(files, *names, default=None):
    for name in names:
        if name not in files:
            continue
        payload = files[name]
        if name.endswith('.jsonl'):
            return [json.loads(line) for line in payload.decode('utf-8-sig').splitlines() if line.strip()], name
        return json.loads(payload.decode('utf-8-sig')), name
    return default, None


def _rows(document, *keys):
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in keys:
            if isinstance(document.get(key), list):
                return document[key]
    return []


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _window(row, duration):
    start, end = row.get('source_start', row.get('start')), row.get('source_end', row.get('end'))
    if not all(_finite(t) for t in (start, end)) or not 0 <= start < end <= duration:
        raise ValueError('Production evidence has an invalid source interval')
    return float(start), float(end)


def _bbox(value):
    if not isinstance(value, dict):
        return None
    values = [value.get(k) for k in ('x', 'y', 'width', 'height')]
    if not all(_finite(v) for v in values):
        return None
    x, y, width, height = values
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1.000001 or y + height > 1.000001:
        return None
    return {k: float(v) for k, v in zip(('x', 'y', 'width', 'height'), values)}


def _merge_literal(existing, incoming, component):
    """Reject conflicting duplicate IDs; append only actual supplied records."""
    id_key = {'segments': 'segment_id', 'words': 'word_id'}[component]
    result = deepcopy(existing)
    indexed = {row[id_key]: row for row in result}
    seen = set()
    for row in incoming:
        identity = row.get(id_key)
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('Duplicate/missing production ' + id_key)
        seen.add(identity)
        if identity in indexed:
            previous = indexed[identity]
            literal_key = 'text' if component == 'segments' else 'word'
            literal = lambda record: record.get(literal_key, record.get('text'))
            if (previous.get('start'), previous.get('end'), literal(previous)) != (row.get('start'), row.get('end'), literal(row)):
                raise ValueError('Conflicting literal/timing for ' + identity)
            # Richer source fields may be additive; contradictory common fields
            # would silently change the evidence and must be reconciled instead.
            if any(previous[key] != row[key] for key in previous.keys() & row.keys()):
                raise ValueError('Conflicting production record for ' + identity)
        else:
            result.append(deepcopy(row))
    return sorted(result, key=lambda row: (row['start'], row['end'], row[id_key]))


def _metadata(package):
    metadata = deepcopy(package.get('metadata') or package.get('source') or {})
    if not metadata.get('sha256'):
        metadata['sha256'] = metadata.get('source_sha256') or package.get('manifest', {}).get('source_sha256')
    if not metadata.get('duration'):
        metadata['duration'] = metadata.get('source_duration') or package.get('manifest', {}).get('source_duration')
    if not isinstance(metadata.get('sha256'), str) or len(metadata['sha256']) != 64:
        raise ValueError('Production source needs its exact SHA256')
    if not _finite(metadata.get('duration')) or metadata['duration'] <= 0:
        raise ValueError('Production source needs its measured duration')
    return metadata


def _verified_handoff(package, handoff, metadata):
    if handoff is None:
        return None
    manifest = handoff.get('manifest') or {}
    other = _metadata(handoff)
    if other['sha256'] != metadata['sha256'] or other['duration'] != metadata['duration']:
        raise ValueError('Editorial handoff belongs to another source')
    expected = package.get('package_sha256')
    if not expected or manifest.get('package_sha256') != expected:
        raise ValueError('Editorial handoff is not bound to this exact package SHA256')
    return handoff


def _piece(row, kind, identity, duration, **ordering):
    start, end = _window(row, duration)
    intervals = deepcopy(row.get('source_intervals') or [{'start': start, 'end': end}])
    for interval in intervals:
        a, b = _window(interval, duration)
        if a < start or b > end:
            raise ValueError('Declared piece intervals exceed the original source window')
    return {'episode_id': identity, 'piece_kind': kind, 'raw_candidate_id': row.get('candidate_id'),
        'candidate_id': row.get('candidate_id'), 'source_start': start, 'source_end': end,
        'duration': end - start, 'source_intervals': intervals, 'camera_mode': 'AUTO_CONSERVADOR',
        'title': row.get('title'), 'title_data': {k: deepcopy(v) for k, v in row.items() if 'title' in k},
        'segment_ids': deepcopy(row.get('segment_ids') or row.get('source_segment_ids') or []),
        'word_ids': deepcopy(row.get('word_ids') or []), 'caption_preflight': deepcopy(row.get('caption_preflight') or {}),
        'risk_flags': deepcopy(row.get('risk_flags') or []), 'raw_proposal': deepcopy(row),
        'assembly_disclosure_required': bool(row.get('assembly_disclosure_required')) or any(
            abs(first['end'] - following['start']) > 1e-6 for first, following in zip(intervals, intervals[1:])),
        'state': 'PLANNED', 'human_approved': False, 'preview_approved': False,
        'publication_ready': False, 'requires_curator_review': True, **ordering}


def _pieces(evidence, files, duration):
    pieces = [_piece(row, 'REEL', 'REEL_' + row['candidate_id'], duration, order=i)
              for i, row in enumerate(evidence.get('candidates', []), 1)]
    sequences, _ = _document(files, 'editorial/story_sequence_candidates.json', '04_STORIES/series.json', default={})
    units, _ = _document(files, 'editorial/story_units.json', default={})
    unit_index = {row['unit_id']: row for row in _rows(units, 'units')}
    for series_order, sequence in enumerate(_rows(sequences, 'sequences', 'series'), 1):
        sid = sequence.get('sequence_id') or sequence.get('series_id')
        parts = sequence.get('parts')
        if parts is None:
            ids = sequence.get('unit_ids') or []
            if any(uid not in unit_index for uid in ids):
                raise ValueError('Story sequence references a missing source unit: ' + str(sid))
            parts = [unit_index[uid] for uid in ids]
        for order, row in enumerate(parts, 1):
            identity = str(sid) + '_PART_' + str(order).zfill(2)
            piece = _piece(row, 'STORY_PART', identity, duration, series_id=sid,
                series_order=series_order, order=order, unit_id=row.get('unit_id'),
                sequence_proposal=deepcopy(sequence))
            preflight_name = '04_STORIES/SERIE_' + str(series_order).zfill(3) + '/PARTE_' + str(order).zfill(2) + '/caption_preflight.json'
            preflight, name = _document(files, preflight_name)
            declared = (preflight.get('stories') or {}).get(row.get('unit_id')) if isinstance(preflight, dict) else None
            if declared:
                piece['caption_preflight'] = deepcopy(declared)
                piece['caption_preflight']['source_ref'] = name
            elif not piece['caption_preflight']:
                piece['caption_preflight'] = {'status': 'ALIGNMENT_REVIEW_REQUIRED', 'allowed_caption_mode': 'none',
                    'reason_codes': ['no_declared_verified_word_audio_preflight_for_source_unit'],
                    'origin': 'curator_missing_evidence_guard_not_an_audio_classification'}
            pieces.append(piece)
    stories, _ = _document(files, 'social/stories_manifest.json', 'stories_manifest.json', default={})
    for order, row in enumerate(_rows(stories, 'stories'), 1):
        pieces.append(_piece(row, 'STORY', str(row.get('story_id') or 'STORY_' + str(order)), duration, order=order))
    # Native proposals, including alternatives, are retained without editorial
    # ranking or a call to CURAR. Unknown generic schemas are not guessed.
    return pieces


def _ready_pieces(package, duration):
    pieces = []
    for i, imported in enumerate(package['pieces'], 1):
        raw = {**deepcopy(imported.get('editorial') or {}),
               'start': imported['source_start'], 'end': imported['source_end']}
        documents = imported.get('documents') or {}
        source_document = documents.get('source_segments')
        intervals = _rows(source_document, 'segments')
        if intervals:
            raw['source_intervals'] = intervals
        kind = 'REEL' if imported['kind'] == 'reel' else 'STORY_PART' if imported.get('series_id') else 'STORY'
        piece = _piece(raw, kind, imported['piece_id'], duration,
            series_id=imported.get('series_id'), order=imported.get('order') or i)
        for key in ('camera_plan', 'caption_plan', 'audio_plan'):
            piece[key] = deepcopy(imported.get(key) or {})
        piece.update(camera_plan_origin='verified_curator_ready', import_path=imported.get('path'),
            imported_documents=deepcopy(documents))
        pieces.append(piece)
    return pieces


def _dossier_native(package):
    """Read the bound nested archive in memory, with the shared ZIP bounds."""
    from .production_contract import _zip_members, _read_zip_files, _manifest_files
    payload = (package.get('files') or {}).get('06_SEGUNDA_CURADORIA/SECOND_CURATION_READY.zip')
    if payload is None:
        raise ValueError('Editorial handoff lacks its declared native package; supply the explicit native package')
    expected = (package.get('manifest') or {}).get('package_sha256')
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError('Editorial handoff nested package SHA256 differs')
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        files = _read_zip_files(archive, _zip_members(archive))
    manifest, _ = _document(files, 'SECOND_CURATION_MANIFEST.json', default={})
    _manifest_files(files, manifest, {'SECOND_CURATION_MANIFEST.json'})
    metadata, _ = _document(files, 'source/metadata.json', default={})
    if metadata.get('sha256') != _metadata(package)['sha256'] or manifest.get('source_hash') != metadata.get('sha256'):
        raise ValueError('Editorial handoff nested native source differs')
    return {'format': 'ANALYZER_NATIVE', 'files': files, 'manifest': manifest,
            'metadata': metadata, 'package_sha256': expected}


def _collection(containers, *aliases, keys=()):
    for container in reversed(containers):
        value, name = _document(container.get('files') or {}, *aliases)
        if name:
            return deepcopy(_rows(value, *keys)), container, name
    return [], None, None


def _assets(containers):
    assets = {}
    for container in containers:
        root = Path(container['root']).resolve() if container.get('root') else None
        for name, payload in (container.get('files') or {}).items():
            if PurePosixPath(name).suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                continue
            row = {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload), 'path': None}
            if root:
                target = (root / name).resolve()
                if not target.is_relative_to(root) or target.is_symlink():
                    raise ValueError('Visual asset escapes the verified container')
                if target.is_file():
                    if hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
                        raise ValueError('Staged visual asset SHA256 differs: ' + name)
                    row['path'] = str(target)
            assets[name] = row
    return assets


def normalise_production_evidence(package, *, handoff=None):
    """Pure adaptation of a verified container; no project/output writes."""
    if package.get('format') == 'EDITORIAL_HANDOFF':
        if handoff is not None:
            raise ValueError('A primary editorial handoff cannot be enriched by a second handoff')
        result = normalise_production_evidence(_dossier_native(package), handoff=package)
        result['evidence']['provenance']['production_adapter']['input_format'] = 'EDITORIAL_HANDOFF'
        return result
    metadata = _metadata(package)
    handoff = _verified_handoff(package, handoff, metadata)
    containers = [package] + ([handoff] if handoff else [])
    files = package.get('files') or {}
    if package.get('format') == 'ANALYZER_NATIVE' and package.get('path'):
        evidence = load_evidence(package['path'])
        if (evidence['source']['sha256'] != metadata['sha256'] or
                evidence['provenance'].get('input_package_sha256') != package.get('package_sha256')):
            raise ValueError('Native evidence source changed during adaptation')
    else:
        assembled_files = files
        supplied = package.get('evidence')
        if supplied:
            assembled_files = {**files, 'transcript/full_segments.jsonl': b'\n'.join(json.dumps(row).encode() for row in supplied.get('segments', [])),
                'transcript/full_words.jsonl': b'\n'.join(json.dumps(row).encode() for row in supplied.get('words', []))}
        evidence = _assemble(assembled_files, metadata, {'analysis_status': 'partial'}, {}, package.get('package_sha256'))
        if supplied:
            for key in evidence.keys() & supplied.keys() - {'source', 'metadata', 'provenance'}:
                evidence[key] = deepcopy(supplied[key])
            # Positive source-linked audio observations are contract-validated
            # upstream. Preserve them literally for the existing audio gate.
            for key in ('audio_events', 'audio'):
                if key in supplied:
                    evidence[key] = deepcopy(supplied[key])
    # A local source hash prefix is an internal namespace, never a YouTube ID.
    origin = metadata.get('source') or {}
    evidence['source'].update(id=origin.get('id') or metadata.get('video_id'),
        video_id=origin.get('id') or metadata.get('video_id'),
        namespace=metadata['sha256'][:12], identity_basis='source_sha256')
    merged_files = dict(files)
    if handoff:
        merged_files.update(handoff.get('files') or {})
        for component, aliases in (('segments', ('01_TRANSCRICAO/segmentos.jsonl', 'transcript/full_segments.jsonl')),
                                   ('words', ('01_TRANSCRICAO/palavras.jsonl', 'transcript/full_words.jsonl'))):
            document, name = _document(handoff.get('files') or {}, *aliases)
            if name:
                incoming = _rows(document, component)
                for row in incoming:
                    _window(row, metadata['duration'])
                evidence[component] = _merge_literal(evidence[component], incoming, component)
                evidence['availability'][component] = {'status': 'partial', 'count': len(evidence[component]),
                    'sources': ['verified_handoff/' + name], 'source_sha256': metadata['sha256'],
                    'artifact_sha256': hashlib.sha256(handoff['files'][name]).hexdigest(),
                    'completeness_claim': 'literal_supplied_records_not_full_audio_or_human_verification'}
    observations, _, obs_name = _collection(containers, 'people/person_appearances.json',
        '02_PESSOAS_E_CENAS/aparicoes.json', 'people_observations.json', keys=('observations', 'appearances'))
    if not obs_name:
        observations = evidence.get('people_observations') or []
    normalized, rejected = [], 0
    for raw in observations:
        time = raw.get('observed_at', raw.get('time'))
        if not _finite(time) or not 0 <= time <= metadata['duration']:
            raise ValueError('Visual observation has no valid absolute source time')
        row = deepcopy(raw)
        face, body = _bbox(raw.get('face_bbox')), _bbox(raw.get('body_bbox') or (raw.get('bbox') if raw.get('bbox_kind') == 'body' else None))
        rejected += bool(raw.get('face_bbox') and not face) + bool(raw.get('body_bbox') and not body)
        row.update(time=float(time), face_bbox=face, face_visible=raw.get('face_visible') is True and face is not None,
            body_visible=raw.get('body_visible') is True and body is not None,
            bbox=body, bbox_kind='body' if body else None,
            detection_confidence=raw.get('detection_confidence', raw.get('confidence')),
            source_time_basis='absolute_source_seconds', source_record_id=raw.get('appearance_id'),
            hands_evidence_status='observed' if raw.get('hand_bboxes') else 'unknown',
            instrument_evidence_status='unknown')
        # No face/body alias may turn a coarse person detection into a crop
        # certificate. The existing geometry engine still checks every crop.
        normalized.append(row)
    director, _, director_name = _collection(containers, 'camera/camera_director_timeline.json',
        'camera_director_timeline.json', keys=('timeline', 'segments'))
    if not director_name:
        director = evidence.get('camera_timeline') or evidence.get('director') or []
    scenes, _, scenes_name = _collection(containers, 'scenes.json', 'visual/scenes.json',
        '02_PESSOAS_E_CENAS/cenas.json', keys=('scenes',))
    if not scenes_name:
        scenes = evidence.get('scenes') or []
    for row in director + scenes:
        _window(row, metadata['duration'])
    shots = [{'start': row['start'], 'end': row['end'], 'shot_id': row['source_shot_id']}
             for row in director if row.get('source_shot_id')]
    if not shots:
        shots = [{'start': row['start'], 'end': row['end'], 'shot_id': row.get('shot_id', row.get('scene_id'))}
                 for row in scenes]
    graphics, _, graphics_name = _collection(containers, 'visual/broadcast_graphics_s8.json',
        'visual/broadcast_graphics.json', 'broadcast_graphics.json', keys=('intervals',))
    ocr, _, ocr_name = _collection(containers, 'visual/commercial_ocr_s8.json',
        'visual/ocr.json', 'ocr.json', keys=('texts', 'observations', 'frames'))
    instruments, _, instrument_name = _collection(containers, 'visual/instrument_observations.json',
        'people/instrument_observations.json', '02_PESSOAS_E_CENAS/instrumentos.json', keys=('observations',))
    tracks, _, tracks_name = _collection(containers, 'people/person_tracks.json',
        '02_PESSOAS_E_CENAS/trilhas.json', keys=('tracks', 'tracklets'))
    assets = _assets(containers)
    frames, _, frames_name = _collection(containers, 'frame_samples.json', 'visual/frame_samples.json', keys=('frame_samples', 'frames'))
    if not frames_name:
        frames = deepcopy(evidence.get('frame_samples') or [])
    for candidate in evidence.get('candidates') or []:
        visual_metadata = candidate.get('visual_metadata') or {}
        sheet_refs = [ref for ref in candidate.get('visual_refs') or [] if ref in assets]
        if not sheet_refs:
            continue
        for sample_order, sample in enumerate(visual_metadata.get('frames') or [], 1):
            time = sample.get('time')
            if not _finite(time) or not 0 <= time <= metadata['duration']:
                raise ValueError('Contact-sheet sample has an invalid source timestamp')
            frames.append({**deepcopy(sample), 'frame_sample_id': candidate['candidate_id'] + '_SAMPLE_' + str(sample_order),
                'candidate_id': candidate['candidate_id'], 'time': time, 'source_time_basis': 'absolute_source_seconds',
                'asset_refs': sheet_refs, 'asset_kind': 'contact_sheet_not_individual_decoded_frame',
                'asset_paths': [assets[ref]['path'] for ref in sheet_refs if assets[ref]['path']],
                'measurement_scope': 'sampled', 'sample_order': sample_order})
    shared, shared_name = _document(merged_files, 'camera/shared_camera_handoff.json', '05_CAMERAS/camera_handoff.json', default={})
    index = {'schema': 'LDP_PRODUCTION_VISUAL_INDEX_V1', 'source_sha256': metadata['sha256'],
        'source_time_basis': 'absolute_source_seconds', 'metadata': deepcopy(metadata),
        'observations': normalized, 'tracks': tracks, 'director': director, 'shots': shots, 'scenes': scenes,
        'frames': frames, 'broadcast_graphics': {'intervals': graphics}, 'ocr': ocr,
        'instrument_observations': instruments, 'shared_camera_handoff': shared,
        'assets': assets, 'hands_evidence_status': 'unknown',
        'instrument_evidence_status': 'observed' if instruments else 'unknown',
        'source_collections': {'observations': obs_name, 'director': director_name, 'scenes': scenes_name,
            'graphics': graphics_name, 'ocr': ocr_name, 'instruments': instrument_name, 'tracks': tracks_name,
            'frames': frames_name or 'editorial/candidate_catalog.json#visual_metadata.frames', 'shared_camera_handoff': shared_name}}
    evidence['people_observations'], evidence['camera_timeline'], evidence['director'] = normalized, director, director
    evidence['scenes'], evidence['graphics'] = scenes, graphics
    evidence['frame_samples'], evidence['person_tracks'], evidence['ocr'] = frames, tracks, ocr
    for component, rows, name in (('people_observations', normalized, obs_name), ('camera_timeline', director, director_name),
            ('scenes', scenes, scenes_name), ('frame_samples', frames, frames_name), ('person_tracks', tracks, tracks_name), ('ocr', ocr, ocr_name)):
        evidence['availability'][component] = {'status': 'available' if rows else 'missing', 'count': len(rows),
            'sources': [name] if name else [], 'source_sha256': metadata['sha256'], 'completeness_claim': 'sampled_inventory_not_continuous_verification'}
    evidence['provenance']['production_adapter'] = {'schema': index['schema'], 'input_format': package.get('format'),
        'input_package_sha256': package.get('package_sha256'), 'handoff_manifest_sha256':
        hashlib.sha256(handoff['files']['PROJECT_MANIFEST.json']).hexdigest() if handoff and 'PROJECT_MANIFEST.json' in handoff.get('files', {}) else None,
        'new_inference_executed': False, 'timestamps_invented': False}
    pieces = _ready_pieces(package, metadata['duration']) if 'pieces' in package else _pieces(evidence, merged_files, metadata['duration'])
    titles, _ = _document(merged_files, 'social/title_suggestions.json', default={})
    title_rows = _rows(titles, 'suggestions', 'titles', 'candidates')
    for piece in pieces:
        declared = [row for row in title_rows if row.get('candidate_id') == piece.get('raw_candidate_id')]
        if declared:
            piece['title_data']['source_suggestions'] = deepcopy(declared)
    return {'evidence': evidence, 'pieces': pieces, 'visual_index': index,
        'summary': {'source_sha256': metadata['sha256'], 'reels': sum(p['piece_kind'] == 'REEL' for p in pieces),
            'story_parts': sum(p['piece_kind'] == 'STORY_PART' for p in pieces),
            'story_series': len({p['series_id'] for p in pieces if p.get('series_id')}),
            'standalone_stories': sum(p['piece_kind'] == 'STORY' for p in pieces),
            'words': len(evidence['words']), 'observations': len(normalized), 'director_intervals': len(director),
            'tracks': len(tracks), 'frame_samples': len(frames), 'visual_assets': len(assets),
            'invalid_geometry_boxes': rejected, 'hands_evidence_status': 'unknown',
            'instrument_evidence_status': index['instrument_evidence_status'], 'human_approved': False}}


def build_piece_camera(evidence_index, piece, source_metadata, cfg=None):
    """Use the existing certified Director per interval, preserving every gap.

    No outer-window coverage threshold is allowed to discard a certified local
    interval. Conversely a certificate never authorizes its neighbouring gaps.
    Raw sampled observations stay available for the existing refinement engine;
    they do not override an explicit Director source-preservation decision.
    """
    from .camera_refinement import use_analyzer_director
    metadata = _metadata({'metadata': source_metadata})
    if evidence_index.get('source_sha256') != metadata['sha256']:
        raise ValueError('Camera evidence belongs to another source')
    start, end = _window(piece, metadata['duration'])
    if piece.get('camera_plan_origin') == 'verified_curator_ready':
        plan = deepcopy(piece['camera_plan'])
        plan.update(needs_review=True, human_approved=False, visual_source='verified_curator_ready_proposal')
        return plan
    director = evidence_index.get('director') or []
    protected = [row for row in evidence_index.get('scenes', [])
                 if row.get('critical_content') is True or row.get('critical_text') is True or row.get('crop_risk') in {'high', 'critical'}]
    protected += [row for row in evidence_index.get('instrument_observations', []) if row.get('preserve_source') is True or row.get('critical_content') is True]
    boundaries = {start, end}
    for row in director + protected:
        if row.get('end', 0) > start and row.get('start', end) < end:
            boundaries.update((max(start, row['start']), min(end, row['end'])))
    rows = []
    points = sorted(boundaries)
    for a, b in zip(points, points[1:]):
        risky = any(row['start'] < b and row['end'] > a for row in protected)
        plan = None if risky else use_analyzer_director(director, a, b)
        if plan:
            for row in plan['segments']:
                rows.append({**row, 'start': row['start'] + a - start, 'end': row['end'] + a - start,
                    'source_start': row['start'] + a, 'source_end': row['end'] + a})
        else:
            overlapping = [r for r in director if r.get('start', end) < b and r.get('end', 0) > a]
            unsupported = any((r.get('crop') or {}).get('safe') is True and
                (r.get('camera') or {}).get('zoom_start') != (r.get('camera') or {}).get('zoom_end') and
                max((r.get('camera') or {}).get('zoom_start', 1), (r.get('camera') or {}).get('zoom_end', 1)) > 1.05 for r in overlapping)
            rows.append({'start': a - start, 'end': b - start, 'source_start': a, 'source_end': b,
                'mode': 'full_frame_blur', 'reason': 'PROTECTED_SOURCE_CONTENT' if risky else
                'ANALYZER_ZOOM_EXCEEDS_EXISTING_RENDERER_ENVELOPE' if unsupported else 'SOURCE_PRESERVE', 'crop_safe': False})
    return {'schema_version': '4.4.0', 'mode': 'adaptive_timeline', 'segments': rows,
        'visual_source': 'analyzer_director', 'needs_review': True, 'human_approved': False,
        'diagnostics': {'source_sha256': metadata['sha256'], 'source_time_basis': 'absolute_source_seconds',
            'analyzer_safe_focus_fraction': sum(r['end'] - r['start'] for r in rows if r['mode'] == 'crop') / (end - start),
            'instrument_evidence_status': evidence_index.get('instrument_evidence_status', 'unknown'),
            'hands_evidence_status': evidence_index.get('hands_evidence_status', 'unknown'),
            'new_inference_executed': False, 'micro_perception_skipped': True}}
