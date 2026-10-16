"""The camera demonstration is an explicit two-Story, read-only workflow."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ldporto_curator.approval import file_hash
from ldporto_curator.episode_approval import record_episode_preview
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles
from scripts import validate_story_camera_routing as demo


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.fixture
def frozen_inputs(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'isolated fixture source; ffmpeg must never open this')
    sha = file_hash(source)
    project = SeriesProject(tmp_path / 'historical', {'render': {'prefer_nvenc': False}})
    project.evidence = {'source': {'sha256': sha, 'width': 1920, 'height': 1080},
        'metadata': {'width': 1920, 'height': 1080}, 'segments': [], 'words': []}
    episodes = []
    for index, identifier in enumerate(('HOST', 'MAP', 'UNSELECTED')):
        start, end = index*12., (index+1)*12.
        project.evidence['segments'].append({'segment_id': identifier, 'start': start,
            'end': end, 'text': 'Ola aviao'})
        project.evidence['words'].extend([
            {'word_id': identifier+'_1', 'segment_id': identifier,
                'start': start+.1, 'end': start+.5, 'word': 'Ola'},
            {'word_id': identifier+'_2', 'segment_id': identifier,
                'start': start+1., 'end': start+1.7, 'word': 'aviao'}])
        episode = {'episode_id': identifier, 'series_id': 'S01', 'order': index+1,
            'story_order': index+1, 'source_start': start, 'source_end': end,
            'duration': end-start, 'title_text': 'Frozen '+identifier, 'title_duration': 5.,
            'subtitle_preset': 'LDP_REELS_KARAOKE', 'camera_mode': 'AUTO_CONSERVADOR',
            'camera_plan': {'mode': 'full_frame_blur', 'segments': [
                {'start': 0., 'end': 12., 'mode': 'full_frame_blur', 'zoom': 1.}]},
            'status': 'PREVIEW_READY', 'state': 'PREVIEW_READY',
            'human_approval': {'human': True}}
        episodes.append(episode)
    project.plan = {'plan_id': 'HISTORICAL', 'source_sha256': sha,
        'episodes': episodes, 'extras': []}
    for episode in episodes:
        folder = project.directory / episode['episode_id']
        folder.mkdir(parents=True)
        media = folder / 'PREVIEW.mp4'
        media.write_bytes(('frozen '+episode['episode_id']).encode())
        subs = write_episode_subtitles(project.evidence, episode, folder,
            preset=episode['subtitle_preset'])
        assets = [Path(subs[key]) for key in ('ass', 'srt', 'sync_metadata')]
        for name in ('title_card_preview.png', 'TITLE_LAYOUT.json', 'thumbnails/CAPA_01.png'):
            path = folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'historical title and cover')
            assets.append(path)
        signature = project.signature(episode)
        record_episode_preview(folder, media, signature, {'status': 'validated'}, assets)
        episode['preview'] = {'project_path': str(media.relative_to(project.directory)),
            'review_folder': str(folder.relative_to(project.directory)),
            'sha256': file_hash(media), 'plan_hash': signature,
            'thumbnail_choices': {'choices': []}}
    project.save()
    plan_path = tmp_path / 'reels/EDIT_DECISIONS.json'
    clips = [{'clip_id': identifier, 'source_start': index*12., 'source_end': (index+1)*12.}
             for index, identifier in enumerate(('HOST', 'MAP'))]
    plan = {'source_media_sha256': sha, 'planning_evidence': 'revisions/current',
        'approved_clips': clips}
    write_json(plan_path, plan)
    host = {'observations': [{'time': index*.2, 'person_id': 'VISUAL_HOST',
        'track_id': 'TRACK', 'shot_id': 'SHOT', 'face_visible': True,
        'safe_crop_possible': True, 'detection_confidence': .96, 'sharpness': 150.,
        'face_bbox': {'x': .43, 'y': .2, 'width': .10, 'height': .18}}
        for index in range(60)], 'sampled_start': 0., 'sampled_end': 11.8,
        'shots': [{'shot_id': 'SHOT', 'start': 0., 'end': 12.}],
        'broadcast_graphics': {'intervals': []}}
    write_json(plan_path.parent / 'revisions/current/clips/HOST/clip_micro_perception.json', host)
    write_json(plan_path.parent / 'revisions/current/clips/MAP/clip_micro_perception.json', {})
    return SimpleNamespace(project=project, source=source, sha=sha,
                           plan=plan, plan_path=plan_path)


def test_resolves_exact_declared_interval_before_larger_cover(frozen_inputs):
    inputs = frozen_inputs
    plan = deepcopy(inputs.plan)
    plan['approved_clips'].insert(0, {'clip_id': 'BROAD', 'source_start': 0., 'source_end': 30.})
    # The real loader reads the authoritative plan, so persist its declared extra clip.
    write_json(inputs.plan_path, plan)
    episode = deepcopy(inputs.project.episode('HOST'))
    episode['source_start'] = .0000001
    micro, binding = demo.resolve_saved_micro(inputs.plan_path, plan, episode, inputs.sha)
    assert binding['clip_id'] == 'HOST' and binding['match'] == 'exact'
    assert len(micro['observations']) == 60


def test_covering_interval_requires_unique_evidence(frozen_inputs):
    inputs = frozen_inputs
    episode = deepcopy(inputs.project.episode('HOST'))
    episode.update(source_start=2., source_end=10., duration=8.)
    _, binding = demo.resolve_saved_micro(inputs.plan_path, inputs.plan, episode, inputs.sha)
    assert binding['clip_id'] == 'HOST' and binding['match'] == 'covers'
    ambiguous = deepcopy(inputs.plan)
    ambiguous['approved_clips'].append({'clip_id': 'SECOND', 'source_start': 1., 'source_end': 11.})
    with pytest.raises(ValueError, match='ambiguous'):
        demo.resolve_saved_micro(inputs.plan_path, ambiguous, episode, inputs.sha)


def test_duplicate_exact_evidence_and_missing_interval_fail_closed(frozen_inputs):
    inputs = frozen_inputs
    ambiguous = deepcopy(inputs.plan)
    ambiguous['approved_clips'].append(deepcopy(ambiguous['approved_clips'][0]))
    with pytest.raises(ValueError, match='ambiguous'):
        demo.resolve_saved_micro(inputs.plan_path, ambiguous, inputs.project.episode('HOST'), inputs.sha)
    with pytest.raises(ValueError, match='missing'):
        demo.resolve_saved_micro(inputs.plan_path, inputs.plan, inputs.project.episode('UNSELECTED'), inputs.sha)


def test_wrong_source_and_unbound_paths_cannot_route_camera(frozen_inputs):
    inputs = frozen_inputs
    with pytest.raises(ValueError, match='different source'):
        demo.resolve_saved_micro(inputs.plan_path, inputs.plan, inputs.project.episode('HOST'), 'a'*64)
    escaped = deepcopy(inputs.plan)
    escaped['planning_evidence'] = '../other'
    with pytest.raises(ValueError, match='inside'):
        demo.resolve_saved_micro(inputs.plan_path, escaped, inputs.project.episode('HOST'), inputs.sha)


def test_selection_requires_two_explicit_unique_historical_ids(frozen_inputs):
    parent = frozen_inputs.project
    with pytest.raises(ValueError, match='different'):
        demo.selected_episodes(parent, 'HOST', 'HOST')
    with pytest.raises(ValueError, match='missing or ambiguous'):
        demo.selected_episodes(parent, 'HOST', 'MISSING')
    parent.plan['episodes'].append(deepcopy(parent.episode('HOST')))
    with pytest.raises(ValueError, match='missing or ambiguous'):
        demo.selected_episodes(parent, 'HOST', 'MAP')


def test_destination_refuses_overwrite_and_paths_outside_reports(tmp_path):
    reports = tmp_path / 'docs/reports'
    reports.mkdir(parents=True)
    with pytest.raises(ValueError, match='new directory'):
        demo.checked_destination(reports, reports)
    with pytest.raises(ValueError, match='new directory'):
        demo.checked_destination(tmp_path / 'output/new', reports)
    existing = reports / 'existing'
    existing.mkdir()
    with pytest.raises(ValueError, match='new directory'):
        demo.checked_destination(existing, reports)
    assert demo.checked_destination(reports / 'new', reports) == reports / 'new'


def test_two_camera_only_demos_preserve_all_history_and_do_not_analyze_or_approve(
        frozen_inputs, tmp_path, monkeypatch):
    inputs = frozen_inputs
    before = demo.inventory(inputs.project.directory)
    monkeypatch.setattr(demo, 'ROOT', tmp_path)
    monkeypatch.setattr(demo, 'load_config', lambda path: {'render': {'prefer_nvenc': True}})
    def forbidden(*args, **kwargs):
        pytest.fail('No detector, curation, approval, or batch render may run')
    monkeypatch.setattr('ldporto_curator.final_camera.inspect_clip', forbidden)
    monkeypatch.setattr('ldporto_curator.final_camera.inspect_candidate_graphics', forbidden)
    monkeypatch.setattr(SeriesProject, 'approve', forbidden)
    monkeypatch.setattr(SeriesProject, 'render_approved', forbidden)
    render_calls, command_calls = [], []

    def isolated_render(project, identifier, source, *, preview):
        assert preview is True and project.cfg['render']['prefer_nvenc'] is False
        assert project.directory != inputs.project.directory
        assert (project.directory.parent / 'VALIDACAO_STORY_CAMERA_ROUTING.json').is_file()
        render_calls.append(identifier)
        episode = project.episode(identifier)
        folder = project.directory / 'fake_render' / identifier
        folder.mkdir(parents=True)
        timeline = project.prepare_caption_timeline(identifier)
        for key, name in [('ass', 'CAPTIONS.ass'), ('srt', 'CAPTIONS.srt'),
                          ('sync_metadata', 'SUBTITLE_SYNC.json')]:
            (folder / name).write_bytes(Path(timeline[key]).read_bytes())
        (folder / 'title_card_preview.png').write_bytes(b'historical title and cover')
        output = folder / 'PREVIEW.mp4'
        output.write_bytes(('new isolated '+identifier).encode())
        write_json(folder / 'camera_plan.json', episode['camera_plan'])
        return output

    def filter_command(bundle, clip, source, output, ass, title, cfg, preview, encoder):
        assert encoder == 'libx264' and preview is True
        assert output.name == 'FILTER_EVIDENCE_NOT_RENDERED.mp4'
        command_calls.append(clip['episode_id'])
        return ['ffmpeg', '-filter_complex', 'evidence_only_graph', str(output)], 540, 960

    monkeypatch.setattr(SeriesProject, 'render', isolated_render)
    monkeypatch.setattr('ldporto_curator.render._base_cmd', filter_command)
    monkeypatch.setattr(demo, 'audio_digest', lambda path: {'sha256_pcm': 'same', 'samples': 100})
    monkeypatch.setattr(demo, 'probe', lambda path: {'streams': []})
    monkeypatch.setattr(demo, 'compare_frames', lambda *args: [])
    destination = tmp_path / 'docs/reports/demos'
    assert demo.main(['--project', str(inputs.project.directory),
        '--camera-plan', str(inputs.plan_path), '--source', str(inputs.source),
        '--destination', str(destination), '--host-episode', 'HOST', '--map-episode', 'MAP']) == 0
    assert render_calls == command_calls == ['HOST', 'MAP']
    assert demo.inventory(inputs.project.directory) == before
    report = json.loads((destination / 'VALIDACAO_STORY_CAMERA_ROUTING.json').read_text(encoding='utf-8'))
    assert report['historical_project_unchanged'] and report['protected_inputs_unchanged']
    assert report['source_unchanged'] and report['approved'] is False
    assert report['normal_workflow_integration'] == 'PENDING_USER_APPROVAL'
    assert report['new_analysis_executed'] is report['curation_executed'] is False
    assert report['selected_episode_ids'] == ['HOST', 'MAP']
    assert len(report['cases']) == 2
    host, map_case = report['cases']
    assert host['routing_trace']['crop_segment_count'] > 0
    assert map_case['routing_trace']['new_segment_modes'] == ['full_frame_blur']
    for case in report['cases']:
        assert case['audio_pcm_identical'] and case['ass_bytes_unchanged']
        assert case['srt_bytes_unchanged'] and case['title_pixels_unchanged']
        assert case['canonical_timeline_unchanged'] and case['title_and_order_unchanged']
        assert case['routing_trace']['renderer_input_matches_rendered_camera_plan']
        assert case['routing_trace']['additional_encode_executed_for_filter_evidence'] is False
    assert not list(destination.rglob('FILTER_EVIDENCE_NOT_RENDERED.mp4'))
