"""External, isolated import transactions and gates around the real V5 engine."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import subprocess

import pytest

from ldporto_curator import production_package as production
from ldporto_curator.series_workflow import SeriesProject, OperationCancelled
from ldporto_curator.utils import write_json
from test_production_contract import ready_files, finalize, archive, SOURCE


def package(tmp_path, *, caption='ALIGNMENT_REVIEW_REQUIRED', source=SOURCE):
    files, manifest, folder = ready_files()
    caption_doc = {'state': caption, 'word_ids': ['W1', 'W2']}
    files[folder + '/caption_plan.json'] = json.dumps(caption_doc).encode()
    evidence = json.loads(files['evidence/evidence.json'])
    evidence['words'].append({'word_id': 'W2', 'segment_id': 'S1', 'word': 'original.', 'start': 2.1, 'end': 3.})
    files['evidence/evidence.json'] = json.dumps(evidence).encode()
    return archive(tmp_path / 'ready.zip', finalize(files, manifest))


def test_external_transaction_pins_inputs_reopens_and_preserves_legacy(tmp_path):
    path = package(tmp_path)
    original = path.read_bytes()
    legacy = tmp_path / 'legacy'; legacy.mkdir()
    sentinel = legacy / 'approved.json'; sentinel.write_bytes(b'untouched')
    result = production.import_production_package(path, output_root=tmp_path / 'production', media_library=tmp_path / 'missing', log=lambda _: None)
    project = result['project']
    assert isinstance(project, SeriesProject)
    assert result['source_path'] is None and result['summary']['media_state'] == 'MEDIA_SELECTION_REQUIRED'
    assert not project.episode('R1')['production_caption_gate']['renderable']
    assert result['summary']['approval_state'] == 'HUMAN_REVIEW_REQUIRED'
    assert not list(project.directory.rglob('*.mp4'))
    reopened = production.load_production_project(project.directory)
    assert reopened.signature(reopened.episode('R1')) == project.signature(project.episode('R1'))
    assert path.read_bytes() == original and sentinel.read_bytes() == b'untouched'
    again = production.import_production_package(path, output_root=tmp_path / 'production', media_library=tmp_path / 'missing', log=lambda _: None)
    assert again['project'].directory == project.directory


def test_repository_destination_rejected_before_staging(tmp_path):
    path = package(tmp_path)
    with pytest.raises(ValueError, match='fora do repositório'):
        production.import_production_package(path, output_root=Path(__file__).parent.parent / 'output/unsafe-production')


def test_failed_staging_keeps_previous_revision_and_audit(tmp_path, monkeypatch):
    path = package(tmp_path)
    previous = tmp_path / 'production/existing/approved.mp4'
    previous.parent.mkdir(parents=True); previous.write_bytes(b'historical')
    def fail(*args, **kwargs):
        raise ValueError('simulated interrupted storage')
    monkeypatch.setattr(production, 'resolve_production_media', fail)
    with pytest.raises(ValueError, match='simulated'):
        production.import_production_package(path, output_root=tmp_path / 'production')
    receipts = list((tmp_path / 'production').rglob('TRANSACTION.json'))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())['state'] == 'FAILED'
    assert previous.read_bytes() == b'historical'
    assert not list((tmp_path / 'production').glob('*/revisions/*/series_index.json'))


def test_cancellation_precedes_writes(tmp_path):
    stop = threading.Event(); stop.set()
    path = package(tmp_path)
    with pytest.raises(OperationCancelled):
        production.import_production_package(path, output_root=tmp_path / 'production', cancel=stop)
    assert not (tmp_path / 'production').exists()


def test_wrong_manual_media_sha_never_associates(tmp_path):
    media = tmp_path / 'wrong.mp4'; media.write_bytes(b'wrong source')
    with pytest.raises(ValueError, match='SHA256'):
        production.resolve_production_media({'sha256': SOURCE, 'duration': 10}, media_path=media, media_library=tmp_path / 'empty')


def test_media_rehash_and_technical_validation_without_copy(tmp_path, monkeypatch):
    library = tmp_path / 'library/alias'; library.mkdir(parents=True)
    media = library / 'original.mp4'; media.write_bytes(b'measured source')
    digest = production.file_hash(media)
    write_json(library / 'media_manifest.json', {'source_sha256': digest, 'relative_path': 'original.mp4'})
    monkeypatch.setattr(production, '_probe', lambda _: {'duration': 10., 'width': 1920, 'height': 1080, 'fps': 24.})
    state = production.resolve_production_media({'sha256': digest, 'duration': 10., 'width': 1920, 'height': 1080, 'fps': 24.}, media_library=library.parent)
    assert state['path'] == str(media.resolve()) and state['state'] == 'HASH_AND_TECHNICAL_VERIFIED'
    assert state['copied'] is False and state['downloaded'] is False
    with pytest.raises(ValueError, match='Resolução'):
        production.resolve_production_media({'sha256': digest, 'duration': 10., 'width': 1280}, media_path=media, media_library=tmp_path / 'empty')


@pytest.mark.parametrize('state', ['ALIGNMENT_REVIEW_REQUIRED', 'AUDIO_REVIEW_REQUIRED', 'BLOCKED', 'NO_SPEECH', 'INSTRUMENTAL'])
def test_explicit_caption_states_are_never_inferred_or_bypassed(state):
    gate = production.caption_preflight({'caption_plan': {'state': state}}, {})
    assert gate['state'] == state and gate['renderable'] is False


def test_story_audio_blocker_wins_over_apparently_aligned_words():
    gate = production.caption_preflight({'raw_proposal': {'blockers': ['human_audio_review_pending']}}, {})
    assert gate['state'] == 'AUDIO_REVIEW_REQUIRED' and not gate['renderable']


def test_render_and_approval_enforce_upstream_gate_before_core(tmp_path, monkeypatch):
    project = production.import_production_package(package(tmp_path), output_root=tmp_path / 'production', media_library=tmp_path / 'empty')['project']
    monkeypatch.setattr(SeriesProject, 'render', lambda *args, **kwargs: pytest.fail('blocked render reached core'))
    with pytest.raises(ValueError, match='bloqueada'):
        project.render('R1', tmp_path / 'anything.mp4')
    with pytest.raises(ValueError, match='bloqueada'):
        project.approve('R1', human_reviewed=True)


def test_edit_undo_keeps_native_gate_and_camera_history(tmp_path):
    project = production.import_production_package(package(tmp_path), output_root=tmp_path / 'production', media_library=tmp_path / 'empty')['project']
    before = deepcopy(project.episode('R1'))
    after = project.edit('R1', title_text='Outro título')
    assert after['production_origin_id'] == 'R1'
    assert after['production_caption_gate']['state'] == 'ALIGNMENT_REVIEW_REQUIRED'
    assert after['camera_plan'] == before['camera_plan']
    assert not after.get('human_approval')
    project.undo()
    assert project.episode('R1')['title_text'] == before['title_text']
    assert project.episode('R1')['production_caption_gate'] == before['production_caption_gate']


def test_stale_worker_cannot_mutate_project(tmp_path):
    project = production.import_production_package(package(tmp_path), output_root=tmp_path / 'production', media_library=tmp_path / 'empty')['project']
    other = production.load_production_project(project.directory)
    project.edit('R1', title_text='Changed')
    with pytest.raises(ValueError, match='outra instância'):
        other.edit('R1', title_text='Overwrite')


def test_batch_does_not_stop_for_independent_block_or_failure(tmp_path):
    class Project:
        cancel = None
        directory = tmp_path
        def episodes(self):
            return [{'episode_id': ident, 'production_caption_gate': {'renderable': ident != 'blocked'}} for ident in ('blocked', 'fails', 'valid')]
        def render(self, ident, media, *, preview):
            if ident == 'fails':
                raise ValueError('isolated error')
            target = tmp_path / 'valid.mp4'; target.write_bytes(b'validated stub')
            return target
    report = production.render_production_previews(Project(), tmp_path / 'source.mp4', log=lambda _: None)
    assert [row['status'] for row in report['rows']] == ['BLOCKED', 'FAILED', 'VALIDATED']
    assert report['counts'] == {'BLOCKED': 1, 'FAILED': 1, 'VALIDATED': 1}


def test_tampered_visual_index_cannot_reopen(tmp_path):
    project = production.import_production_package(package(tmp_path), output_root=tmp_path / 'production', media_library=tmp_path / 'empty')['project']
    (project.directory / 'visual_evidence_index.json').write_text('{}')
    with pytest.raises(ValueError, match='Índice visual'):
        production.load_production_project(project.directory)


def test_positive_instrumental_uses_existing_renderer_with_empty_captions(tmp_path):
    """Generated sine-only fixture proves empty ASS works without fake words."""
    media = tmp_path / 'original.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24:duration=4',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)], check=True, capture_output=True)
    source_hash = production.file_hash(media)
    from test_production_contract import encode
    files, manifest, folder = ready_files()
    manifest['source_sha256'] = source_hash
    files['media_reference.json'] = encode({'source_sha256': source_hash, 'duration': 4., 'width': 640, 'height': 360, 'fps': 24.})
    files['evidence/evidence.json'] = encode({'source': {'sha256': source_hash, 'duration': 4., 'width': 640, 'height': 360, 'fps': 24.}, 'segments': [], 'words': [],
        'candidates': [], 'audio_events': [{'event_id': 'SYNTHETIC_SINE_ONLY', 'source_sha256': source_hash,
            'start': 1., 'end': 3., 'confidence': 1., 'no_speech': True, 'category': 'instrumental'}]})
    files[folder + '/editorial.json'] = encode({'piece_id': 'R1', 'title_text': ''})
    files[folder + '/source_segments.json'] = encode({'segments': [{'start': 1., 'end': 3.}]})
    files[folder + '/caption_plan.json'] = encode({'state': 'INSTRUMENTAL', 'word_ids': []})
    files[folder + '/title_overlay.json'] = encode({'enabled': False})
    files[folder + '/camera_timeline.json'] = encode({'timebase': 'clip_relative', 'segments': [
        {'start': 0., 'end': 2., 'mode': 'SOURCE_PRESERVE'}]})
    path = archive(tmp_path / 'instrumental.zip', finalize(files, manifest))
    result = production.import_production_package(path, media_path=media, output_root=tmp_path / 'production',
        media_library=tmp_path / 'missing', cfg={'render': {'prefer_nvenc': False}})
    project = result['project']; episode = project.episode('R1')
    assert episode['production_caption_gate']['renderable'] is True
    output = project.render('R1', media)
    sync = json.loads((output.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8'))
    assert sync['enabled'] is False and sync['events'] == [] and sync['renderable'] is True
    assert output.is_file() and episode['state'] == 'PREVIEW_READY' and not episode.get('human_approval')
    assert not (output.parent / 'PREVIEW_APPROVED_V5.json').exists()
    assert production.load_production_project(project.directory).signature(episode) == project.signature(episode)
    # Source-bound proof is rechecked rather than trusting the cached gate.
    project.evidence['audio_events'][0]['confidence'] = .1
    with pytest.raises(ValueError, match='Evidência positiva'):
        project.signature(episode)
