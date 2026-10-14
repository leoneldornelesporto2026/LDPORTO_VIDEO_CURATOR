"""Real FFmpeg integration for V5 project review, recovery and final gates."""
import json
from pathlib import Path
import shutil
import threading

import pytest

from ldporto_curator.approval import file_hash
from ldporto_curator.series_workflow import SeriesProject, OperationCancelled
from ldporto_curator.full_handoff import validate_handoff
from ldporto_curator.utils import run


def evidence_for(media):
    return {'source': {'sha256': file_hash(media), 'video_id': 'synthetic_integration', 'duration': 4.0,
                       'width': 640, 'height': 360, 'fps': 30},
            'segments': [{'segment_id': 'S1', 'start': 0, 'end': 2, 'text': 'Teste sintético visual.', 'sentence_complete': True},
                         {'segment_id': 'S2', 'start': 2, 'end': 4, 'text': 'Narração não medida neste teste.', 'sentence_complete': True}],
            'words': [], 'scenes': [], 'timeline': [], 'candidates': [], 'shortlist': [],
            'availability': {'segments': {'status': 'partial', 'count': 2, 'sources': ['fixture']}}}


@pytest.fixture
def media(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/FFprobe não instalado')
    path = tmp_path / 'source.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x360:rate=30',
         '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','4','-c:v','libx264',
         '-preset','ultrafast','-threads','2','-pix_fmt','yuv420p','-c:a','aac',str(path)])
    return path


def test_real_preview_handoff_final_and_edit_gates(media, tmp_path):
    evidence = evidence_for(media)
    project = SeriesProject.create(evidence, tmp_path/'out', {'render':{'prefer_nvenc':False}})
    episode = project.episodes()[0]
    identifier = episode['episode_id']
    assert episode['status'] == 'REVIEW_REQUIRED' and not episode['human_approval']
    with pytest.raises(ValueError, match='aprovação humana'):
        project.render(identifier, media, preview=False)
    preview = project.render(identifier, media)
    assert preview.exists() and episode['status'] == 'PREVIEW_READY'
    report = json.loads((preview.parent/'RENDER_VALIDATION.json').read_text())
    assert report['width'] == 540 and report['height'] == 960
    assert abs(report['duration']-4) < .15 and len(report['samples']) == 3
    assert len(list((preview.parent/'thumbnails').glob('CAPA_*.png'))) == 3
    assert (preview.parent/'CAPTIONS.srt').is_file() and (preview.parent/'CAPTIONS.ass').is_file()
    assert project.render(identifier, media) == preview
    packet = project.export()
    manifest = validate_handoff(packet)
    assert manifest['source_sha256'] == file_hash(media)
    with pytest.raises(ValueError, match='ação explícita'):
        project.approve(identifier)
    # Explicit test action exercises the human gate; this is not a product approval.
    project.approve(identifier, human_reviewed=True)
    final = project.render(identifier, media, preview=False)
    assert final.is_file() and (final.parent/'CAPA_SELECIONADA.png').is_file()
    assert episode['status'] == 'FINAL_RENDERED' and not episode['approval']['publication_approved']
    before = project.directory/'series_index.json'
    with pytest.raises(ValueError, match='confirme'):
        project.edit(identifier, title_text='Ajuste')
    revised = project.edit(identifier, title_text='Teste sintético visual.', confirm_invalidation=True)
    assert revised['status'] == 'REVIEW_REQUIRED' and revised['human_approval'] is None
    assert final.exists() and preview.exists()
    assert revised['artifact_history'] and revised['approval_history']
    with pytest.raises(ValueError, match='aprovação humana'):
        project.render(revised['episode_id'], media, preview=False)
    resumed = SeriesProject(project.directory, project.cfg)
    assert resumed.plan == project.plan and resumed.evidence == project.evidence
    assert list((project.directory/'revisions').glob('*.json'))


def test_source_tamper_is_rejected_before_assets(media, tmp_path):
    project = SeriesProject.create(evidence_for(media), tmp_path/'out')
    media.write_bytes(media.read_bytes()+b'tampered')
    with pytest.raises(ValueError, match='SHA256'):
        project.render(project.episodes()[0]['episode_id'], media)
    assert not list(project.directory.rglob('*.ass'))


def test_cancelled_operation_and_zero_shortlist_dossier_do_not_approve(media, tmp_path):
    cancel = threading.Event(); cancel.set()
    project = SeriesProject.create(evidence_for(media), tmp_path/'out', mode='DOSSIER_ONLY', cancel=cancel)
    assert project.episodes() == [] and validate_handoff(project.export())
    project2 = SeriesProject.create(evidence_for(media), tmp_path/'out2', cancel=cancel)
    with pytest.raises(OperationCancelled):
        project2.render(project2.episodes()[0]['episode_id'], media)
    assert not any(ep.get('human_approval') for ep in project2.episodes())


@pytest.mark.parametrize('changes',[{'subtitle_overrides':{'font_size_final':float('nan')}},
    {'thumbnail_selection':'MISSING'}, {'audio':{'mode':'invented'}}])
def test_invalid_visual_edit_does_not_mutate_saved_plan(tmp_path, changes):
    source=tmp_path/'source.mp4'; source.write_bytes(b'fixture')
    project=SeriesProject.create(evidence_for(source),tmp_path/'out')
    before=json.dumps(project.plan,sort_keys=True)
    persisted=(project.directory/'series_index.json').read_bytes()
    with pytest.raises(ValueError):
        project.edit(project.episodes()[0]['episode_id'],**changes)
    assert json.dumps(project.plan,sort_keys=True)==before
    assert (project.directory/'series_index.json').read_bytes()==persisted
