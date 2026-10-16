"""Revision persistence/gate integrity; all writes are isolated in pytest temp dirs."""
from copy import deepcopy
from dataclasses import fields
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ldporto_curator.analysis_loader import AnalysisBundle
from ldporto_curator.persisted_plan import (
    PlanStore, StalePlanError, canonical, compare_settings,
    editorial_fingerprint, project_lock, render_fingerprint,
    render_settings, source_fingerprint,
)


def bundle(tmp_path):
    dictionaries = {'analysis', 'insights', 'review', 'second_package', 'second_decisions'}
    values = {field.name: ({} if field.name in dictionaries else [])
              for field in fields(AnalysisBundle)}
    values.update(
        root=tmp_path / 'unavailable_original_analysis', video_id='fixture_p0',
        analysis={'metadata': {'sha256': 'a' * 64, 'duration': 120,
                              'source': {'id': 'fixture_p0', 'url': 'https://example.invalid/video',
                                         'filename': 'original.mp4'}},
                  'created_at': 'old diagnostic time'},
        segments=[{'start': 0, 'end': 30, 'text': 'Existing literal speech.', 'confidence': .8}],
        captions=[{'start': 0, 'end': 30, 'text': 'Existing literal speech.',
                   'words': [{'start': 0, 'end': 1, 'word': 'Existing'}]}],
        words=[{'start': 0, 'end': 1, 'word': 'Existing'}],
    )
    return AnalysisBundle(**values)


def decisions(count=2):
    return [
        {'clip_id': f'CLIP_{i + 1:03d}', 'rank': i + 1,
         'source_start': 30 * i, 'source_end': 30 * (i + 1), 'duration': 30,
         'title_text': 'Literal title', 'title_duration': 3.2,
         'camera_plan': {'mode': 'adaptive_timeline', 'diagnostics': {'count': 7},
                         'segments': [{'start': 0, 'end': 30, 'mode': 'crop',
                                       'center_x': .5, 'zoom': 1.0}]},
         'subtitle_plan': {'margin_v_final': 320}, 'reason': 'editorial rationale'}
        for i in range(count)
    ]


def cfg(tmp_path):
    return {'paths': {'analysis_root': str(tmp_path / 'unavailable_original_analysis'),
                      'output_root': str(tmp_path / 'output'), 'source_cache': str(tmp_path / 'media')},
            'render': {'preview_width': 540, 'preview_height': 960, 'audio_lufs': -14},
            'subtitles': {'font': 'Segoe UI', 'font_size_final': 72},
            'title': {'duration': 3.2}, 'camera': {'strategy': 'conservative'},
            'ollama': {'enabled': True, 'model': 'must-never-be-called'},
            'curation': {'max_approved_clips': 12}}


def created(tmp_path, count=2):
    store = PlanStore(tmp_path / 'project')
    config = cfg(tmp_path)
    document, cached = store.create(bundle(tmp_path), decisions(count), config, 'fixture_p0')
    return store, document, cached, config


def test_create_reload_uses_cached_bundle_without_any_analyzer_access(tmp_path, monkeypatch):
    store, document, cached, config = created(tmp_path)
    import ldporto_curator.analysis_loader as loader
    monkeypatch.setattr(loader, 'load_bundle', lambda *_: pytest.fail('Read Analyzer after curation'))
    monkeypatch.setattr(loader, 'find_analysis', lambda *_: pytest.fail('Searched Analyzer after curation'))
    reopened = PlanStore(store.base_dir)
    restored, restored_bundle = reopened.load(config)
    assert restored['plan_revision'] == document['plan_revision']
    assert restored_bundle.root == reopened.revision_dir(restored)
    assert restored_bundle.root != bundle(tmp_path).root
    assert restored_bundle.captions == cached.captions == bundle(tmp_path).captions
    assert source_fingerprint(restored_bundle) == restored['source_fingerprint']
    assert restored['approval_record'] is None and restored['preview'] is None


def test_state_roundtrip_survives_new_instance_and_keeps_fingerprints(tmp_path):
    store, doc, _, config = created(tmp_path)
    signatures = {k: doc[k] for k in ('source_fingerprint', 'editorial_plan_fingerprint', 'plan_signature')}
    doc['preview'] = {'path': 'revisions/test/preview.mp4', 'sha256': 'test-record-only'}
    doc['approval_state'] = 'PREVIEW_READY'
    doc = store.save_state(doc, expected_revision=doc['plan_revision'])
    doc['approval_record'] = {'human_reviewed': True, 'plan_revision': doc['plan_revision']}
    doc['approval_state'] = 'TEST_APPROVED'
    doc = store.save_state(doc)
    loaded, _ = PlanStore(store.base_dir).load(config)
    assert loaded == doc
    assert loaded['state_version'] == 2
    assert {k: loaded[k] for k in signatures} == signatures
    assert len(list((store.revision_dir(doc) / 'states').glob('*.json'))) == 3


