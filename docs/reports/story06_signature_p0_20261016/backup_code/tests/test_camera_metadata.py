"""No media access: source-bound camera evidence, hashes, paths and time limits."""
from copy import deepcopy
import json
from pathlib import Path
import os

import pytest

from ldporto_curator.camera_metadata import load_existing_camera_metadata, verify_existing_camera_metadata


SOURCE = 'a'*64


@pytest.fixture
def saved(tmp_path):
    plan=tmp_path/'EDIT_DECISIONS.json'
    micro=tmp_path/'planning'/'run'/'clips'/'CLIP_01'/'clip_micro_perception.json'
    micro.parent.mkdir(parents=True)
    payload={'sampled_start':10.05,'sampled_end':19.95,
             'observations':[{'time':10.05},{'time':15.},{'time':19.95}]}
    document={'source_media_sha256':SOURCE,'planning_evidence':'planning\\run',
              'approved_clips':[{'clip_id':'CLIP_01','source_start':10.,'source_end':20.}]}
    micro.write_text(json.dumps(payload),encoding='utf-8')
    plan.write_text(json.dumps(document),encoding='utf-8')
    return plan,micro,document,payload


def test_loads_exact_plan_clip_and_rehashes_both_files_without_touching_media(saved):
    plan,path,document,payload=saved
    micro=load_existing_camera_metadata(path,SOURCE)
    assert micro['source_sha256']==SOURCE
    assert micro['metadata_provenance']['source_plan_path']==str(plan)
    assert len(micro['metadata_provenance']['sha256'])==64
    assert verify_existing_camera_metadata(micro,SOURCE)==micro
    changed=deepcopy(micro);changed['observations'][0]['time']=12.
    with pytest.raises(ValueError,match='payload changed'):
        verify_existing_camera_metadata(changed,SOURCE)
    assert json.loads(path.read_text(encoding='utf-8'))==payload


def test_same_timestamps_from_other_source_are_rejected(saved):
    plan,path,document,payload=saved
    with pytest.raises(ValueError,match='different source'):
        load_existing_camera_metadata(path,'b'*64)
    payload['source_sha256']='b'*64
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError,match='payload source SHA256'):
        load_existing_camera_metadata(path,SOURCE)


@pytest.mark.parametrize('target',['metadata','plan'])
def test_verification_rejects_changed_file_bytes_even_if_semantics_are_unchanged(saved,target):
    plan,path,document,payload=saved
    micro=load_existing_camera_metadata(path,SOURCE)
    changed=path if target=='metadata' else plan
    changed.write_text(changed.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='SHA256 changed'):
        verify_existing_camera_metadata(micro,SOURCE)


@pytest.mark.parametrize('field,value',[
    ('sampled_start',float('nan')),('sampled_end',float('inf')),
    ('sampled_start',8.),('sampled_end',21.),
    ('sampled_start',True),('sampled_end',None)])
def test_invalid_or_unbound_sample_interval_is_rejected(saved,field,value):
    plan,path,document,payload=saved
    payload[field]=value;path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError):
        load_existing_camera_metadata(path,SOURCE)


@pytest.mark.parametrize('time',[float('nan'),float('inf'),None,True,9.39,20.61])
def test_observation_times_must_be_finite_and_inside_clip_with_tolerance(saved,time):
    plan,path,document,payload=saved
    payload['observations'][1]['time']=time
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError):
        load_existing_camera_metadata(path,SOURCE)


def test_small_sampling_offset_is_allowed_and_returns_independent_copy(saved):
    plan,path,document,payload=saved
    payload.update(sampled_start=9.5,sampled_end=20.5)
    payload['observations']=[{'time':9.5},{'time':20.5}]
    path.write_text(json.dumps(payload),encoding='utf-8')
    micro=load_existing_camera_metadata(path,SOURCE,source_plan=plan)
    verified=verify_existing_camera_metadata(micro,SOURCE)
    verified['observations'][0]['time']=10.
    assert micro['observations'][0]['time']==9.5


def test_exact_binding_rejects_another_clip_and_parent_path_escape(saved,tmp_path):
    plan,path,document,payload=saved
    other=path.parent.parent/'OTHER_CLIP'/'clip_micro_perception.json'
    other.parent.mkdir();other.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError,match='exact clip path'):
        load_existing_camera_metadata(other,SOURCE)
    document['planning_evidence']='../planning'
    plan.write_text(json.dumps(document),encoding='utf-8')
    with pytest.raises(ValueError,match='stay inside'):
        load_existing_camera_metadata(path,SOURCE)


def test_metadata_without_source_plan_or_provenance_is_rejected(tmp_path):
    path=tmp_path/'clip_micro_perception.json';path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='ancestral'):
        load_existing_camera_metadata(path,SOURCE)
    with pytest.raises(ValueError,match='provenance'):
        verify_existing_camera_metadata({'source_sha256':SOURCE,'observations':[]},SOURCE)
    assert verify_existing_camera_metadata({},SOURCE)=={}


def test_empty_file_metadata_can_be_bound_for_a_reasoned_fallback(saved):
    plan,path,document,payload=saved
    path.write_text('{}',encoding='utf-8')
    micro=load_existing_camera_metadata(path,SOURCE)
    assert verify_existing_camera_metadata(micro,SOURCE)==micro


def test_file_symlinks_are_rejected_even_when_their_target_is_valid(saved):
    plan,path,document,payload=saved
    link=path.parent/'linked_micro.json'
    try:
        link.symlink_to(path)
    except (OSError,NotImplementedError):
        pytest.skip('Filesystem does not permit creating symlinks')
    with pytest.raises(ValueError,match='links or junctions'):
        load_existing_camera_metadata(link,SOURCE,source_plan=plan)


@pytest.mark.skipif(os.name!='nt',reason='Windows junction regression')
def test_directory_junction_is_rejected(saved,tmp_path):
    import subprocess
    plan,path,document,payload=saved
    junction=tmp_path/'linked_planning'
    result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(tmp_path/'planning')],
                          capture_output=True,text=True)
    if result.returncode:
        pytest.skip('Filesystem does not permit junction creation')
    # pytest's isolated temp tree owns this junction; no user directories are linked.
    with pytest.raises(ValueError,match='links or junctions'):
        load_existing_camera_metadata(junction/'run'/'clips'/'CLIP_01'/'clip_micro_perception.json',
                                      SOURCE,source_plan=plan)
