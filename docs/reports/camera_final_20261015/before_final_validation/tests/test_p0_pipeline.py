"""Real Pipeline state transitions with bounded, controlled renderer fixtures.

Only media encoding/curation inputs are substituted. Persistence, fingerprints,
approval file contracts, locks and recovery execute their production code.
"""
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import threading

import pytest

from ldporto_curator.analysis_loader import AnalysisBundle
from ldporto_curator.persisted_plan import (
    PlanStore, StalePlanError, project_lock, render_settings, _fingerprint,
)
from ldporto_curator.source_video import SourceUnavailable
from ldporto_curator import pipeline


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled-original-source-bytes-not-a-decoder-fixture')
    media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    dictionaries = {'analysis', 'insights', 'review', 'second_package', 'second_decisions'}
    values = {field.name: ({} if field.name in dictionaries else [])
              for field in fields(AnalysisBundle)}
    values.update(root=tmp_path / 'completed_analysis_fixture', video_id='p0_fixture',
                  analysis={'metadata': {'sha256': media_sha, 'duration': 240,
                                        'source': {'id': 'p0_fixture', 'filename': 'source.mp4',
                                                   'url': 'https://example.invalid/completed-video'}}},
                  captions=[{'start': 0, 'end': 30, 'text': 'Literal existing speech.'}],
                  segments=[{'start': 0, 'end': 30, 'text': 'Literal existing speech.'}])
    analysis = AnalysisBundle(**values)
    config = {'paths': {'analysis_root': str(analysis.root), 'output_root': str(tmp_path / 'output'),
                        'source_cache': str(tmp_path / 'source_cache')},
              'source_media': {'path': str(source)},
              'render': {'preview_width': 540, 'preview_height': 960, 'final_width': 1080,
                         'final_height': 1920, 'audio_lufs': -14, 'audio_true_peak': -1.5},
              'subtitles': {'font': 'Segoe UI', 'font_size_final': 72},
              'title': {'duration': 3.2}, 'camera': {'v44_refinement': False},
              'ollama': {'enabled': True},
              'safety': {'require_first_test_approval_before_batch': True}}
    state = {'curations': 0, 'analysis_reads': 0, 'count': 7, 'rendered': [],
             'camera_builds': 0, 'effective_metadata_changes': {}, 'events': []}
    def read_bundle(_):
        state['analysis_reads'] += 1
        return deepcopy(analysis)
    def select(*args, **kwargs):
        state['curations'] += 1
        return [{'clip_id': f'CLIP_{i + 1:03d}', 'rank': i + 1,
                 'source_start': i * 30, 'source_end': (i + 1) * 30, 'duration': 30,
                 'title_text': f'Literal title {i + 1}', 'title_duration': 3.2,
                 'curation_source': 'FIRST_PASS', 'reason': 'Existing evidence'}
                for i in range(state['count'])]
    def camera(*args, **kwargs):
        state['camera_builds'] += 1
        return {'mode': 'adaptive_timeline', 'segments': [
            {'start': 0, 'end': 30, 'mode': 'crop', 'center_x': .5, 'zoom': 1}]}
    def render(bundle, clip, video, out, cfg, preview=True, **kwargs):
        out.mkdir(parents=True, exist_ok=True)
        media = out / (clip['clip_id'] + ('_PREVIEW.mp4' if preview else '_FINAL.mp4'))
        payload = {'clip': clip, 'captions': bundle.captions, 'preview': preview}
        media.write_bytes(json.dumps(payload, sort_keys=True).encode())
        descriptor = {'encoder': 'libx264', 'preview': preview,
                      'width': cfg['render']['preview_width' if preview else 'final_width'],
                      'height': cfg['render']['preview_height' if preview else 'final_height'],
                      'duration': clip['duration'], 'source_start': clip['source_start'],
                      'render_settings_fingerprint': _fingerprint(render_settings(cfg)),
                      'subtitle_sha256': 'controlled-ass-hash', 'title_card_sha256': None,
                      'media_sha256': hashlib.sha256(media.read_bytes()).hexdigest()}
        descriptor.update(state['effective_metadata_changes'])
        Path(str(media) + '.render.json').write_text(json.dumps(descriptor), encoding='utf-8')
        state['rendered'].append({'clip_id': clip['clip_id'], 'clip': deepcopy(clip),
                                  'path': media, 'preview': preview, 'bundle_root': bundle.root})
        return media
    monkeypatch.setattr(pipeline, 'find_analysis', lambda *_: analysis.root)
    monkeypatch.setattr(pipeline, 'load_bundle', read_bundle)
    monkeypatch.setattr(pipeline, 'curate', select)
    monkeypatch.setattr(pipeline, 'build_camera_plan', camera)
    monkeypatch.setattr(pipeline, 'render_clip', render)
    monkeypatch.setattr(pipeline, 'create_assets', lambda *a, **k: {})
    monkeypatch.setattr(pipeline, 'build_board', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'write_handoff', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'renderer_signature', lambda: 'controlled-renderer-signature')
    root = tmp_path / 'workspace'; root.mkdir()
    def fresh(cfg=None):
        return pipeline.Pipeline(cfg or config, root, log=lambda *_: None, progress=state['events'].append)
    state.update(source=source, source_input='p0_fixture', config=config, fresh=fresh,
                 store=PlanStore(tmp_path / 'output/curation/p0_fixture'))
    return state


