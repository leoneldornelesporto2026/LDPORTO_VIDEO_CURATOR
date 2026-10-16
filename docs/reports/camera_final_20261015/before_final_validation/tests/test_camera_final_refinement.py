"""Camera-only regression: measured framing, frozen inputs and bounded motion."""
from copy import deepcopy
import shutil
import subprocess

import pytest

from ldporto_curator.final_camera import refine_from_existing_metadata
from ldporto_curator.smart_composition import improve_camera_plan
from ldporto_curator.director_config import resolve_smart_zoom
from ldporto_curator.persisted_plan import editorial_fingerprint


META = {'width':1920, 'height':1080}


def evidence(seconds=12):
    return {'observations':[{'time':i*.2, 'person_id':'VISUAL_HOST', 'track_id':'TRACK',
        'shot_id':'SHOT', 'face_visible':True, 'safe_crop_possible':True,
        'detection_confidence':.96, 'sharpness':150.,
        'face_bbox':{'x':.43, 'y':.2, 'width':.10, 'height':.18}}
        for i in range(seconds*5)],
        'shots':[{'shot_id':'SHOT', 'start':0., 'end':float(seconds)}],
        'broadcast_graphics':{'intervals':[]}}


def crop_plan(seconds=12):
    return {'mode':'adaptive_timeline', 'segments':[{'start':0., 'end':float(seconds),
        'mode':'crop', 'person_id':'VISUAL_HOST', 'person_ids':[],
        'center_x':.48, 'center_x_start':.48, 'center_x_end':.48,
        'center_y_start':.5, 'center_y_end':.5, 'zoom':1., 'motion_follow':True,
        'motion_easing':'smoothstep', 'subject_screen_y':.5, 'reason':'DOMINANT_FACE',
        'evidence_role':'DOMINANT_FACE', 'graphics_policy':'none'}]}


def test_zoom_envelope_is_configurable_optional_and_one_per_stable_host_shot():
    micro=evidence()
    new=improve_camera_plan(crop_plan(),micro,META,0.,12.,
        {'director_style':{'smart_zoom':{'micro_zoom_factor':1.025, 'micro_zoom_duration':4.,
                                       'micro_zoom_min_hold_seconds':4.}}})
    row=new['segments'][0]
    assert (row['zoom_start'],row['zoom_end']) == (1.,1.025)
    assert row['zoom_transition_start']==4.
    assert row['zoom_transition_duration']==4.
    assert row['zoom_easing']=='smoothstep'
    disabled=improve_camera_plan(crop_plan(),micro,META,0.,12.,
        {'director_style':{'smart_zoom':{'enabled':False}}})
    assert disabled['segments'][0]['zoom']==1.
    assert 'zoom_start' not in disabled['segments'][0]
    for invalid in (1.051,.99,float('nan')):
        with pytest.raises(ValueError):
            resolve_smart_zoom({'micro_zoom_factor':invalid})


def test_missing_measurements_never_create_new_zoom_or_guess_the_host():
    for change in ('gap','second_face','quality'):
        micro=evidence()
        if change=='gap':
            micro['observations']=[r for r in micro['observations'] if not 4 < r['time'] < 6]
        elif change=='second_face':
            other=deepcopy(micro['observations'][20]);other['person_id']='OTHER'
            micro['observations'].append(other)
        else:
            micro['observations'][20]['sharpness']=None
        row=improve_camera_plan(crop_plan(),micro,META,0.,12.)['segments'][0]
        assert row.get('zoom',1.)==1.


@pytest.mark.parametrize('measurement', ['shoulders','hands'])
def test_measured_wide_shoulders_and_gestures_preserve_full_source(measurement):
    micro=evidence()
    for row in micro['observations']:
        if measurement=='shoulders':
            row.update(body_visible=True,bbox_kind='body',
                       bbox={'x':.20,'y':.25,'width':.60,'height':.70})
        else:
            row['hand_bboxes']=[{'x':.8,'y':.5,'width':.1,'height':.1}]
    result=improve_camera_plan(crop_plan(),micro,META,0.,12.)
    row=result['segments'][0]
    assert row['mode']=='full_frame_blur'
    assert row['fallback_reason']=='HOST_BODY_OR_MOTION_UNSAFE_PRESERVE_SOURCE'