def test_explicit_seven_to_three_recures_without_overwriting_previous_revision(tmp_path):
    store, first, _, config = created(tmp_path, 7)
    first['approval_state'] = 'TEST_APPROVED'
    first = store.save_state(first)
    previous_state = (store.revision_dir(first) / 'STATE.json').read_bytes()
    second, _ = store.create(bundle(tmp_path), decisions(3), config, 'fixture_p0')
    assert second['plan_revision'] != first['plan_revision']
    assert second['editorial_plan_fingerprint'] != first['editorial_plan_fingerprint']
    assert second['approval_state'] == 'PLAN_READY' and second['approval_record'] is None
    assert (store.revision_dir(first) / 'STATE.json').read_bytes() == previous_state
    with pytest.raises(StalePlanError, match='Revisão obsoleta'):
        store.save_state(first)
    assert store.load()[0]['plan_revision'] == second['plan_revision']


def test_delayed_callback_same_revision_cannot_overwrite_newer_state(tmp_path):
    store, original, _, _ = created(tmp_path)
    delayed = deepcopy(original)
    original['approval_state'] = 'PREVIEW_READY'
    current = store.save_state(original)
    delayed['approval_state'] = 'PLAN_READY'
    with pytest.raises(StalePlanError, match='obsoleto'):
        PlanStore(store.base_dir).save_state(delayed)
    assert store.load()[0] == current


@pytest.mark.parametrize('field,value', [
    ('source_start', .1), ('source_end', 29.9), ('duration', 29),
    ('title_text', 'Changed actual title'), ('title_duration', 8),
    ('subtitle_plan', {'margin_v_final': 500}), ('audio_mode', 'normalize'),
])
def test_real_render_input_edit_rejected_with_exact_field(tmp_path, field, value):
    store, doc, _, _ = created(tmp_path)
    doc['approved_clips'][1][field] = value
    with pytest.raises(StalePlanError, match=r'editorial_projection\[1\]\.' + field):
        store.save_state(doc)
    assert store.load()[0]['approval_state'] == 'PLAN_READY'


def test_crop_of_unreviewed_clip_is_bound_to_whole_batch(tmp_path):
    store, doc, _, _ = created(tmp_path)
    old = doc['editorial_plan_fingerprint']
    doc['approved_clips'][1]['camera_plan']['segments'][0]['center_x'] = .8
    assert editorial_fingerprint(doc['approved_clips']) != old
    with pytest.raises(StalePlanError, match=r'camera_plan\.segments\[0\]\.center_x'):
        store.save_state(doc)


def test_model_routing_paths_and_visual_diagnostics_do_not_invalidate_settings(tmp_path):
    store, doc, _, config = created(tmp_path)
    other = deepcopy(config)
    other['paths'] = {'output_root': 'moved-only', 'analysis_root': 'must-not-read'}
    other['ollama'] = {'enabled': False, 'model': 'unavailable'}
    other['curation']['max_approved_clips'] = 3
    doc['approved_clips'][0]['camera_plan']['diagnostics']['count'] = 99
    doc['approved_clips'][0]['camera_plan']['segments'][0]['observed_at'] = 'new time'
    doc['approved_clips'][0]['reason'] = 'New display explanation'
    assert compare_settings(doc, other) == []
    saved = store.save_state(doc)
    assert store.load(other)[0]['plan_signature'] == saved['plan_signature']


def test_settings_change_names_exact_field_without_touching_saved_state(tmp_path):
    store, doc, _, config = created(tmp_path)
    changed = deepcopy(config)
    changed['subtitles']['font'] = 'Arial'
    with pytest.raises(ValueError, match=r'subtitles\.font'):
        store.load(changed)
    assert store.load(changed, check_settings=False)[0] == doc


def test_font_location_change_preserves_identity_but_content_change_invalidates(tmp_path):
    a, b = tmp_path / 'a.ttf', tmp_path / 'b.ttf'
    a.write_bytes(b'controlled-font-file'); b.write_bytes(a.read_bytes())
    config = {'title': {'font_path': str(a)}}
    pinned = render_settings(config)
    assert compare_settings(pinned, {'title': {'font_path': str(b)}}) == []
    b.write_bytes(b'different-font-file')
    with pytest.raises(ValueError, match='font_file_sha256'):
        compare_settings(pinned, {'title': {'font_path': str(b)}})


