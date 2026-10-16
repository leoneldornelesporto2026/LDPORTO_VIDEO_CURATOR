"""Recovery integration regressions; every writable artifact lives under tmp_path.

The subtitle writer, lexical SHA256 verifier, signatures and recovery verifier are
real. Only video encoding is replaced by small, explicitly unapproved fixtures.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ldporto_curator import combined_batch
from ldporto_curator.approval import file_hash
from ldporto_curator.episode_approval import record_episode_preview
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles
from ldporto_curator.utils import load_json, write_json
from scripts import REPARAR_STORY06_SEM_QWEN as repair


STORY06 = combined_batch._STORY06_ID


def inventory(directory):
    return {path.relative_to(directory).as_posix(): file_hash(path)
            for path in directory.rglob('*') if path.is_file()}


def record_fixture_preview(project, episode_id):
    """Create signed review artifacts without decoding or encoding any media."""
    episode = project.episode(episode_id)
    existing = episode.get('preview') or {}
    if existing.get('project_path'):
        path = project.directory / existing['project_path']
        assert file_hash(path) == existing['sha256']
        assert existing['plan_hash'] == project.signature(episode)
        return path
    signature = project.signature(episode)
    directory = project.folder(episode) / signature[:16] / 'preview'
    directory.mkdir(parents=True, exist_ok=False)
    subs = write_episode_subtitles(project.evidence, episode, directory,
        preset=episode['subtitle_preset'], overrides=episode.get('subtitle_overrides'),
        width=540, height=960)
    assert subs['sync']['renderable'] is True
    assert subs['sync']['alignment'] == 'word'
    camera = directory / 'camera_plan.json'
    write_json(camera, episode['camera_plan'])
    media = directory / 'PREVIEW_540x960.mp4'
    media.write_bytes(('controlled preview, no encoder: ' + signature).encode())
    assets = [Path(subs[key]) for key in ('ass', 'srt', 'sync_metadata')]
    record_episode_preview(directory, media, signature,
        {'status': 'validated', 'duration': episode['duration'],
         'visual_human_review': 'pending', 'audio_human_review': 'pending'},
        [*assets, camera])
    episode['preview'] = {'review_folder': directory.relative_to(project.directory).as_posix(),
        'project_path': media.relative_to(project.directory).as_posix(),
        'plan_hash': signature, 'sha256': file_hash(media),
        'canonical_timeline_sha256': subs['sync']['canonical_timeline_sha256']}
    episode['state'] = episode['status'] = 'PREVIEW_READY'
    project.save()
    return media


@pytest.fixture
def case(tmp_path, monkeypatch):
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'isolated original source fixture, never user media')
    sha = file_hash(source)
    monkeypatch.setattr(repair, 'SOURCE_SHA', sha)
    cfg = {'render': {'prefer_nvenc': False, 'audio_lufs': -14},
           'source_media': {'path': source.as_posix()}}
    parent = SeriesProject(tmp_path / 'projects' / 'stories_fixture', cfg, log=lambda _: None)
    episodes, segments, words = [], [], []
    supplementary = None
    for index in range(16):
        number = index + 1
        eid = STORY06 if number == 6 else f'STORY_{number:02}'
        start, end = float(index * 10), float(index * 10 + 8)
        sid = repair.MISSING_SEGMENT if number == 6 else f'SEG_{number:02}'
        tokens = ('O piloto explicou com calma toda a rota antes da partida segura.'.split()
                  if number == 6 else 'Trecho completo.'.split())
        measured = [{'word_id': f'WORD_{number:02}_{i:02}', 'segment_id': sid,
            'word': token, 'start': start + .5 + i * .5,
            'end': start + .85 + i * .5} for i, token in enumerate(tokens)]
        segment = {'segment_id': sid, 'start': start, 'end': end,
                   'text': ' '.join(tokens), 'word_ids': [w['word_id'] for w in measured]}
        segments.append(segment)
        if number == 6:
            supplementary = measured
        else:
            words.extend(measured)
        series = 'S01' if number <= 3 else 'S02' if number <= 8 else 'S03'
        episodes.append({'episode_id': eid, 'series_id': series,
            'order': number, 'story_order': number,
            'episode_part_label': f'Parte {number}', 'source_start': start,
            'source_end': end, 'duration': end - start,
            'source_sha256': sha, 'duration_preset': 'story_upto_60',
            'boundary_quality': 'sentence_or_qa', 'title_text': f'Titulo {number}',
            'title_duration': 5., 'subtitle_preset': 'LDP_REELS_KARAOKE',
            'camera_mode': 'AUTO_CONSERVADOR',
            'camera_plan': {'mode': 'full_frame_blur', 'segments': [
                {'start': 0., 'end': end - start, 'mode': 'full_frame_blur'}]},
            'state': 'REVIEW_REQUIRED', 'status': 'REVIEW_REQUIRED'})
    parent.evidence = {'source': {'sha256': sha, 'id': 'P0_FIXTURE',
        'video_id': 'P0_FIXTURE', 'duration': 160., 'width': 1920, 'height': 1080},
        'metadata': {'sha256': sha, 'duration': 160., 'width': 1920, 'height': 1080},
        'segments': segments, 'words': words, 'timeline': [], 'scenes': []}
    parent.plan = {'project_id': 'P0_FIXTURE', 'plan_id': 'PARENT_STORIES',
        'source_sha256': sha, 'episodes': episodes, 'extras': []}
    parent.save()
    lexical = tmp_path / 'lexical'
    lexical.mkdir()
    docs = {'words.json': supplementary,
        'transcript_segments.json': [segments[5]],
        'manifest.json': {'video_sha256': sha, 'files': ['words.json', 'transcript_segments.json']},
        'asr_cache.json': {'source_hash': sha, 'data': {'words': supplementary}}}
    for name, document in docs.items():
        write_json(lexical / name, document)
    manifest = lexical / 'WORD_EVIDENCE_SEG00163.json'
    document = {'schema': 'LDP_SUPPLEMENTAL_WORD_EVIDENCE_V1',
        'source_sha256': sha, 'segment_ids': [repair.MISSING_SEGMENT]}
    for key, name in [('word_file', 'words.json'),
            ('transcript_segments_file', 'transcript_segments.json'),
            ('source_manifest_file', 'manifest.json'), ('source_identity_file', 'asr_cache.json')]:
        document[key] = {'path': str(lexical / name), 'sha256': file_hash(lexical / name)}
    write_json(manifest, document)
    value = SimpleNamespace(parent=parent, source=source, manifest=manifest,
        supplementary=supplementary, root=tmp_path, cfg=cfg, serial=0)

    def recover(*, preview=True):
        value.serial += 1
        directory = parent.directory.parent / f'story06_caption_recovered_{value.serial:03}'
        child, _ = repair.derive_unpreviewed_story(parent, directory, manifest)
        if preview:
            record_fixture_preview(child, STORY06)
        return child

    value.recover = recover
    return value


def info(case, child=None):
    return combined_batch._recovered_preview_info(case.parent,
        case.parent.episode(STORY06), case.source,
        explicit_revision=child.directory if child is not None else None)


def render_stub(monkeypatch, calls):
    def render(project, episode_id, source, *, preview=True):
        calls.append((project.directory, episode_id, preview))
        assert preview is True, 'Unapproved fixtures must never enter final rendering'
        return record_fixture_preview(project, episode_id)
    monkeypatch.setattr(SeriesProject, 'render', render)


def test_recovered_signature_restores_nonempty_configuration(case):
    child = case.recover()
    before = inventory(case.parent.directory)
    result = info(case, child)
    expected = child.episode(STORY06)['preview']['plan_hash']
    assert result['signature'] == expected
    assert result['project'].cfg == case.cfg
    assert result['technical_state'] == 'RECOVERED_PREVIEW_VALIDATED'
    assert result['human_review_state'] == 'HUMAN_REVIEW_REQUIRED'
    assert result['ready_for_final_render'] is False
    assert combined_batch._verified_recovered_preview(case.parent,
        case.parent.episode(STORY06), case.source, explicit_revision=child.directory) == result['movie']
    assert inventory(case.parent.directory) == before


def test_legacy_recovery_accepts_only_configuration_reproducing_exact_signature(case):
    child = case.recover()
    recovery = child.plan['story06_recovery']
    recovery.pop('render_settings', None)
    recovery.pop('render_settings_sha256', None)
    child.save()
    assert info(case, child)['signature'] == child.episode(STORY06)['preview']['plan_hash']
    case.parent.cfg = deepcopy(case.cfg)
    case.parent.cfg['render']['audio_lufs'] = -18
    with pytest.raises(ValueError):
        info(case, child)


@pytest.mark.parametrize('tamper', ['signature', 'movie', 'caption', 'word_timestamp', 'lexical_source'])
def test_recovery_rejects_actually_tampered_inputs(case, tamper):
    child = case.recover()
    episode = child.episode(STORY06)
    folder = child.directory / episode['preview']['review_folder']
    if tamper == 'signature':
        record = load_json(folder / 'PREVIEW_REVIEW_V5.json')
        record['plan_signature'] = '0' * 64
        write_json(folder / 'PREVIEW_REVIEW_V5.json', record)
    elif tamper == 'movie':
        (child.directory / episode['preview']['project_path']).write_bytes(b'changed MP4')
    elif tamper == 'caption':
        (folder / 'CAPTIONS.ass').write_bytes(b'changed caption')
    elif tamper == 'word_timestamp':
        recovered_word = next(word for word in child.evidence['words']
                              if word['word_id'] == case.supplementary[0]['word_id'])
        recovered_word['end'] += .01
        child.save()
    else:
        (case.manifest.parent / 'words.json').write_bytes(b'[]')
    before = inventory(case.root)
    with pytest.raises(ValueError):
        info(case, child)
    assert inventory(case.root) == before


def test_legitimate_new_revision_does_not_need_parent_fingerprint(case):
    historical_signature = case.parent.signature(case.parent.episode(STORY06))
    child = case.recover()
    assert child.plan['plan_id'] != case.parent.plan['plan_id']
    assert child.plan['parent_plan_id'] == case.parent.plan['plan_id']
    assert child.signature(child.episode(STORY06)) != historical_signature
    assert info(case, child)['technical_state'] == 'RECOVERED_PREVIEW_VALIDATED'


def test_unapproved_recovery_continues_to_story16(case, monkeypatch):
    child = case.recover()
    calls = []
    render_stub(monkeypatch, calls)
    result = combined_batch.render_stories_review_batch(case.parent, case.source,
        log=lambda _: None, recovered_revision=child.directory)
    assert result['total_parts'] == 16
    assert [row['episode_id'] for row in result['order']] == [
        episode['episode_id'] for episode in case.parent.episodes()]
    assert result['finals'] == 0 and result['publication_approved'] is False
    sixth = result['order'][5]
    assert sixth['episode_id'] == STORY06 and sixth['publication_ready'] is False
    assert all(episode_id != STORY06 for _, episode_id, _ in calls)
    assert result['order'][-1]['episode_id'] == 'STORY_16'


def test_human_approval_belongs_to_the_exact_recovered_revision(case):
    first, second = case.recover(), case.recover()
    first.approve(STORY06, human_reviewed=True)
    approved, pending = info(case, first), info(case, second)
    assert approved['human_review_state'] == 'PREVIEW_APPROVED'
    assert approved['ready_for_final_render'] is True
    assert pending['human_review_state'] == 'HUMAN_REVIEW_REQUIRED'
    assert pending['ready_for_final_render'] is False
    assert not case.parent.episode(STORY06).get('human_approval')


def test_invalid_historical_recovery_coexists_with_valid_revision(case):
    invalid, valid = case.recover(), case.recover()
    episode = invalid.episode(STORY06)
    (invalid.directory / episode['preview']['project_path']).write_bytes(b'old interrupted file')
    before = inventory(invalid.directory)
    result = info(case)
    assert result['project'].directory == valid.directory
    assert inventory(invalid.directory) == before


def test_resume_after_interrupted_story6_preserves_attempt(case, monkeypatch):
    incomplete = case.recover(preview=False)
    before = inventory(incomplete.directory)
    creations = []

    def create(project, episode, source, log):
        creations.append(episode['episode_id'])
        child = case.recover()
        return child.directory, child.directory / child.episode(STORY06)['preview']['project_path']

    monkeypatch.setattr(combined_batch, '_create_verified_story06_preview', create)
    calls = []
    render_stub(monkeypatch, calls)
    first = combined_batch.render_stories_review_batch(case.parent, case.source, log=lambda _: None)
    second = combined_batch.render_stories_review_batch(case.parent, case.source, log=lambda _: None)
    assert first['total_parts'] == second['total_parts'] == 16
    assert creations == [STORY06]
    assert inventory(incomplete.directory) == before


def test_repeated_batch_is_idempotent_without_new_revisions(case, monkeypatch):
    child = case.recover()
    calls = []
    render_stub(monkeypatch, calls)
    first = combined_batch.render_stories_review_batch(case.parent, case.source,
        log=lambda _: None, recovered_revision=child.directory)
    before = inventory(case.root)
    second = combined_batch.render_stories_review_batch(case.parent, case.source,
        log=lambda _: None, recovered_revision=child.directory)
    assert first == second
    assert inventory(case.root) == before
    assert len(list(case.parent.directory.parent.glob('story06_caption_recovered_*'))) == 1


def test_missing_lexical_evidence_blocks_only_story6(case, monkeypatch):
    def blocked(*args, **kwargs):
        raise ValueError('Story 6: insufficient verified lexical evidence')

    monkeypatch.setattr(combined_batch, '_create_verified_story06_preview', blocked)
    calls = []
    render_stub(monkeypatch, calls)
    result = combined_batch.render_stories_review_batch(case.parent, case.source, log=lambda _: None)
    assert result['total_parts'] == 16
    sixth = result['order'][5]
    assert any(token in sixth['status'].upper() for token in ('BLOCK', 'BLOQ'))
    assert sixth['publication_ready'] is False
    assert result['order'][-1]['episode_id'] == 'STORY_16'
    assert not list(case.parent.directory.parent.glob('story06_caption_recovered_*'))


def test_preserves_first_five_stories_and_eight_reels(case, monkeypatch):
    for episode in case.parent.episodes()[:5]:
        record_fixture_preview(case.parent, episode['episode_id'])
    child = case.recover()
    reels = case.root / 'existing_reels'
    reels.mkdir()
    for rank in range(1, 9):
        (reels / f'REEL_{rank:02}.mp4').write_bytes(f'approved Reel fixture {rank}'.encode())
    protected = [path for episode in case.parent.episodes()[:5]
                 for path in (case.parent.directory / episode['preview']['review_folder']).rglob('*')
                 if path.is_file()]
    protected.extend(reels.iterdir())
    before = {str(path): file_hash(path) for path in protected}
    render_stub(monkeypatch, [])
    result = combined_batch.render_stories_review_batch(case.parent, case.source,
        log=lambda _: None, recovered_revision=child.directory)
    assert result['total_parts'] == 16
    assert {str(path): file_hash(path) for path in protected} == before


def test_normal_combined_route_skips_completed_reels(case, monkeypatch):
    case.recover()
    monkeypatch.setattr(combined_batch, 'prepare_stories', lambda *args: (case.parent, case.source, {}))
    monkeypatch.setattr(combined_batch, 'reel_batch_complete', lambda *args: True)
    render_stub(monkeypatch, [])

    def forbidden(*args, **kwargs):
        pytest.fail('Completed Reels must not be rendered or curated again')

    pipeline = SimpleNamespace(log=lambda _: None, progress=lambda *a, **k: None,
        render_all=forbidden, curate_only=forbidden)
    result = combined_batch.render_combined_batch(pipeline, 'P0_FIXTURE')
    assert result['total_parts'] == 16
    assert result['finals'] == 0


def test_technically_valid_preview_never_authorizes_final_without_human_review(case):
    child = case.recover()
    assert info(case, child)['ready_for_final_render'] is False
    before = inventory(child.directory)
    with pytest.raises(ValueError, match='aprova'):
        child.render(STORY06, case.source, preview=False)
    assert inventory(child.directory) == before


def test_persisted_recovery_settings_cannot_be_changed(case):
    child = case.recover()
    child.plan['story06_recovery']['render_settings']['render']['audio_lufs'] = -18
    child.save()
    with pytest.raises(ValueError, match='Configuração congelada'):
        info(case, child)


def test_recovery_cannot_claim_a_different_project_id(case):
    child = case.recover()
    child.plan['project_id'] = 'different_project'
    child.save()
    with pytest.raises(ValueError, match='Identidade do projeto'):
        info(case, child)


def test_interrupted_batch_manifest_is_preserved_and_resume_is_idempotent(tmp_path):
    target = tmp_path / 'LOTE_STORIES_EM_ORDEM.json'
    target.write_text('{"interrupted":', encoding='utf-8')
    original = target.read_bytes()
    document = {'total_parts': 16, 'publication_approved': False}
    published = combined_batch._write_batch_json(target, document)
    assert published != target and target.read_bytes() == original
    before = inventory(tmp_path)
    assert combined_batch._write_batch_json(target, document) == published
    assert inventory(tmp_path) == before