def test_new_camera_from_saved_evidence_never_calls_perception_or_mutates_frozen_inputs(monkeypatch):
    from ldporto_curator import final_camera
    def forbidden(*args,**kwargs):
        pytest.fail('Camera-only refinement attempted new perception')
    monkeypatch.setattr(final_camera,'inspect_clip',forbidden)
    monkeypatch.setattr(final_camera,'inspect_candidate_graphics',forbidden)
    clip={'source_start':0.,'source_end':12.,'camera_plan':crop_plan(),
          'caption_revision':{'frozen_camera':True}, 'title_text':'Approved title',
          'subtitle_plan':{'canonical_timeline_sha256':'a'*64}, 'approval':{'human_reviewed':True}}
    micro=evidence();before=deepcopy((clip,micro))
    new=refine_from_existing_metadata(clip,META,micro=micro)
    assert (clip,micro)==before
    assert new is not clip['camera_plan']
    assert new['diagnostics']['existing_metadata_only'] is True
    assert new['diagnostics']['new_analysis_executed'] is False
    assert new['needs_review'] is True
    assert any(row['mode']=='crop' for row in new['segments'])
    assert all(row.get('speaker_identity_confirmed') is not True for row in new['segments'])


def test_no_saved_visual_evidence_uses_a_reasoned_conservative_fallback():
    new=refine_from_existing_metadata({'source_start':3.,'source_end':9.},META)
    row=new['segments'][0]
    assert (row['start'],row['end'],row['mode'])==(0.,6.,'full_frame_blur')
    assert row['reason']=='INSUFFICIENT_EXISTING_VISUAL_EVIDENCE'


def test_legacy_crop_without_existing_evidence_is_not_recertified_and_blur_gets_a_reason():
    clip={'source_start':0.,'source_end':12.,'camera_plan':crop_plan()}
    assert refine_from_existing_metadata(clip,META,micro={})['segments'][0]['mode']=='full_frame_blur'
    clip['camera_plan']={'mode':'adaptive_timeline','segments':[{'start':0.,'end':12.,'mode':'full_frame_blur'}]}
    result=refine_from_existing_metadata(clip,META,micro={})
    assert result['segments'][0]['reason']=='INSUFFICIENT_EXISTING_VISUAL_EVIDENCE'
    assert result['diagnostics']['existing_micro_observations_available'] is False


def test_next_shot_face_at_exclusive_end_does_not_invalidate_prior_host():
    micro=evidence()
    other=deepcopy(micro['observations'][-1]);other.update(time=12.,person_id='NEXT_SHOT')
    micro['observations'].append(other)
    row=improve_camera_plan(crop_plan(),micro,META,0.,12.)['segments'][0]
    assert row['mode']=='crop' and row['zoom_end']>1.


def test_merged_camera_motion_is_checked_between_its_endpoints():
    plan=crop_plan()
    plan['segments'][0].update(center_x_start=.2,center_x_end=.8)
    row=improve_camera_plan(plan,evidence(),META,0.,12.)['segments'][0]
    assert row['mode']=='full_frame_blur'


def test_a_single_detection_jump_does_not_disable_a_stable_target_forever():
    from ldporto_curator.camera_evidence import VisualTargetEvidence
    from ldporto_curator.director_config import resolve_config
    tracker=VisualTargetEvidence()
    found=[]
    for row in evidence()['observations']:
        measured=deepcopy(row)
        if measured['time']==2.:
            measured['face_bbox']['x']+=.12
        result=tracker.update({'VISUAL_HOST':measured},measured['time'],'SHOT',resolve_config())
        if measured['time']>=5.:
            found.append(result)
    assert found and all(found)
    assert all(row['speaker_identity_confirmed'] is False for row in found)


