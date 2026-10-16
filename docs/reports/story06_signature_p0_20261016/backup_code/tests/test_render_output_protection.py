"""Interrupted/concurrent publication uses only isolated synthetic render files."""
import hashlib
import json
from pathlib import Path

import pytest

from ldporto_curator import render, utils


def inventory(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def controlled_render(tmp_path, monkeypatch):
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'original source bytes, never decoded')
    clip = {'clip_id': 'E', 'source_start': 1.25, 'source_end': 3.25,
            'duration': 2., 'camera_plan': {'mode': 'crop'}}
    cfg = {'render': {'prefer_nvenc': False}}
    calls = []

    def subtitles(_bundle, _clip, directory, _cfg, **_kwargs):
        ass = directory / 'captions.ass'
        ass.write_bytes(b'canonical subtitle fixture')
        (directory / 'subtitles.srt').write_bytes(b'canonical SRT fixture')
        return ass

    def title(_clip, directory, _cfg, **_kwargs):
        card = directory / 'title_card_preview.png'
        card.write_bytes(b'controlled title fixture')
        return card

    def command(_bundle, _clip, video, out, _ass, _card, _cfg, _preview, encoder):
        return ['ffmpeg', '-y', '-i', str(video), '-c:v', encoder, str(out)], 540, 960

    def encode(command, _duration, **_kwargs):
        assert '-n' in command and '-y' not in command
        target = Path(command[-1])
        # Model FFmpeg's refusal to replace an existing encoding target.
        if target.exists():
            return 1, 'File already exists'
        target.write_bytes(b'valid controlled encoded bytes')
        calls.append(list(command))
        return 0, ''

    def validate(path, width, height):
        assert path.read_bytes() == b'valid controlled encoded bytes'
        assert (width, height) == (540, 960)

    monkeypatch.setattr(render, 'write_subtitles', subtitles)
    monkeypatch.setattr(render, 'create_title_card', title)
    monkeypatch.setattr(render, '_base_cmd', command)
    monkeypatch.setattr(render, '_run_ffmpeg_with_progress', encode)
    monkeypatch.setattr(render, 'validate_output', validate)

    def run(directory):
        return render._render_clip(None, clip, source, directory, cfg, log=lambda *_: None)

    return source, cfg, calls, run


