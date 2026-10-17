"""Production adaptation is source-bound, literal and independent of approvals."""
from copy import deepcopy
import hashlib
import json

import pytest

from ldporto_curator.production_evidence import normalise_production_evidence, build_piece_camera
from ldporto_curator.camera_refinement import use_analyzer_director


SOURCE = 'a' * 64
PACKAGE = 'b' * 64


def payload(value):
    return json.dumps(value).encode()


def director(start=2., end=4., **overrides):
    return {'start': start, 'end': end, 'layout': 'single_person', 'crop': {'safe': True},
        'focus_person': 'P', 'focus_confidence': .95, 'camera_evidence_role': 'DOMINANT_FACE',
        'source_shot_id': 'S', 'camera': {'center_start': [.4, .5], 'center_end': [.45, .5],
        'zoom_start': 1., 'zoom_end': 1.025}, **overrides}


def container():
    metadata = {'sha256': SOURCE, 'duration': 20., 'width': 1920, 'height': 1080,
                'source': {'type': 'local', 'filename': 'original.mp4'}}
    files = {'editorial/candidate_catalog.json': payload({'candidates': [
        {'candidate_id': 'A', 'start': 0., 'end': 10., 'caption_preflight': {'allowed_caption_mode': 'none'}}]}),
        'transcript/relevant_segments.jsonl': payload({'segment_id': 'S1', 'start': 2., 'end': 4., 'text': 'real words'}),
        'transcript/relevant_words.jsonl': b'\n'.join(payload(row) for row in [
            {'word_id': 'W1', 'segment_id': 'S1', 'start': 2., 'end': 3., 'word': 'real'},
            {'word_id': 'W2', 'segment_id': 'S1', 'start': 3., 'end': 4., 'word': 'words'}]),
        'camera/camera_director_timeline.json': payload([director()])}
    return {'format': 'CURATOR_READY', 'metadata': metadata, 'files': files,
            'manifest': {}, 'package_sha256': PACKAGE}


def test_all_declared_pieces_stay_proposals_and_sequence_parts_are_units():
    package = container()
    package['files'].update({
        'editorial/story_sequence_candidates.json': payload({'sequences': [
            {'sequence_id': 'SQ', 'unit_ids': ['U1', 'U2'], 'publication_ready': True}]}),
        'editorial/story_units.json': payload({'units': [
            {'unit_id': 'U1', 'start': 2., 'end': 6., 'source_intervals': [{'start': 2., 'end': 3.}, {'start': 5., 'end': 6.}]},
            {'unit_id': 'U2', 'start': 6., 'end': 9.}]}),
        'social/stories_manifest.json': payload({'stories': [{'story_id': 'ST', 'start': 3., 'end': 8.}]})})
    original = deepcopy(package)
    result = normalise_production_evidence(package)
    assert package == original
    assert result['summary']['reels'] == 1
    assert result['summary']['story_parts'] == 2
    assert result['summary']['standalone_stories'] == 1
    part = result['pieces'][1]
    assert part['series_id'] == 'SQ' and part['unit_id'] == 'U1' and part['order'] == 1
    assert part['assembly_disclosure_required'] is True
    assert len(part['source_intervals']) == 2
    assert all(p['human_approved'] is p['preview_approved'] is p['publication_ready'] is False for p in result['pieces'])
    assert result['pieces'][0]['caption_preflight']['allowed_caption_mode'] == 'none'
    assert result['evidence']['source']['video_id'] is None
    assert result['evidence']['source']['identity_basis'] == 'source_sha256'


def test_missing_sequence_unit_fails_instead_of_silently_dropping_it():
    package = container()
    package['files']['editorial/story_sequence_candidates.json'] = payload({'sequences': [{'sequence_id': 'SQ', 'unit_ids': ['absent']}]})
    with pytest.raises(ValueError, match='missing source unit'):
        normalise_production_evidence(package)


def test_real_body_and_face_geometry_aliases_remain_distinct():
    package = container()
    body = {'x': .2, 'y': .1, 'width': .5, 'height': .8}
    face = {'x': .4, 'y': .15, 'width': .08, 'height': .15}
    package['files']['people/person_appearances.json'] = payload([
        {'appearance_id': 'OBS', 'observed_at': 2.5, 'person_id': 'P', 'track_id': 'T',
         'face_bbox': face, 'body_bbox': body, 'face_visible': True, 'body_visible': True,
         'confidence': .93, 'safe_crop_possible': True},
        {'observed_at': 3., 'person_id': 'Q', 'body_bbox': body, 'body_visible': True, 'face_visible': True}])
    result = normalise_production_evidence(package)
    rows = result['visual_index']['observations']
    assert rows[0]['bbox'] == body and rows[0]['bbox_kind'] == 'body'
    assert rows[0]['face_bbox'] == face and rows[0]['time'] == 2.5
    assert rows[0]['detection_confidence'] == .93
    assert rows[1]['face_bbox'] is None and rows[1]['face_visible'] is False
    assert rows[0]['hands_evidence_status'] == rows[0]['instrument_evidence_status'] == 'unknown'


