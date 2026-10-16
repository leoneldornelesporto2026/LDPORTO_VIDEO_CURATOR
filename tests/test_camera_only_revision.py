from copy import deepcopy
import json
from pathlib import Path

import pytest

from ldporto_curator.approval import file_hash
from ldporto_curator.episode_approval import record_episode_preview
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles


@pytest.fixture
def parent(tmp_path):
    project = SeriesProject(tmp_path / 'historical', {'render': {'prefer_nvenc': False}})
    project.evidence = {'source': {'sha256': 'a' * 64, 'width': 1920, 'height': 1080},
        'metadata': {'width': 1920, 'height': 1080},
        'segments': [{'segment_id': 'S', 'start': 0., 'end': 2., 'text': 'Olá avião'}],
        'words': [{'word_id': 'W1', 'segment_id': 'S', 'start': .1, 'end': .5, 'word': 'Olá'},
                  {'word_id': 'W2', 'segment_id': 'S', 'start': 1., 'end': 1.7, 'word': 'avião'}]}
    episode = {'episode_id': 'E', 'series_id': 'S01', 'order': 1, 'story_order': 1,
        'source_start': 0., 'source_end': 2., 'duration': 2., 'title_text': 'Título aprovado',
        'title_duration': 5., 'subtitle_preset': 'LDP_REELS_KARAOKE',
        'camera_mode': 'AUTO_CONSERVADOR', 'camera_plan': {'mode': 'adaptive_timeline',
            'segments': [{'start': 0., 'end': 2., 'mode': 'full_frame_blur', 'zoom': 1.}]},
        'status': 'PREVIEW_READY', 'state': 'PREVIEW_READY', 'human_approval': {'human': True}}
    project.plan = {'plan_id': 'P', 'source_sha256': 'a' * 64, 'episodes': [episode], 'extras': []}
    folder = project.directory / 'preview'
    folder.mkdir(parents=True)
    media = folder / 'PREVIEW.mp4'
    media.write_bytes(b'preserve historical media')
    subs = write_episode_subtitles(project.evidence, episode, folder, preset='LDP_REELS_KARAOKE')
    assets = [Path(subs[key]) for key in ('ass', 'srt', 'sync_metadata')]
    for name in ('title_card_preview.png', 'TITLE_LAYOUT.json', 'thumbnails/CAPA_01.png'):
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'historical title or cover')
        assets.append(path)
    signature = project.signature(episode)
    record_episode_preview(folder, media, signature, {'status': 'validated'}, assets)
    episode['preview'] = {'review_folder': 'preview', 'project_path': 'preview/PREVIEW.mp4',
        'sha256': file_hash(media), 'plan_hash': signature, 'thumbnail_choices': {'choices': []}}
    project.save()
    return project


def inventory(root):
    return {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob('*') if p.is_file()}


def test_camera_only_fork_preserves_canonical_captions_editorial_history_and_reopens(parent, tmp_path, monkeypatch):
    before = inventory(parent.directory)
    old = deepcopy(parent.episode('E'))
    monkeypatch.setattr('ldporto_curator.final_camera.inspect_clip', lambda *a, **k: pytest.fail('No perception'))
    derived = parent.derive_camera_revision(tmp_path / 'new_review', micro_by_episode={'E': {}})
    episode = derived.episode('E')
    assert inventory(parent.directory) == before
    for key in ('source_start', 'source_end', 'duration', 'title_text', 'title_duration', 'subtitle_preset'):
        assert episode[key] == old[key]
    assert episode['human_approval'] is None and not episode.get('preview')
    assert episode['approval_history'] and not list(derived.directory.rglob('*.mp4'))
    result = derived.prepare_caption_timeline('E')
    for key, name in [('ass', 'CAPTIONS.ass'), ('srt', 'CAPTIONS.srt'), ('sync_metadata', 'SUBTITLE_SYNC.json')]:
        assert Path(result[key]).read_bytes() == (parent.directory / 'preview' / name).read_bytes()
    reopened = SeriesProject(derived.directory)
    assert reopened.signature(reopened.episode('E')) == derived.signature(episode)
    assert derived.plan['camera_revision']['analysis_executed'] is False


def test_tampered_captions_rejected_before_destination(parent, tmp_path):
    (parent.directory / 'preview/CAPTIONS.ass').write_text('altered', encoding='utf-8')
    with pytest.raises(ValueError, match='SHA256'):
        parent.derive_camera_revision(tmp_path / 'new_review', micro_by_episode={'E': {}})
    assert not (tmp_path / 'new_review').exists()


def test_new_camera_is_frozen_after_derivation(parent, tmp_path):
    derived = parent.derive_camera_revision(tmp_path / 'new_review', micro_by_episode={'E': {}})
    derived.episode('E')['camera_plan']['segments'][0]['zoom'] = 1.04
    with pytest.raises(ValueError, match='congelar'):
        derived.signature(derived.episode('E'))


def test_substituting_caption_reference_and_its_hashes_breaks_camera_freeze(parent, tmp_path):
    derived = parent.derive_camera_revision(tmp_path / 'new_review', micro_by_episode={'E': {}})
    reference = derived.episode('E')['caption_timeline']
    replacement = derived.directory / 'replacement.ass'
    replacement.write_bytes(b'substituted caption')
    reference['ass'] = replacement.name
    reference['hashes']['ass'] = file_hash(replacement)
    with pytest.raises(ValueError, match='Timeline'):
        derived.prepare_caption_timeline('E')


def test_interrupted_camera_fork_is_not_reopened_or_regenerated(parent, tmp_path, monkeypatch):
    import ldporto_curator.camera_revision as module
    original = module.shutil.copy2
    def interrupted(source, target, *args, **kwargs):
        if 'camera_caption_assets' in Path(target).parts:
            raise OSError('simulated interruption during camera captions copy')
        return original(source, target, *args, **kwargs)
    before = inventory(parent.directory)
    monkeypatch.setattr(module.shutil, 'copy2', interrupted)
    destination = tmp_path / 'new_review'
    with pytest.raises(OSError, match='interruption'):
        parent.derive_camera_revision(destination, micro_by_episode={'E': {}})
    assert inventory(parent.directory) == before
    assert not (destination / 'series_index.json').exists()
    with pytest.raises(ValueError, match='incompleta'):
        SeriesProject(destination)


def test_unlinked_visual_metadata_cannot_steer_camera(parent, tmp_path):
    with pytest.raises(ValueError):
        parent.derive_camera_revision(tmp_path / 'new_review', micro_by_episode={'E': {'observations': [{'time': 0.}]}})
    assert not (tmp_path / 'new_review').exists()


def test_existing_render_never_overwrites_media_or_subtitle_assets(tmp_path, monkeypatch):
    from ldporto_curator import render
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original source')
    target = tmp_path / 'render'
    target.mkdir()
    (target / 'E_PREVIEW.mp4').write_bytes(b'interrupted or approved media')
    (target / 'captions.ass').write_bytes(b'historical captions')
    before = inventory(target)
    monkeypatch.setattr(render, 'write_subtitles', lambda *a, **k: pytest.fail('No asset writes'))
    with pytest.raises(FileExistsError):
        render._render_clip(None, {'clip_id': 'E'}, source, target, {})
    assert inventory(target) == before
