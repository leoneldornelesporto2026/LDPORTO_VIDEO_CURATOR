from pathlib import Path
import sys
from copy import deepcopy
import importlib.util
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
MOD=ROOT/'scripts'/'REPARAR_STORY06_SEM_QWEN.py'
spec=importlib.util.spec_from_file_location('story06_patch',MOD)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from ldporto_curator.series_workflow import SeriesProject

@pytest.fixture
def parent(tmp_path,monkeypatch):
    p=SeriesProject(tmp_path/'parent',{'render':{'prefer_nvenc':False}})
    p.evidence={'source':{'sha256':module.SOURCE_SHA, 'duration':2.0},
        'segments':[{'segment_id':module.MISSING_SEGMENT,'start':0.,'end':2.,'text':'Olá, avião!'}],
        'words':[],'scenes':[],'timeline':[]}
    ep={'episode_id':module.EPISODE_ID,'source_start':0.,'source_end':2.,'duration':2.,
        'duration_preset':'story_upto_60','source_sha256':module.SOURCE_SHA,
        'series_id':'S02','order':3,'story_order':3,'title_text':'TESTE - PARTE 3',
        'title_duration':5.,'subtitle_preset':'LDP_CLEAN','camera_mode':'AUTO_CONSERVADOR',
        'state':'REVIEW_REQUIRED','status':'REVIEW_REQUIRED'}
    p.plan={'plan_id':'HISTORICO','source_sha256':module.SOURCE_SHA,'episodes':[ep], 'extras':[]}
    p.save()
    words=[{'word_id':'WORD_001','segment_id':module.MISSING_SEGMENT,'start':.1,'end':.7,'word':'Olá,'},
           {'word_id':'WORD_002','segment_id':module.MISSING_SEGMENT,'start':1.,'end':1.8,'word':'avião!'}]
    monkeypatch.setattr('ldporto_curator.series_workflow._verified_supplemental_words',
        lambda manifest,evidence: (deepcopy(words),{'status':'verified_mock','added_word_ids':['WORD_001','WORD_002']}))
    return p

def snapshot(path):
    import hashlib
    return {f.relative_to(path).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in path.rglob('*') if f.is_file()}

def test_missing_camera_no_preview_creates_review_only(parent,tmp_path):
    before=snapshot(parent.directory)
    target=tmp_path/'derived'
    d,prov=module.derive_unpreviewed_story(parent,target,tmp_path/'manifest.json')
    assert prov=='new_conservative_camera_not_historically_approved'
    assert snapshot(parent.directory)==before
    assert d.episode(module.EPISODE_ID)['camera_plan']['mode']=='full_frame_blur'
    assert d.episode(module.EPISODE_ID)['status']=='REVIEW_REQUIRED'
    assert not d.episode(module.EPISODE_ID).get('preview')
    assert d.plan['story06_recovery']['approved'] is False
    assert d.plan['story06_recovery']['qwen_executed'] is False
    assert d.prepare_caption_timeline(module.EPISODE_ID)['sync']['renderable'] is True
    assert len(d.evidence['words'])==2

def test_existing_preview_must_not_bypass_historic_assets(parent,tmp_path):
    parent.episode(module.EPISODE_ID)['preview']={'review_folder':'missing'}
    parent.save()
    before=snapshot(parent.directory)
    with pytest.raises(ValueError,match='prévia/final'):
        module.derive_unpreviewed_story(parent,tmp_path/'other',tmp_path/'manifest.json')
    assert snapshot(parent.directory)==before
    assert not (tmp_path/'other').exists()

def test_existing_destination_never_modified(parent,tmp_path):
    target=tmp_path/'derived'
    target.mkdir()
    before=snapshot(parent.directory)
    with pytest.raises(ValueError,match='pasta inédita'):
        module.derive_unpreviewed_story(parent,target,tmp_path/'manifest.json')
    assert snapshot(parent.directory)==before