def test_canonical_policy_normalizes_float_integer_key_order_and_diagnostics(tmp_path):
    rows = decisions()
    changed = deepcopy(rows)
    changed[0]['source_start'] = 0.0
    changed[0]['duration'] = 30.00000000001
    changed[0]['camera_plan']['diagnostics'] = {'elapsed_seconds': 50}
    changed[0]['camera_plan']['segments'][0]['confidence'] = .01
    changed[0] = dict(reversed(list(changed[0].items())))
    assert editorial_fingerprint(rows) == editorial_fingerprint(changed)
    assert canonical({'b': 1.0, 'a': -.0}) == {'a': 0, 'b': 1}
    source = bundle(tmp_path); equivalent = deepcopy(source)
    equivalent.root = tmp_path / 'moved_original_reference'
    equivalent.analysis['created_at'] = 'different volatile time'
    equivalent.segments[0]['confidence'] = .1
    assert source_fingerprint(source) == source_fingerprint(equivalent)


@pytest.mark.parametrize('number', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_values_fail_before_publishing_revision(tmp_path, number):
    store = PlanStore(tmp_path / 'project')
    rows = decisions(); rows[0]['duration'] = number
    with pytest.raises(ValueError, match='não finito'):
        store.create(bundle(tmp_path), rows, cfg(tmp_path), 'fixture_p0')
    assert not store.pointer.exists()


@pytest.mark.parametrize('mutation', ['media_sha256', 'caption_text', 'caption_timing', 'word_timing'])
def test_source_fingerprint_binds_actual_source_and_spoken_captions(tmp_path, mutation):
    original = bundle(tmp_path); changed = deepcopy(original)
    if mutation == 'media_sha256':
        changed.analysis['metadata']['sha256'] = 'b' * 64
    elif mutation == 'caption_text':
        changed.captions[0]['text'] = 'Different literal text'
    elif mutation == 'caption_timing':
        changed.captions[0]['end'] = 29
    else:
        changed.captions[0]['words'][0]['end'] = 2
    assert source_fingerprint(original) != source_fingerprint(changed)


def test_render_fingerprint_binds_revision_media_encoder_and_clip(tmp_path):
    store, doc, _, config = created(tmp_path)
    original = render_fingerprint(doc, 'CLIP_001', 'source-media-a', 'renderer-a')
    assert render_fingerprint(doc, 'CLIP_001', 'source-media-b', 'renderer-a') != original
    assert render_fingerprint(doc, 'CLIP_001', 'source-media-a', 'renderer-b') != original
    assert render_fingerprint(doc, 'CLIP_002', 'source-media-a', 'renderer-a') != original
    second, _ = store.create(bundle(tmp_path), decisions(), config, 'fixture_p0')
    assert second['editorial_plan_fingerprint'] == doc['editorial_plan_fingerprint']
    assert render_fingerprint(second, 'CLIP_001', 'source-media-a', 'renderer-a') != original
    with pytest.raises(ValueError, match='Clip não pertence'):
        render_fingerprint(doc, 'CLIP_OTHER', 'source-media-a', 'renderer-a')


def test_legacy_files_archived_byte_for_byte_without_inheriting_approval(tmp_path):
    store = PlanStore(tmp_path / 'project'); store.base_dir.mkdir()
    files = {'EDIT_DECISIONS.json': b'{"approved_clips":[]}',
             'PREVIEW_REVIEW_V44.json': b'{"path":"legacy.mp4"}',
             'FIRST_TEST_APPROVED.flag': b'approved\n',
             'FIRST_TEST_APPROVED_V44.json': b'{"legacy":true}',
             'CHATGPT_HANDOFF.json': b'{"legacy_handoff":true}'}
    for name, raw in files.items():
        (store.base_dir / name).write_bytes(raw)
    doc, _ = store.create(bundle(tmp_path), decisions(), cfg(tmp_path), 'fixture_p0')
    archive = store.revision_dir(doc) / 'legacy_archive'
    assert {name: (archive / name).read_bytes() for name in files} == files
    assert doc['approval_state'] == 'PLAN_READY' and doc['approval_record'] is None
    assert doc['preview'] is None
    for name, raw in files.items():
        if name != 'EDIT_DECISIONS.json':
            assert (store.base_dir / name).read_bytes() == raw


@pytest.mark.parametrize('target', ['analysis_snapshot', 'plan_inputs'])
def test_immutable_snapshot_and_inputs_tamper_blocks_reload(tmp_path, target):
    store, doc, _, _ = created(tmp_path)
    path = store.base_dir / doc[target]
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='mudaram|mudou'):
        store.load()