def test_brief_focus_proposals_are_suppressed_without_holding_an_unsafe_crop():
    plan=crop_plan(8)
    crop=plan['segments'][0]
    crop.update(start=3.,end=4.,source_shot_id='SHOT')
    fallback={'start':0.,'end':3.,'mode':'full_frame_blur','source_shot_id':'SHOT',
              'reason':'INSUFFICIENT_VISUAL_EVIDENCE'}
    plan['segments']=[fallback,crop,{**fallback,'start':4.,'end':8.}]
    result=improve_camera_plan(plan,evidence(8),META,0.,8.)
    assert len(result['segments'])==1
    assert (result['segments'][0]['start'],result['segments'][0]['end'])==(0.,8.)
    assert result['segments'][0]['mode']=='full_frame_blur'
    assert result['diagnostics']['content_aware_camera']['brief_focus_proposals_suppressed']==1
    assert 'SHORT_UNSTABLE_FOCUS_PRESERVE_SOURCE' in result['segments'][0]['source_preserve_reasons']


def test_reel_approval_signature_binds_every_zoom_envelope_field():
    clip={'clip_id':'REEL','source_start':0.,'source_end':12.,'camera_plan':crop_plan()}
    row=clip['camera_plan']['segments'][0]
    row.update(zoom_start=1.,zoom_end=1.035,zoom_transition_start=3.,zoom_transition_duration=6.,zoom_easing='smoothstep')
    before=editorial_fingerprint([clip])
    for key,value in {'zoom_start':1.01,'zoom_end':1.025,'zoom_transition_start':4.,
                      'zoom_transition_duration':5.,'zoom_easing':'linear'}.items():
        changed=deepcopy(clip);changed['camera_plan']['segments'][0][key]=value
        assert editorial_fingerprint([changed])!=before


def test_saved_revision_script_fails_closed_when_clip_metadata_is_missing(tmp_path):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'scripts/REVISAR_CAMERA_SEM_QWEN.py'
    spec=importlib.util.spec_from_file_location('camera_metadata_revision_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError,match='planning_evidence'):
        module._existing_metadata(tmp_path,{}, {'clip_id':'REEL'})
    outside=tmp_path.parent/'unrelated_camera_evidence.json'
    with pytest.raises(ValueError,match='ausentes ou fora'):
        module._existing_metadata(tmp_path,{'planning_evidence':'../another'}, {'clip_id':'REEL'})
    assert not outside.exists()


@pytest.mark.skipif(shutil.which('ffmpeg') is None,reason='FFmpeg unavailable')
def test_eased_zoom_encode_preserves_frame_rate_frame_count_and_fills_all_edges(tmp_path):
    import cv2
    from ldporto_curator.render import _motion_crop_filter
    seg=crop_plan(2)['segments'][0]
    seg.update(zoom_start=1.,zoom_end=1.035,zoom_transition_start=.2,zoom_transition_duration=1.4,
               center_x_start=.02,center_x_end=.98,center_y_start=.02,center_y_end=.98)
    expression=_motion_crop_filter('0:v',seg,640,360,180,320,0)
    target=tmp_path/'bounded_zoom.mp4'
    result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=0x225588:s=640x360:r=30:d=2',
        '-filter_complex',expression,'-map','[v0]','-c:v','libx264','-pix_fmt','yuv420p',
        '-threads','2','-filter_complex_threads','2',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    cap=cv2.VideoCapture(str(target))
    try:
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT)==60
        assert cap.get(cv2.CAP_PROP_FPS)==30
        for index in (0,30,59):
            cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,frame=cap.read()
            assert ok and frame.shape[:2]==(320,180)
            assert min(frame[0].mean(),frame[-1].mean(),frame[:,0].mean(),frame[:,-1].mean())>20
    finally:
        cap.release()
