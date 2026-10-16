"""P0 camera/Story recovery tests — no writes to real outputs."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from ldporto_curator.final_camera import refine_from_existing_metadata
from ldporto_curator import combined_batch
from scripts.NOVAS_PREVIAS_STORIES_CAMERA import make_camera_reviews


def micro_face(start=0.,duration=11.):
    rows=[]
    for i in range(56):
        t=start+i*.2
        if t >= start+duration:break
        rows.append({'time':t,'person_id':'FACE_1','track_id':'FACE_1','shot_id':'SHOT_01',
          'face_visible':True,'safe_crop_possible':True,'detection_confidence':.96,'sharpness':130.,
          'face_bbox':{'x':.44,'y':.18,'width':.12,'height':.18},
          'center':{'x':.5,'y':.27},'head_center':{'x':.5,'y':.27},'bbox_kind':'face'})
    return {'status':'measured','observations':rows,'frames':[{'time':r['time'],'shot_id':'SHOT_01','face_count':1} for r in rows],
            'shots':[{'start':start,'end':start+duration,'shot_id':'SHOT_01'}],
            'broadcast_graphics':{'intervals':[]}}


def test_opt_in_safe_vertical_crop_without_changing_editorial():
    clip={'clip_id':'SECOND_TEST','curation_source':'SECOND_CURATOR','suggested_layout':'source_preserve',
         'source_start':0.,'source_end':11.,'camera_plan':{'mode':'full_frame_blur'}}
    before=deepcopy(clip); micro=micro_face()
    old=refine_from_existing_metadata(clip,{'width':1920,'height':1080},micro=micro)
    new=refine_from_existing_metadata(clip,{'width':1920,'height':1080},micro=micro,prefer_visual_focus=True)
    assert all(s['mode']=='full_frame_blur' for s in old['segments'])
    assert any(s['mode']=='crop' for s in new['segments'])
    assert clip == before
    assert new['needs_review'] is True
    assert new['diagnostics']['effective_crop_count'] > 0


def test_no_face_means_no_forced_zoom():
    clip={'curation_source':'SECOND_CURATOR','suggested_layout':'source_preserve','source_start':0.,'source_end':11.}
    micro={'status':'measured','observations':[],'frames':[],'shots':[{'start':0,'end':11,'shot_id':'A'}]}
    result=refine_from_existing_metadata(clip,{'width':1920,'height':1080},micro=micro,prefer_visual_focus=True)
    assert all(s['mode']=='full_frame_blur' for s in result['segments'])


def test_story06_does_not_fabricate_missing_manifest(tmp_path,monkeypatch):
    monkeypatch.setattr(combined_batch,'__file__',str(tmp_path/'runtime'/'ldporto_curator'/'combined_batch.py'))
    project=SimpleNamespace(directory=tmp_path/'projects'/'story_a')
    project.directory.mkdir(parents=True)
    ep={'episode_id':combined_batch._STORY06_ID}
    with pytest.raises(ValueError,match='WORD_EVIDENCE_SEG00163'):
        combined_batch._create_verified_story06_preview(project,ep,tmp_path/'original.mp4',lambda x:None)
    assert not list(project.directory.parent.glob('story06_caption_recovered_*'))


def test_story_precheck_validates_16_and_source_without_writing(tmp_path):
    source=tmp_path/'original.mp4'; source.write_bytes(b'fake fixture')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    base=tmp_path/'stories';base.mkdir()
    for name in ('evidence.json','source_manifest.json','series_index.json'):
        (base/name).write_text('{}')
    episodes=[{'episode_id':f'S{i}','source_start':float(i*10),'source_end':float(i*10+9)} for i in range(16)]
    parent=SimpleNamespace(directory=base,evidence={'source':{'sha256':sha},'words':[],'segments':[]},
                  plan={'source_sha256':sha},episodes=lambda:episodes)
    report=make_camera_reviews(parent,source,None,create=False)
    assert report['episodes']==16 and report['status']=='SOURCE_AND_STORIES_VERIFIED'
    assert not list(tmp_path.glob('camera_stories_*'))
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA256'):
        make_camera_reviews(parent,source,None,create=False)