def curate(workflow):
    workflow['fresh']().curate_only(workflow['source_input'])
    return workflow['store'].load()[0]


def preview(workflow):
    curate(workflow)
    workflow['fresh']().test_one(workflow['source_input'])
    return workflow['store'].load()[0]


def approved(workflow):
    preview(workflow)
    workflow['fresh']().approve_test(workflow['source_input'])
    return workflow['store'].load()[0]


def test_full_seven_clip_workflow_with_reopen_every_step_and_qwen_unavailable(workflow, monkeypatch):
    initial = curate(workflow)
    monkeypatch.setattr(pipeline, 'find_analysis', lambda *_: pytest.fail('Downstream searched Analyzer'))
    monkeypatch.setattr(pipeline, 'load_bundle', lambda *_: pytest.fail('Downstream read Analyzer'))
    monkeypatch.setattr(pipeline, 'curate', lambda *a, **k: pytest.fail('Downstream called Qwen/curation'))
    monkeypatch.setattr(pipeline, 'build_camera_plan', lambda *a, **k: pytest.fail('Downstream rebuilt camera'))
    src = workflow['source_input']
    workflow['fresh']().test_one(src)
    tested = workflow['store'].load()[0]
    assert tested['approval_state'] == 'PREVIEW_READY' and tested['approval_record'] is None
    with pytest.raises(ValueError, match='não foi aprovado'):
        workflow['fresh']().render_all(src)
    workflow['fresh']().approve_test(src)
    before_batch = workflow['fresh']().read_state(src)
    results, _ = workflow['fresh']().render_all(src)
    final = workflow['store'].load()[0]
    assert len(results) == 7 and final['approval_state'] == 'BATCH_COMPLETED'
    assert before_batch['approval_state'] == 'TEST_APPROVED'
    assert final['approval_record'] == before_batch['approval_record']
    assert workflow['curations'] == workflow['analysis_reads'] == 1
    assert workflow['camera_builds'] == 7
    assert {row['plan_revision'] for row in final['results']} == {initial['plan_revision']}
    assert {initial['plan_revision'], tested['plan_revision'], final['plan_revision']} == {initial['plan_revision']}
    assert final['plan_signature'] == tested['plan_signature'] == initial['plan_signature']
    assert all(initial['plan_revision'] in str(item['path']) for item in workflow['rendered'])


def test_explicit_recuration_to_three_preserves_old_approval_and_blocks_new_batch(workflow):
    old = approved(workflow)
    old_revision = workflow['store'].revision_dir(old)
    approval_bytes = (old_revision / 'FIRST_TEST_APPROVED_V44.json').read_bytes()
    workflow['count'] = 3
    current = curate(workflow)
    assert current['previous_revision'] == old['plan_revision']
    assert current['plan_revision'] != old['plan_revision']
    assert 'Nova CURAR explícita' in current['invalidation_reason']
    assert len(current['approved_clips']) == 3 and current['approval_record'] is None
    assert (old_revision / 'FIRST_TEST_APPROVED_V44.json').read_bytes() == approval_bytes
    with pytest.raises(ValueError, match='não foi aprovado'):
        workflow['fresh']().render_all(workflow['source_input'])
    assert workflow['curations'] == 2


@pytest.mark.parametrize('action', ['test_one', 'approve_test', 'render_all', 'read_state'])
def test_missing_plan_never_implicitly_curates(workflow, action):
    with pytest.raises(FileNotFoundError, match='SEM_PLANO'):
        getattr(workflow['fresh'](), action)(workflow['source_input'])
    assert workflow['curations'] == workflow['analysis_reads'] == 0


