"""Historical projects stay byte-identical while derived caption inputs are frozen."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ldporto_curator.approval import file_hash
from ldporto_curator.episode_approval import record_episode_preview
from ldporto_curator.series_workflow import SeriesProject


@pytest.fixture
def historical(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original media must stay unchanged')
    project = SeriesProject(tmp_path / 'historical', {'render': {'prefer_nvenc': False}})
    project.evidence = {'source': {'sha256': file_hash(source), 'duration': 2},
        'provenance': {'transcript_version': 'original-1'},
        'segments': [{'segment_id': 'S1', 'start': 0., 'end': 2., 'text': 'Olá, avião!'}],
        'words': [{'word_id': 'W1', 'segment_id': 'S1', 'start': .1, 'end': .7, 'word': 'Olá,'},
                  {'word_id': 'W2', 'segment_id': 'S1', 'start': 1., 'end': 1.8, 'word': 'avião!'}]}
    episode = {'episode_id': 'E1', 'series_id': 'S01', 'story_order': 1, 'order': 1,
        'source_start': 0., 'source_end': 2., 'duration': 2., 'title_text': 'Título já revisado',
        'title_duration': 5., 'transcript_literal': 'Olá, avião!', 'subtitle_preset': 'LDP_CLEAN',
        'camera_mode': 'AUTO_CONSERVADOR', 'camera_plan': {'mode': 'full_frame_blur',
            'segments': [{'start': 0., 'end': 2., 'mode': 'full_frame_blur'}]},
        'status': 'PREVIEW_READY', 'state': 'PREVIEW_READY', 'human_approval': None}
    project.plan = {'plan_id': 'ORIGINAL_PLAN', 'source_sha256': file_hash(source),
                    'episodes': [episode], 'extras': [], 'human_approval': None}
    folder = project.directory / 'old_preview'
    folder.mkdir(parents=True)
    media = folder / 'PREVIEW.mp4'
    media.write_bytes(b'historical rendered media')
    assets = []
    for name in ('title_card_preview.png', 'TITLE_LAYOUT.json',
                 *['thumbnails/CAPA_%02d.png' % index for index in range(1, 6)],
                 'thumbnails/THUMBNAIL_CHOICES.json'):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('historical asset: ' + name).encode())
        assets.append(path)
    signature = project.signature(episode)
    record_episode_preview(folder, media, signature, {'status': 'validated'}, assets)
    episode['preview'] = {'review_folder': 'old_preview', 'project_path': 'old_preview/PREVIEW.mp4',
        'sha256': file_hash(media), 'plan_hash': signature,
        'thumbnail_choices': {'choices': [{'choice_id': 'CAPA_01', 'file': 'CAPA_01.png'}]}}
    project.save()
    return project, source


def inventory(directory):
    return {str(path.relative_to(directory)): file_hash(path)
            for path in directory.rglob('*') if path.is_file()}


def test_derivation_preserves_every_historical_byte_and_editorial_decision(historical, tmp_path):
    project, source = historical
    before = inventory(project.directory)
    old = deepcopy(project.episodes()[0])
    derived = project.derive_caption_revision(tmp_path / 'derived')
    episode = derived.episodes()[0]
    for key in ('episode_id', 'series_id', 'order', 'story_order', 'source_start', 'source_end',
                'duration', 'title_text', 'title_duration', 'transcript_literal', 'camera_plan'):
        assert episode[key] == old[key]
    assert inventory(project.directory) == before
    assert file_hash(source) == project.evidence['source']['sha256']
    assert episode['status'] == 'REVIEW_REQUIRED' and episode['human_approval'] is None
    assert not episode.get('preview') and not episode.get('final')
    assert episode['artifact_history'][0]['source_project'] == str(project.directory)
    for asset in episode['caption_revision']['frozen_assets']['files']:
        assert (derived.directory / asset['project_path']).read_bytes() == Path(asset['source_path']).read_bytes()
    assert SeriesProject(derived.directory).cfg == project.cfg
    assert not list(derived.directory.rglob('*.mp4'))


def test_derivation_rejects_tampered_historical_asset_before_destination(historical, tmp_path):
    project, _ = historical
    (project.directory / 'old_preview/title_card_preview.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        project.derive_caption_revision(tmp_path / 'derived')
    assert not (tmp_path / 'derived').exists()


def test_derivation_rejects_tampered_historical_mp4(historical, tmp_path):
    project, _ = historical
    (project.directory / 'old_preview/PREVIEW.mp4').write_bytes(b'changed media')
    with pytest.raises(ValueError, match='MP4 histórico'):
        project.derive_caption_revision(tmp_path / 'derived')
    assert not (tmp_path / 'derived').exists()


@pytest.mark.parametrize('change', [
    {'duration': 1.}, {'source_end': float('inf')},
    {'source_end': 60.001, 'duration': 60.001, 'duration_preset': 'story_upto_60'},
])
def test_invalid_window_or_story_ceiling_is_rejected_without_trimming(historical, change):
    project, source = historical
    episode = project.episodes()[0]
    episode.update(change)
    with pytest.raises(ValueError, match='Duração|finitas|60 segundos'):
        project.render('E1', source)
    assert all(episode[key] == value for key, value in change.items())
    assert not list(project.directory.rglob('CAPTIONS.ass'))


@pytest.mark.parametrize('mutation', ['camera', 'transcript', 'settings', 'asset'])
def test_frozen_revision_refuses_changed_inputs_before_render(historical, tmp_path, mutation):
    project, source = historical
    derived = project.derive_caption_revision(tmp_path / 'derived')
    episode = derived.episodes()[0]
    if mutation == 'camera':
        episode['camera_plan']['mode'] = 'crop'
    elif mutation == 'transcript':
        derived.evidence['words'][0]['word'] = 'Reescrito'
    elif mutation == 'settings':
        derived.cfg['render']['prefer_nvenc'] = True
    else:
        item = episode['caption_revision']['frozen_assets']['files'][0]
        (derived.directory / item['project_path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='congelad|Transcrição|Configuração|editorial'):
        derived.render('E1', source)
    assert not list(derived.directory.rglob('CAPTIONS.ass'))


def test_timeline_preparation_does_not_encode_and_detects_tampering(historical, tmp_path, monkeypatch):
    project, _ = historical
    derived = project.derive_caption_revision(tmp_path / 'derived')
    monkeypatch.setattr('ldporto_curator.series_workflow._encode', lambda *args: pytest.fail('No batch encode authorized'))
    result = derived.prepare_caption_timeline('E1')
    assert result['sync']['canonical_timeline_sha256']
    assert [word for event in result['sync']['events'] for word in event['word_ids']] == ['W1', 'W2']
    assert derived.prepare_caption_timeline('E1')['sync'] == result['sync']
    Path(result['srt']).write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='Timeline'):
        derived.prepare_caption_timeline('E1')


def test_transcript_edit_invalidates_normal_episode_signature(historical):
    project, _ = historical
    before = project.signature(project.episodes()[0])
    project.evidence['words'][0]['end'] = .6
    assert project.signature(project.episodes()[0]) != before


def test_new_renderer_requires_new_derived_revision(historical, tmp_path, monkeypatch):
    project, _ = historical
    derived = project.derive_caption_revision(tmp_path / 'derived')
    monkeypatch.setattr('ldporto_curator.series_workflow.renderer_fingerprint', lambda: 'new engine build')
    with pytest.raises(ValueError, match='Motor mudou'):
        derived.signature(derived.episodes()[0])


def test_preexisting_derived_folder_is_never_overwritten(historical, tmp_path):
    project, _ = historical
    derived = project.derive_caption_revision(tmp_path / 'derived')
    before = inventory(derived.directory)
    with pytest.raises(ValueError, match='nova pasta'):
        project.derive_caption_revision(derived.directory)
    assert inventory(derived.directory) == before


def test_preview_reuses_frozen_assets_and_final_reuses_exact_canonical_timeline(historical, tmp_path, monkeypatch):
    project, source = historical
    derived = project.derive_caption_revision(tmp_path / 'derived')
    old_camera = deepcopy(derived.episodes()[0]['camera_plan'])
    monkeypatch.setattr('ldporto_curator.series_workflow.conservative_camera',
                        lambda *args: pytest.fail('Frozen camera must not be recalculated'))
    monkeypatch.setattr('ldporto_curator.thumbnail_presets.generate_thumbnail_choices',
                        lambda *args, **kwargs: pytest.fail('Historical thumbnails must not be regenerated'))
    monkeypatch.setattr('ldporto_curator.render._base_cmd',
                        lambda bundle, clip, media, partial, *args: (['ffmpeg', str(partial)], None, None))
    monkeypatch.setattr('ldporto_curator.media_effects.extend_render_command', lambda command, *args: command)
    def encode(command, *args):
        Path(command[-1]).write_bytes(b'controlled encoder fixture')
        return 0, ''
    monkeypatch.setattr('ldporto_curator.series_workflow._encode', encode)
    monkeypatch.setattr('ldporto_curator.series_workflow.validate_episode_media',
                        lambda path, width, height, duration: {'status': 'validated', 'duration': duration})
    preview = derived.render('E1', source)
    assert (preview.parent / 'title_card_preview.png').read_bytes() == (project.directory / 'old_preview/title_card_preview.png').read_bytes()
    assert derived.episodes()[0]['camera_plan'] == old_camera
    assert len(list((preview.parent / 'thumbnails').glob('CAPA_*.png'))) == 5
    preview_sync = json.loads((preview.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='aprovação humana'):
        derived.render('E1', source, preview=False)
    derived.approve('E1', human_reviewed=True)  # Explicit controlled test action only.
    # Title pixels at 1080 are a renderer concern; this test isolates timing and reuse.
    monkeypatch.setattr('ldporto_curator.title_presets.create_episode_title_card', lambda *args, **kwargs: None)
    # The old fixture omits a selected-thumbnail hash, so avoid selecting a cover.
    derived.episodes()[0]['preview']['thumbnail_choices'] = {'choices': []}
    final = derived.render('E1', source, preview=False)
    final_sync = json.loads((final.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8'))
    assert final_sync['canonical_timeline_sha256'] == preview_sync['canonical_timeline_sha256']
    keys = ('start', 'end', 'source_start', 'source_end', 'literal_text', 'word_ids')
    assert [{key: event[key] for key in keys} for event in final_sync['events']] == [
        {key: event[key] for key in keys} for event in preview_sync['events']]


@pytest.fixture
def supplemental(historical, tmp_path):
    project, _ = historical
    words = deepcopy(project.evidence['words'])
    for word in words:
        word['hypothesis_id'] = 'EXISTING_ASR'
    segment = deepcopy(project.evidence['segments'][0])
    segment['word_ids'] = ['W1', 'W2']
    project.evidence['words'] = []
    project.episodes()[0]['word_ids'] = ['ORIGINAL_EDITORIAL_REFERENCE']
    project.save()
    source_hash = project.evidence['source']['sha256']
    documents = {'word_file': words, 'transcript_segments_file': [segment],
        'source_manifest_file': {'video_sha256': source_hash, 'files': ['words.json', 'transcript_segments.json']},
        'source_identity_file': {'source_hash': source_hash, 'data': {'words': words}}}
    manifest = {'schema': 'LDP_SUPPLEMENTAL_WORD_EVIDENCE_V1', 'source_sha256': source_hash,
                'segment_ids': ['S1']}
    for name, document in documents.items():
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        manifest[name] = {'path': str(path), 'sha256': file_hash(path)}
    path = tmp_path / 'word_evidence.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return project, path


def test_verified_original_word_recovery_changes_only_derived_evidence(supplemental, tmp_path):
    parent, manifest = supplemental
    before = inventory(parent.directory)
    derived = parent.derive_caption_revision(tmp_path / 'derived_supplement', word_evidence=manifest)
    assert inventory(parent.directory) == before
    assert not parent.evidence['words']
    assert [row['word_id'] for row in derived.evidence['words']] == ['W1', 'W2']
    assert derived.evidence['segments'] == parent.evidence['segments']
    assert derived.episodes()[0]['word_ids'] == ['ORIGINAL_EDITORIAL_REFERENCE']
    revision = derived.episodes()[0]['caption_revision']
    assert revision['supplemental_word_ids'] == ['W1', 'W2']
    assert derived.plan['caption_revision']['evidence_enrichment']['new_asr_executed'] is False
    assert derived.plan['caption_revision']['evidence_enrichment']['timestamps_invented'] is False
    sync = derived.prepare_caption_timeline('E1')['sync']
    assert sync['alignment'] == 'word' and sync['renderable'] is True
    assert [event['word_ids'] for event in sync['events']] == [['W1'], ['W2']]


@pytest.mark.parametrize('mutation', ['file_hash', 'foreign_source', 'raw_word', 'segment_text', 'assigned_ids'])
def test_supplement_cannot_bypass_source_hash_literal_ids_or_measured_times(supplemental, tmp_path, mutation):
    project, manifest_path = supplemental
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    key = {'file_hash': 'word_file', 'foreign_source': 'source_identity_file', 'raw_word': 'source_identity_file',
           'segment_text': 'transcript_segments_file', 'assigned_ids': 'transcript_segments_file'}[mutation]
    path = Path(manifest[key]['path'])
    document = json.loads(path.read_text(encoding='utf-8'))
    if mutation == 'foreign_source':
        document['source_hash'] = 'another-source'
    elif mutation == 'raw_word':
        document['data']['words'][0]['end'] = .75
    elif mutation == 'segment_text':
        document[0]['text'] = 'Literal reescrito!'
    elif mutation == 'assigned_ids':
        document[0]['word_ids'].reverse()
    path.write_text(json.dumps(document) + '\n', encoding='utf-8')
    if mutation != 'file_hash':
        manifest[key]['sha256'] = file_hash(path)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        project.derive_caption_revision(tmp_path / 'rejected_supplement', word_evidence=manifest_path)
    assert not (tmp_path / 'rejected_supplement').exists()