def test_success_publishes_exclusively_and_retry_preserves_every_asset(tmp_path, controlled_render):
    source, _cfg, calls, run = controlled_render
    target = tmp_path / 'review'
    output = run(target)
    assert output.name == 'E_PREVIEW.mp4'
    assert len(calls) == 1 and 'ENCODING_' in Path(calls[0][-1]).name
    assert not list(target.glob('ENCODING_*.mp4'))
    before = inventory(target)
    with pytest.raises(FileExistsError):
        run(target)
    assert inventory(target) == before
    assert source.read_bytes() == b'original source bytes, never decoded'
    metadata = json.loads((target / 'E_PREVIEW.mp4.render.json').read_text(encoding='utf-8'))
    assert metadata['encoder'] == 'libx264'
    assert metadata['media_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_encoder_interruption_retains_attempt_and_fresh_directory_can_recover(tmp_path, monkeypatch, controlled_render):
    source, _cfg, _calls, run = controlled_render
    normal = render._run_ffmpeg_with_progress
    failed = tmp_path / 'failed_review'

    def interrupted(command, _duration, **_kwargs):
        assert '-n' in command and '-y' not in command
        Path(command[-1]).write_bytes(b'interrupted encoding evidence')
        return 1, 'controlled encoder interruption'

    monkeypatch.setattr(render, '_run_ffmpeg_with_progress', interrupted)
    with pytest.raises(RuntimeError, match='controlled encoder interruption'):
        run(failed)
    assert not (failed / 'E_PREVIEW.mp4').exists()
    assert not (failed / 'E_PREVIEW.mp4.render.json').exists()
    attempts = list(failed.glob('ENCODING_*.mp4'))
    assert len(attempts) == 1 and attempts[0].read_bytes() == b'interrupted encoding evidence'
    before = inventory(failed)
    monkeypatch.setattr(render, '_run_ffmpeg_with_progress', normal)
    with pytest.raises(FileExistsError):
        run(failed)
    assert inventory(failed) == before
    output = run(tmp_path / 'recovery_review')
    assert output.is_file() and inventory(failed) == before
    assert source.read_bytes() == b'original source bytes, never decoded'


def test_validation_failure_never_publishes_or_erases_encoding_evidence(tmp_path, monkeypatch, controlled_render):
    _source, _cfg, _calls, run = controlled_render
    normal = render.validate_output
    target = tmp_path / 'bad_validation'

    def fail_validation(*_args):
        raise RuntimeError('controlled media validation failure')

    monkeypatch.setattr(render, 'validate_output', fail_validation)
    with pytest.raises(RuntimeError, match='controlled media validation failure'):
        run(target)
    assert not (target / 'E_PREVIEW.mp4').exists()
    assert len(list(target.glob('ENCODING_*.mp4'))) == 1
    before = inventory(target)
    monkeypatch.setattr(render, 'validate_output', normal)
    assert run(tmp_path / 'valid_recovery').is_file()
    assert inventory(target) == before


def test_concurrent_output_appearing_during_encode_cannot_be_replaced(tmp_path, monkeypatch, controlled_render):
    _source, _cfg, _calls, run = controlled_render
    target = tmp_path / 'concurrent_review'
    normal = render._run_ffmpeg_with_progress

    def competitor_publishes(command, duration, **kwargs):
        result = normal(command, duration, **kwargs)
        (target / 'E_PREVIEW.mp4').write_bytes(b'other operation published first')
        return result

    monkeypatch.setattr(render, '_run_ffmpeg_with_progress', competitor_publishes)
    with pytest.raises(FileExistsError):
        run(target)
    assert (target / 'E_PREVIEW.mp4').read_bytes() == b'other operation published first'
    assert len(list(target.glob('ENCODING_*.mp4'))) == 1
    assert not (target / 'E_PREVIEW.mp4.render.json').exists()


def test_sidecar_write_interruption_keeps_published_media_and_blocks_retry(tmp_path, monkeypatch, controlled_render):
    _source, _cfg, _calls, run = controlled_render
    target = tmp_path / 'sidecar_failure'
    normal = utils.write_json

    def interrupted(path, value):
        if str(path).endswith('.mp4.render.json'):
            raise OSError('controlled sidecar write interruption')
        return normal(path, value)

    monkeypatch.setattr(utils, 'write_json', interrupted)
    with pytest.raises(OSError, match='controlled sidecar write interruption'):
        run(target)
    assert (target / 'E_PREVIEW.mp4').is_file()
    before = inventory(target)
    monkeypatch.setattr(utils, 'write_json', normal)
    with pytest.raises(FileExistsError):
        run(target)
    assert inventory(target) == before


def test_nvenc_fallback_uses_distinct_pending_files_and_retains_failed_attempt(tmp_path, monkeypatch, controlled_render):
    _source, cfg, _calls, run = controlled_render
    cfg['render']['prefer_nvenc'] = True
    monkeypatch.setattr(render, 'ffmpeg_has_nvenc', lambda: True)
    normal = render._run_ffmpeg_with_progress
    attempts = []

    def fallback(command, duration, **kwargs):
        attempts.append(Path(command[-1]))
        if 'h264_nvenc' in command:
            Path(command[-1]).write_bytes(b'failed NVENC encoding evidence')
            return 1, 'controlled NVENC failure'
        return normal(command, duration, **kwargs)

    monkeypatch.setattr(render, '_run_ffmpeg_with_progress', fallback)
    target = tmp_path / 'fallback_review'
    output = run(target)
    assert len(attempts) == 2 and attempts[0] != attempts[1]
    assert attempts[0].read_bytes() == b'failed NVENC encoding evidence'
    assert not attempts[1].exists() and output.is_file()
    metadata = json.loads((target / 'E_PREVIEW.mp4.render.json').read_text(encoding='utf-8'))
    assert metadata['encoder'] == 'libx264'


def test_operation_claim_blocks_competing_writer_before_any_asset_generation(tmp_path, monkeypatch, controlled_render):
    _source, _cfg, calls, run = controlled_render
    target = tmp_path / 'competing_writers'
    normal = render.write_subtitles
    subtitles_calls = []

    def one_writer(*args, **kwargs):
        subtitles_calls.append(True)
        assert len(subtitles_calls) == 1, 'Competing writer reached the asset generator'
        claim = target / 'RENDER_ATTEMPT.json'
        before = claim.read_bytes()
        with pytest.raises(FileExistsError):
            run(target)
        assert claim.read_bytes() == before
        return normal(*args, **kwargs)

    monkeypatch.setattr(render, 'write_subtitles', one_writer)
    assert run(target).is_file()
    assert len(subtitles_calls) == 1 and len(calls) == 1
    receipt = json.loads((target / 'RENDER_ATTEMPT.json').read_text(encoding='utf-8'))
    assert receipt['approved'] is False


@pytest.mark.parametrize('artifact', [
    'captions.ass', 'subtitles.srt', 'TITLE_CARD_PREVIEW.PNG',
    'ENCODING_interrupted_E_PREVIEW.mp4', 'RENDER_ATTEMPT.json',
    'PREVIEW_CAMERA_VERIFIER_V44.json', 'APPROVAL.json',
])
def test_preexisting_review_artifact_prevents_its_directory_being_reused(tmp_path, monkeypatch, controlled_render, artifact):
    _source, _cfg, _calls, run = controlled_render
    target = tmp_path / 'preexisting_review'
    target.mkdir()
    (target / artifact).write_bytes(b'historic or interrupted review evidence')
    before = inventory(target)
    monkeypatch.setattr(render, 'write_subtitles', lambda *_a, **_k: pytest.fail('Preexisting review was reused'))
    with pytest.raises(FileExistsError):
        run(target)
    assert inventory(target) == before


def test_existing_orphaned_sidecar_blocks_all_asset_writes(tmp_path, monkeypatch, controlled_render):
    _source, _cfg, _calls, run = controlled_render
    target = tmp_path / 'orphaned_history'
    target.mkdir()
    (target / 'E_PREVIEW.mp4.render.json').write_bytes(b'previous render receipt')
    (target / 'captions.ass').write_bytes(b'preserved historic subtitles')
    before = inventory(target)
    monkeypatch.setattr(render, 'write_subtitles', lambda *_a, **_k: pytest.fail('Historical assets must remain intact'))
    with pytest.raises(FileExistsError):
        run(target)
    assert inventory(target) == before