def test_wrong_rank_does_not_fall_back_to_another_clip(workflow):
    doc = curate(workflow)
    with pytest.raises(ValueError, match='Rank 99 não existe'):
        workflow['fresh']().test_one(workflow['source_input'], rank=99)
    assert not workflow['rendered']
    assert workflow['store'].load()[0] == doc


def test_source_bytes_changed_after_approval_block_before_batch_render(workflow):
    doc = approved(workflow)
    rendered = len(workflow['rendered'])
    workflow['source'].write_bytes(b'different original bytes at same path')
    with pytest.raises(ValueError, match=r'source_media\.sha256'):
        workflow['fresh']().render_all(workflow['source_input'])
    assert len(workflow['rendered']) == rendered
    invalid = workflow['store'].load()[0]
    assert invalid['approval_state'] == 'APPROVAL_INVALIDATED'
    assert invalid['approval_record'] == doc['approval_record']
    assert invalid['plan_signature'] == doc['plan_signature']
    assert workflow['events'][-1]['approval_state'] == 'APPROVAL_INVALIDATED'
    assert 'source_media.sha256' in workflow['events'][-1]['invalidation_reason']


def test_approval_uses_preview_exclusively_when_original_is_offline(workflow):
    doc = preview(workflow)
    # Move only our pytest-owned source fixture out of the configured route.
    offline = workflow['source'].with_suffix('.offline')
    workflow['source'].rename(offline)
    workflow['fresh']().approve_test(workflow['source_input'])
    approved_doc = workflow['store'].load()[0]
    assert approved_doc['approval_state'] == 'TEST_APPROVED'
    assert approved_doc['plan_revision'] == doc['plan_revision']
    with pytest.raises(SourceUnavailable, match='original indisponível'):
        workflow['fresh']().render_all(workflow['source_input'])
    assert workflow['curations'] == 1 and len(workflow['rendered']) == 1


@pytest.mark.parametrize('stage', ['approve_test', 'render_all'])
@pytest.mark.parametrize('asset', ['media', 'metadata'])
def test_preview_or_effective_sidecar_tamper_blocks_gate(workflow, stage, asset):
    doc = preview(workflow) if stage == 'approve_test' else approved(workflow)
    record = doc['preview']
    target = record['path'] if asset == 'media' else record['render_metadata_path']
    Path(target).write_bytes(b'changed after reviewed encoding')
    rendered = len(workflow['rendered'])
    with pytest.raises(ValueError, match='sha256'):
        getattr(workflow['fresh'](), stage)(workflow['source_input'])
    assert len(workflow['rendered']) == rendered


def test_approval_record_tamper_never_releases_batch(workflow):
    doc = approved(workflow)
    folder = workflow['store'].revision_dir(doc)
    path = folder / 'FIRST_TEST_APPROVED_V44.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    record['binding']['plan_revision'] = 'different-revision'
    path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError, match='Registro de aprovação mudou'):
        workflow['fresh']().render_all(workflow['source_input'])
    assert len(workflow['rendered']) == 1


@pytest.mark.parametrize('section,field,value', [
    ('subtitles', 'font', 'Arial'), ('title', 'duration', 9),
    ('render', 'audio_lufs', -18), ('camera', 'v44_refinement', True),
])
def test_real_effect_settings_change_names_field_and_does_not_recurate(workflow, section, field, value):
    doc = approved(workflow)
    modified = deepcopy(workflow['config']); modified[section][field] = value
    with pytest.raises(ValueError, match=section + r'\.' + field):
        workflow['fresh'](modified).render_all(workflow['source_input'])
    assert workflow['curations'] == 1 and len(workflow['rendered']) == 1
    assert workflow['store'].load()[0] == doc
    assert workflow['events'][-1]['approval_state'] == 'APPROVAL_INVALIDATED'


def test_read_only_reopen_model_and_analyzer_routing_change_keep_approval(workflow):
    doc = approved(workflow)
    modified = deepcopy(workflow['config'])
    modified['paths']['analysis_root'] = 'must never search this folder'
    modified['ollama'] = {'enabled': False, 'model': 'unavailable-after-curation'}
    modified['curation'] = {'max_approved_clips': 3}
    for _ in range(3):
        assert workflow['fresh'](modified).read_state(workflow['source_input']) == doc
    workflow['fresh'](modified).render_all(workflow['source_input'])
    assert workflow['curations'] == 1