def handoff(package, words):
    return {'format': 'EDITORIAL_HANDOFF', 'metadata': deepcopy(package['metadata']),
        'manifest': {'package_sha256': PACKAGE}, 'files': {
            '01_TRANSCRICAO/palavras.jsonl': b'\n'.join(payload(word) for word in words)}}


def test_handoff_enrichment_requires_both_source_and_exact_package():
    package = container()
    enriched = handoff(package, [])
    enriched['metadata']['sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='another source'):
        normalise_production_evidence(package, handoff=enriched)
    enriched = handoff(package, [])
    enriched['manifest']['package_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='exact package'):
        normalise_production_evidence(package, handoff=enriched)


def test_only_consistent_literal_words_are_enriched_and_gate_stays_blocked():
    package = container()
    original = {'word_id': 'W1', 'segment_id': 'S1', 'start': 2., 'end': 3., 'word': 'real'}
    added = {'word_id': 'W3', 'segment_id': 'S2', 'start': 8., 'end': 9., 'word': 'source'}
    result = normalise_production_evidence(package, handoff=handoff(package, [original, added]))
    assert [word['word_id'] for word in result['evidence']['words']] == ['W1', 'W2', 'W3']
    assert result['evidence']['availability']['words']['status'] == 'partial'
    assert result['pieces'][0]['caption_preflight']['allowed_caption_mode'] == 'none'
    with pytest.raises(ValueError, match='Conflicting literal'):
        normalise_production_evidence(package, handoff=handoff(package, [{**original, 'word': 'invented'}]))


def test_enrichment_rejects_changed_source_record_and_duplicate_ids():
    package = container()
    word = {'word_id': 'W1', 'segment_id': 'S1', 'start': 2., 'end': 3., 'word': 'real'}
    with pytest.raises(ValueError, match='Duplicate'):
        normalise_production_evidence(package, handoff=handoff(package, [word, word]))
    with pytest.raises(ValueError, match='Conflicting production record'):
        normalise_production_evidence(package, handoff=handoff(package, [{**word, 'segment_id': 'OTHER'}]))


def test_interval_certificates_work_below_whole_piece_coverage_and_preserve_gaps():
    result = normalise_production_evidence(container())
    assert use_analyzer_director(result['visual_index']['director'], 0, 10) is None
    plan = build_piece_camera(result['visual_index'], result['pieces'][0], result['evidence']['metadata'])
    assert [(r['start'], r['end'], r['mode']) for r in plan['segments']] == [
        (0, 2, 'full_frame_blur'), (2, 4, 'crop'), (4, 10, 'full_frame_blur')]
    crop = plan['segments'][1]
    assert crop['zoom_start'] == 1 and crop['zoom_end'] == 1.025
    assert crop['source_start'] == 2 and crop['source_end'] == 4
    assert plan['diagnostics']['analyzer_safe_focus_fraction'] == .2


@pytest.mark.parametrize('change', [{'crop': {'safe': False}}, {'camera_evidence_role': 'SOURCE_PRESERVE'},
    {'focus_confidence': .8}, {'layout': 'full_frame'}, {'source_shot_id': None}])
def test_unsafe_or_summary_rows_never_become_certificates(change):
    package = container()
    package['files']['camera/camera_director_timeline.json'] = payload([director(**change)])
    result = normalise_production_evidence(package)
    plan = build_piece_camera(result['visual_index'], result['pieces'][0], result['evidence']['metadata'])
    assert all(row['mode'] == 'full_frame_blur' for row in plan['segments'])


def test_protected_map_or_instrument_content_overrides_a_focus_certificate():
    result = normalise_production_evidence(container())
    result['visual_index']['scenes'] = [{'start': 3., 'end': 5., 'critical_content': True, 'scene_type': 'map'}]
    plan = build_piece_camera(result['visual_index'], result['pieces'][0], result['evidence']['metadata'])
    assert any(row['mode'] == 'crop' and row['end'] == 3 for row in plan['segments'])
    assert all(row['mode'] == 'full_frame_blur' for row in plan['segments'] if row['start'] >= 3)
    assert any(row['reason'] == 'PROTECTED_SOURCE_CONTENT' for row in plan['segments'])


def test_camera_source_mismatch_is_rejected():
    result = normalise_production_evidence(container())
    with pytest.raises(ValueError, match='another source'):
        build_piece_camera(result['visual_index'], result['pieces'][0], {**result['evidence']['metadata'], 'sha256': 'c' * 64})


def test_bridge_clips_zoom_to_original_time_and_uses_existing_renderer():
    source = director(0, 10)
    source['camera']['zoom_end'] = 1.04
    plan = use_analyzer_director([source], 5, 10)
    row = plan['segments'][0]
    assert row['zoom_start'] == pytest.approx(1.02)
    assert row['zoom_end'] == 1.04
    assert row['zoom_transition_duration'] == 5
    assert row['source_director_start'] == 0 and row['source_director_end'] == 10
    from ldporto_curator.render import _motion_crop_filter
    graph = _motion_crop_filter('src', row, 1920, 1080, 1080, 1920, 0)
    assert 'eval=frame' in graph and '1.02000000' in graph


def test_renderer_limit_is_explicit_fallback_not_flattened_zoom():
    package = container()
    row = director()
    row['camera']['zoom_end'] = 1.12
    package['files']['camera/camera_director_timeline.json'] = payload([row])
    result = normalise_production_evidence(package)
    plan = build_piece_camera(result['visual_index'], result['pieces'][0], result['evidence']['metadata'])
    assert all(row['mode'] == 'full_frame_blur' for row in plan['segments'])
    assert plan['segments'][1]['reason'] == 'ANALYZER_ZOOM_EXCEEDS_EXISTING_RENDERER_ENVELOPE'


def test_assets_resolve_only_inside_verified_staging_and_no_files_are_written(tmp_path):
    package = container()
    package['root'] = tmp_path
    package['files']['frames/a.jpg'] = b'known-image-bytes'
    (tmp_path / 'frames').mkdir()
    asset = tmp_path / 'frames/a.jpg'
    asset.write_bytes(package['files']['frames/a.jpg'])
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    result = normalise_production_evidence(package)
    assert result['visual_index']['assets']['frames/a.jpg']['path'] == str(asset.resolve())
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    asset.write_bytes(b'changed')
    with pytest.raises(ValueError, match='asset SHA256'):
        normalise_production_evidence(package)


def test_native_uses_existing_verified_evidence_loader(monkeypatch):
    import ldporto_curator.production_evidence as module
    package = container()
    expected = normalise_production_evidence(package)['evidence']
    calls = []
    monkeypatch.setattr(module, 'load_evidence', lambda path: calls.append(path) or deepcopy(expected))
    package.update(format='ANALYZER_NATIVE', path='already-verified.zip')
    normalise_production_evidence(package)
    assert calls == ['already-verified.zip']


def test_contact_sheet_samples_and_tracklets_are_retained_without_fake_frames():
    package = container()
    candidates = json.loads(package['files']['editorial/candidate_catalog.json'])
    candidates['candidates'][0].update(visual_refs=['visuals/A/contact_sheet.jpg'],
        visual_metadata={'frames': [{'time': 2.5, 'camera_mode': 'SOURCE_PRESERVE'}, {'time': 4., 'camera_mode': 'STATIC_MEDIUM'}]})
    package['files']['editorial/candidate_catalog.json'] = payload(candidates)
    package['files']['visuals/A/contact_sheet.jpg'] = b'contact-sheet'
    package['files']['people/person_tracks.json'] = payload([{'track_id': 'T', 'first_seen': 2., 'last_seen': 4., 'person_id': 'P'}])
    result = normalise_production_evidence(package)
    index = result['visual_index']
    assert len(index['frames']) == 2 and len(index['tracks']) == 1
    assert index['frames'][0]['time'] == 2.5
    assert index['frames'][0]['asset_kind'] == 'contact_sheet_not_individual_decoded_frame'
    assert index['frames'][0]['asset_paths'] == []
    assert index['frames'][0]['asset_refs'] == ['visuals/A/contact_sheet.jpg']
    assert result['evidence']['availability']['frame_samples']['count'] == 2


def test_compact_shared_handoff_does_not_replace_a_real_director_certificate():
    package = container()
    enriched = handoff(package, [])
    enriched['files']['05_CAMERAS/camera_timeline.json'] = payload({'segments': [
        {'start': 2., 'end': 4., 'layout': 'single_person', 'crop': {'safe': True}, 'camera': director()['camera']}]})
    result = normalise_production_evidence(package, handoff=enriched)
    assert result['visual_index']['director'][0]['camera_evidence_role'] == 'DOMINANT_FACE'
    assert result['visual_index']['director'][0]['focus_person'] == 'P'


def test_verified_curator_ready_uses_declared_pieces_and_existing_render_plans():
    package = container()
    evidence = normalise_production_evidence(package)['evidence']
    evidence['audio_events'] = [{'start': 2., 'end': 5., 'category': 'NO_SPEECH', 'source_sha256': SOURCE}]
    plan = {'mode': 'adaptive_timeline', 'segments': [{'start': 0., 'end': 3., 'mode': 'full_frame_blur'}]}
    package.update(evidence=evidence, pieces=[{'piece_id': 'MANUAL_STORY', 'kind': 'story',
        'source_start': 2., 'source_end': 5., 'duration': 3., 'series_id': 'S', 'order': 1,
        'editorial': {'title': 'Declared title'}, 'camera_plan': plan,
        'documents': {'source_segments': {'segments': [{'start': 2., 'end': 5.}]}},
        'caption_plan': {'allowed_caption_mode': 'none'}}])
    result = normalise_production_evidence(package)
    assert result['evidence']['audio_events'] == evidence['audio_events']
    assert len(result['pieces']) == 1 and result['pieces'][0]['episode_id'] == 'MANUAL_STORY'
    piece = result['pieces'][0]
    assert piece['title'] == 'Declared title'
    actual = build_piece_camera(result['visual_index'], piece, package['metadata'])
    assert actual['segments'] == plan['segments'] and actual['human_approved'] is False