def test_active_pointer_cannot_reference_external_snapshot(tmp_path):
    store, doc, _, _ = created(tmp_path)
    doc['analysis_snapshot'] = '../external-analysis.json'
    store.pointer.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='Referência do plano inválida'):
        store.load()


def test_active_editorial_json_tamper_names_changed_field(tmp_path):
    store, doc, _, _ = created(tmp_path)
    doc['approved_clips'][0]['duration'] = 900
    store.pointer.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(StalePlanError, match=r'editorial_projection\[0\]\.duration'):
        store.load()


def test_failed_atomic_pointer_publish_keeps_prior_state_loadable(tmp_path, monkeypatch):
    store, doc, _, _ = created(tmp_path)
    original = store.pointer.read_bytes()
    import ldporto_curator.persisted_plan as module
    replace = module.os.replace
    def fail_pointer(source, destination):
        if Path(destination) == store.pointer:
            raise OSError('Controlled pointer publication failure')
        return replace(source, destination)
    monkeypatch.setattr(module.os, 'replace', fail_pointer)
    doc['approval_state'] = 'PREVIEW_READY'
    with pytest.raises(OSError, match='Controlled'):
        store.save_state(doc)
    assert store.pointer.read_bytes() == original
    assert store.load()[0]['approval_state'] == 'PLAN_READY'
    assert not list(store.base_dir.glob('.*.tmp'))
    assert len(list((store.revision_dir(doc) / 'states').glob('*.json'))) == 2


def test_live_owner_same_pid_and_other_thread_dispatch_are_not_displaced(tmp_path):
    base = tmp_path / 'project'
    with project_lock(base):
        with pytest.raises(RuntimeError, match='Outra operação'):
            with project_lock(base):
                pytest.fail('Concurrent mutation acquired lock')
    with project_lock(base):
        pass
    assert not (base / '.PLAN_OPERATION.lock').exists()


def _lock_child(base):
    code = ('from pathlib import Path; import sys; '
            'from ldporto_curator.persisted_plan import project_lock; '
            'context=project_lock(Path(sys.argv[1])); context.__enter__(); '
            'print("locked",flush=True); sys.stdin.read(); context.__exit__(None,None,None)')
    return subprocess.Popen([sys.executable, '-c', code, str(base)],
                            cwd=Path(__file__).resolve().parents[1],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def test_real_crossprocess_live_lock_rejected_and_dead_pid_reclaimed(tmp_path):
    base = tmp_path / 'project'
    process = _lock_child(base)
    try:
        assert process.stdout.readline().strip() == 'locked', process.stderr.read()
        with pytest.raises(RuntimeError, match='Outra operação'):
            with project_lock(base):
                pytest.fail('Live process was displaced')
        process.kill(); process.wait(timeout=10)
        assert (base / '.PLAN_OPERATION.lock').exists()
        with project_lock(base) as owner:
            assert owner['pid'] == os.getpid()
        assert not (base / '.PLAN_OPERATION.lock').exists()
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)


def test_lock_release_never_deletes_replacement_owners_token(tmp_path):
    base = tmp_path / 'project'
    with project_lock(base):
        path = base / '.PLAN_OPERATION.lock'
        path.write_text(json.dumps({'pid': os.getpid(), 'token': 'replacement'}), encoding='utf-8')
    assert json.loads(path.read_text())['token'] == 'replacement'


def test_unknown_lock_owner_is_preserved_instead_of_assuming_it_dead(tmp_path):
    base = tmp_path / 'project'; base.mkdir()
    path = base / '.PLAN_OPERATION.lock'
    path.write_text(json.dumps({'pid': None, 'token': 'unknown'}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='Outra operação'):
        with project_lock(base):
            pass
    assert path.exists()


def test_boolean_setting_is_not_canonicalized_as_the_number_one():
    with pytest.raises(ValueError, match=r'render\.prefer_nvenc'):
        compare_settings({'render': {'prefer_nvenc': True}}, {'render': {'prefer_nvenc': 1}})


def test_recovery_guard_left_by_dead_process_is_also_recoverable(tmp_path):
    base = tmp_path / 'project'
    process = _lock_child(base)
    try:
        assert process.stdout.readline().strip() == 'locked', process.stderr.read()
        old_owner = json.loads((base / '.PLAN_OPERATION.lock').read_text())
        process.kill(); process.wait(timeout=10)
        guard = base / '.PLAN_OPERATION.lock.reclaim'
        guard.write_text(json.dumps(old_owner), encoding='utf-8')
        with project_lock(base):
            assert not guard.exists()
        assert not (base / '.PLAN_OPERATION.lock').exists()
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)