def test_pipeline_captures_deep_config_snapshot(workflow):
    supplied = deepcopy(workflow['config'])
    instance = workflow['fresh'](supplied)
    supplied['render']['audio_lufs'] = -30
    supplied['paths']['output_root'] = 'changed-after-worker-start'
    supplied['source_media']['path'] = 'absent-media.mp4'
    instance.curate_only(workflow['source_input'])
    doc = workflow['store'].load()[0]
    assert doc['render_settings']['render']['audio_lufs'] == -14
    assert doc['source_media_path'] == str(workflow['source'].resolve())


@pytest.mark.parametrize('action', ['test_one', 'approve_test', 'render_all'])
def test_project_operation_lock_blocks_repeated_workers_before_outputs(workflow, action):
    approved(workflow)
    before = len(workflow['rendered'])
    with project_lock(workflow['store'].base_dir):
        with pytest.raises(RuntimeError, match='Outra operação'):
            getattr(workflow['fresh'](), action)(workflow['source_input'])
    assert len(workflow['rendered']) == before


def test_retesting_does_not_reuse_old_approval_and_preserves_previous_mp4(workflow):
    old = approved(workflow)
    prior = Path(old['preview']['path']); before = prior.read_bytes()
    workflow['fresh']().test_one(workflow['source_input'], rank=2)
    new = workflow['store'].load()[0]
    assert new['preview']['reviewed_clip_id'] == 'CLIP_002'
    assert new['plan_revision'] == old['plan_revision']
    assert new['approval_record'] is None and new['approval_state'] == 'PREVIEW_READY'
    assert prior.read_bytes() == before
    with pytest.raises(ValueError, match='não foi aprovado'):
        workflow['fresh']().render_all(workflow['source_input'])


@pytest.mark.parametrize('field,value', [('source_start', 999), ('duration', 999),
                                        ('width', 123), ('height', 123),
                                        ('encoder', 'unapproved-codec'),
                                        ('render_settings_fingerprint', 'different-settings')])
def test_effective_renderer_metadata_must_match_approved_inputs(workflow, field, value):
    # A renderer claiming different effective inputs must never be approved,
    # even when its media and sidecar hashes themselves are internally valid.
    workflow['effective_metadata_changes'] = {field: value}
    preview(workflow)
    with pytest.raises(ValueError, match='(?i)' + field):
        workflow['fresh']().approve_test(workflow['source_input'])


def test_explicit_timestamp_crop_and_caption_settings_edit_creates_revision_without_qwen(workflow, monkeypatch):
    original = approved(workflow)
    selected = deepcopy(original['approved_clips'])
    selected[0].update(source_start=.1, source_end=29.9, duration=29.8)
    selected[0]['camera_plan']['segments'][0].update(end=29.8, center_x=.8)
    changed_cfg = deepcopy(workflow['config']); changed_cfg['subtitles']['font'] = 'Arial'
    monkeypatch.setattr(pipeline, 'curate', lambda *a, **k: pytest.fail('Edit invoked Qwen'))
    monkeypatch.setattr(pipeline, 'load_bundle', lambda *_: pytest.fail('Edit read Analyzer'))
    current = workflow['fresh']().revise_plan(workflow['source_input'], selected, changed_cfg)
    assert current['previous_revision'] == original['plan_revision']
    assert current['plan_revision'] != original['plan_revision']
    assert current['approval_state'] == 'PLAN_READY' and current['approval_record'] is None
    assert 'source_start' in current['invalidation_reason'] and 'center_x' in current['invalidation_reason']
    assert 'subtitles.font' in current['invalidation_reason']
    assert 'nova curadoria não é necessária' in current['invalidation_reason']
    assert workflow['curations'] == 1
    with pytest.raises(ValueError, match='não foi aprovado'):
        workflow['fresh'](changed_cfg).render_all(workflow['source_input'])


def test_late_worker_cannot_publish_over_new_active_revision(workflow, monkeypatch):
    approved(workflow)
    real_renderer = pipeline.render_clip
    entered, release = threading.Event(), threading.Event()
    errors = []
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10), 'Controlled delayed renderer was not released'
        return real_renderer(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'render_clip', delayed)
    def worker():
        try:
            workflow['fresh']().test_one(workflow['source_input'])
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=worker, daemon=True); thread.start()
    try:
        assert entered.wait(timeout=10)
        current, frozen = workflow['store'].load()
        # Simulate an external delayed writer bypassing the operation lock. CAS
        # must still prevent the old renderer from replacing the active pointer.
        new, _ = workflow['store'].create(frozen, current['approved_clips'],
                                          workflow['config'], workflow['source_input'])
        release.set(); thread.join(timeout=10)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], StalePlanError)
        active = workflow['store'].load()[0]
        assert active['plan_revision'] == new['plan_revision']
        assert active['preview'] is None and active['approval_record'] is None
        assert active['results'] == []
    finally:
        release.set(); thread.join(timeout=10)


def test_encoder_failure_preserves_approval_and_reopen_retry_without_qwen(workflow, monkeypatch):
    original = approved(workflow)
    renderer = pipeline.render_clip
    def fail_once(*args, **kwargs):
        monkeypatch.setattr(pipeline, 'render_clip', renderer)
        raise RuntimeError('Controlled encoder failure')
    monkeypatch.setattr(pipeline, 'render_clip', fail_once)
    with pytest.raises(RuntimeError, match='Controlled encoder failure'):
        workflow['fresh']().render_all(workflow['source_input'])
    failed = workflow['fresh']().read_state(workflow['source_input'])
    assert failed['approval_state'] == 'TEST_APPROVED'
    assert failed['approval_record'] == original['approval_record']
    assert failed['plan_signature'] == original['plan_signature']
    assert failed['active_batch'] is None and failed['results'] == []
    assert failed['last_batch_error']['error'] == 'Controlled encoder failure'
    assert failed['batch_history'][-1]['status'] == 'FAILED'
    assert failed['batch_history'][-1]['approval_preserved'] is True
    assert failed['batch_history'][-1]['partial_artifacts'] == []
    monkeypatch.setattr(pipeline, 'curate', lambda *a, **k: pytest.fail('Retry called Qwen'))
    monkeypatch.setattr(pipeline, 'load_bundle', lambda *_: pytest.fail('Retry accessed Analyzer'))
    result, _ = workflow['fresh']().render_all(workflow['source_input'])
    final = workflow['store'].load()[0]
    assert len(result) == 7 and final['approval_state'] == 'BATCH_COMPLETED'
    assert [row['status'] for row in final['batch_history']] == ['FAILED', 'COMPLETED']
    assert final['last_batch_error'] is None and workflow['curations'] == 1


@pytest.mark.parametrize('failure', ['assets', 'board'])
def test_assets_and_board_failures_never_mark_batch_completed(workflow, monkeypatch, failure):
    original = approved(workflow)
    def fail(*args, **kwargs):
        raise RuntimeError('Controlled ' + failure + ' failure')
    monkeypatch.setattr(pipeline, 'create_assets' if failure == 'assets' else 'build_board', fail)
    with pytest.raises(RuntimeError, match='Controlled ' + failure):
        workflow['fresh']().render_all(workflow['source_input'])
    failed = workflow['store'].load()[0]
    assert failed['approval_state'] == 'TEST_APPROVED'
    assert failed['approval_record'] == original['approval_record']
    assert failed['results'] == []
    expected = 0 if failure == 'assets' else 7
    assert len(failed['batch_history'][-1]['partial_artifacts']) == expected
    assert failed['batch_history'][-1]['status'] == 'FAILED'


def test_failure_after_first_clip_keeps_only_verified_partial_artifacts_in_history(workflow, monkeypatch):
    approved(workflow)
    renderer = pipeline.render_clip
    calls = []
    def second_fails(*args, **kwargs):
        calls.append(args[1]['clip_id'])
        if len(calls) == 2:
            raise RuntimeError('Controlled second clip failure')
        return renderer(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'render_clip', second_fails)
    with pytest.raises(RuntimeError, match='second clip'):
        workflow['fresh']().render_all(workflow['source_input'])
    failed = workflow['store'].load()[0]
    partial = failed['batch_history'][-1]['partial_artifacts']
    assert failed['results'] == [] and failed['approval_state'] == 'TEST_APPROVED'
    assert len(partial) == 1 and partial[0]['clip_id'] == 'CLIP_001'
    assert partial[0]['sha256_verified'] is True and partial[0]['render_validated'] is True
    assert hashlib.sha256(Path(partial[0]['path']).read_bytes()).hexdigest() == partial[0]['sha256']


def test_original_tamper_during_batch_persists_approval_invalidation(workflow, monkeypatch):
    original = approved(workflow)
    renderer = pipeline.render_clip
    def change_source(*args, **kwargs):
        result = renderer(*args, **kwargs)
        workflow['source'].write_bytes(b'changed during active encode')
        return result
    monkeypatch.setattr(pipeline, 'render_clip', change_source)
    with pytest.raises(ValueError, match=r'source_media\.sha256'):
        workflow['fresh']().render_all(workflow['source_input'])
    failed = workflow['fresh']().read_state(workflow['source_input'])
    assert failed['approval_state'] == 'APPROVAL_INVALIDATED'
    assert 'source_media.sha256' in failed['invalidation_reason']
    assert failed['approval_record'] == original['approval_record']  # Historical proof remains.
    assert failed['results'] == [] and failed['active_batch'] is None
    assert failed['batch_history'][-1]['partial_artifacts'] == []
    assert failed['batch_history'][-1]['approval_preserved'] is False
    with pytest.raises(ValueError, match='não foi aprovado'):
        workflow['fresh']().render_all(workflow['source_input'])


def test_reopening_interrupted_batch_recovers_valid_approval_and_partial_history(workflow):
    original = approved(workflow)
    store = workflow['store']
    doc, cached = store.load()
    revision = store.revision_dir(doc)
    output = (Path(workflow['config']['paths']['output_root']) / 'renders' / doc['project_id']
              / 'revisions' / doc['plan_revision'] / 'CLIP_001' / 'batches' / 'interrupted-run')
    media = pipeline.render_clip(cached, doc['approved_clips'][0], workflow['source'],
                                 output, workflow['config'], preview=False)
    artifact = {'path': str(media), 'sha256': hashlib.sha256(media.read_bytes()).hexdigest(),
                'clip_id': 'CLIP_001', 'plan_revision': doc['plan_revision'],
                'batch_id': 'interrupted-run', 'render_validated': True,
                'source_media_sha256': doc['source_media_sha256']}
    doc.update(approval_state='BATCH_RENDERING',
               active_batch={'batch_id': 'interrupted-run', 'partial_artifacts': [artifact]})
    store.save_state(doc)
    resumed = workflow['fresh']().read_state(workflow['source_input'])
    assert resumed['approval_state'] == 'TEST_APPROVED'
    assert resumed['approval_record'] == original['approval_record']
    assert resumed['active_batch'] is None and resumed['results'] == []
    attempt = resumed['batch_history'][-1]
    assert attempt['status'] == 'INTERRUPTED'
    assert attempt['partial_artifacts'][0]['sha256_verified'] is True
    assert workflow['fresh']().read_state(workflow['source_input']) == resumed
    assert workflow['curations'] == 1


def test_failed_no_approval_policy_batch_restores_plan_ready(workflow, monkeypatch):
    curate(workflow)
    config = deepcopy(workflow['config'])
    config['safety']['require_first_test_approval_before_batch'] = False
    def fail(*args, **kwargs):
        raise RuntimeError('Controlled optional-policy failure')
    monkeypatch.setattr(pipeline, 'render_clip', fail)
    with pytest.raises(RuntimeError, match='optional-policy'):
        workflow['fresh'](config).render_all(workflow['source_input'])
    doc = workflow['store'].load()[0]
    assert doc['approval_state'] == 'PLAN_READY' and doc['approval_record'] is None
    assert doc['results'] == [] and doc['batch_history'][-1]['status'] == 'FAILED'


def test_stale_batch_worker_never_publishes_recovery_over_new_revision(workflow, monkeypatch):
    approved(workflow)
    renderer = pipeline.render_clip
    new_revision = []
    def replace_active(*args, **kwargs):
        current, cached = workflow['store'].load()
        new, _ = workflow['store'].create(cached, current['approved_clips'],
                                          workflow['config'], workflow['source_input'])
        new_revision.append(new['plan_revision'])
        return renderer(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'render_clip', replace_active)
    with pytest.raises(StalePlanError, match='Revisão obsoleta'):
        workflow['fresh']().render_all(workflow['source_input'])
    doc = workflow['store'].load()[0]
    assert doc['plan_revision'] == new_revision[0]
    assert doc['approval_state'] == 'PLAN_READY'
    assert doc['approval_record'] is None and doc['results'] == []
    assert not doc.get('batch_history') and not doc.get('last_batch_error')
