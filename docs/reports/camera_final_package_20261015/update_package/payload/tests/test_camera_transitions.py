"""Opt-in composition easing preserves the source clock and genuine shot cuts."""
from copy import deepcopy
import shutil
import subprocess

import pytest

from ldporto_curator.director_config import resolve_config
from ldporto_curator.persisted_plan import editorial_fingerprint
from ldporto_curator.render import _adaptive_camera_parts
from ldporto_curator.smart_composition import improve_camera_plan


def plan(duration=12.):
    fallback={'mode':'full_frame_blur','source_shot_id':'SHOT','start':0.,'end':3.}
    crop={'start':3.,'end':duration-3.,'mode':'crop','person_id':'HOST','source_shot_id':'SHOT',
          'center_x':.48,'center_x_start':.48,'center_x_end':.48,
          'center_y_start':.5,'center_y_end':.5,'subject_screen_y':.5,'zoom':1.,
          'motion_follow':True,'motion_easing':'smoothstep','graphics_policy':'none','reason':'DOMINANT_FACE'}
    return {'mode':'adaptive_timeline','segments':[fallback,crop,{**fallback,'start':duration-3.,'end':duration}]}


def micro():
    return {'observations':[{'time':i*.2,'person_id':'HOST','track_id':'TRACK','face_visible':True,
        'safe_crop_possible':True,'sharpness':150.,'detection_confidence':.95,
        'face_bbox':{'x':.43,'y':.2,'width':.10,'height':.18}} for i in range(60)]}


def test_new_plan_marks_only_verified_same_shot_transitions_and_preserves_inputs():
    original=plan();evidence=micro();before=deepcopy((original,evidence))
    new=improve_camera_plan(original,evidence,{'width':1920,'height':1080},0.,12.)
    assert (original,evidence)==before
    row=new['segments'][1]
    assert row['focus_transition_in']==row['focus_transition_out']==.35
    assert [(r['start'],r['end']) for r in new['segments']]==[(0.,3.),(3.,9.),(9.,12.)]
    original['segments'][2]['source_shot_id']='REAL_CUT'
    new=improve_camera_plan(original,evidence,{'width':1920,'height':1080},0.,12.)
    assert new['segments'][1]['focus_transition_in']==.35
    assert 'focus_transition_out' not in new['segments'][1]
    disabled=improve_camera_plan(original,evidence,{'width':1920,'height':1080},0.,12.,
                                {'director_style':{'focus_transition_seconds':0.}})
    assert all('focus_transition_in' not in row and 'focus_transition_out' not in row for row in disabled['segments'])


@pytest.mark.parametrize('value',[-.1,.451,float('nan'),True])
def test_transition_configuration_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        resolve_config({'focus_transition_seconds':value})


def test_legacy_plan_has_unchanged_filter_path_and_transition_fields_bind_reel_approval():
    original=plan()
    parts,_=_adaptive_camera_parts(original,640,360,180,320,12.)
    assert 'blend=' not in ';'.join(parts)
    clip={'clip_id':'REEL','camera_plan':original}
    before=editorial_fingerprint([clip])
    for field in ('focus_transition_in','focus_transition_out'):
        changed=deepcopy(clip);changed['camera_plan']['segments'][1][field]=.35
        assert editorial_fingerprint([changed])!=before


@pytest.mark.parametrize('change',['shot','unknown_shot','graphics','oversize'])
def test_renderer_rejects_transition_metadata_that_crosses_a_cut_or_unsafe_layout(change):
    camera=plan();row=camera['segments'][1];row['focus_transition_in']=.35
    if change=='shot':
        camera['segments'][0]['source_shot_id']='OTHER'
    elif change=='unknown_shot':
        row.pop('source_shot_id')
    elif change=='graphics':
        row['graphics_policy']='single_copy_source_strip'
    else:
        row['focus_transition_in']=.46
    with pytest.raises(ValueError):
        _adaptive_camera_parts(camera,640,360,180,320,12.)


@pytest.mark.skipif(shutil.which('ffmpeg') is None,reason='FFmpeg unavailable')
def test_transition_blends_identical_frames_at_midpoint_without_frame_or_audio_loss(tmp_path):
    import cv2
    import numpy as np
    camera=plan()
    camera['segments'][0].update(end=1.)
    camera['segments'][1].update(start=1.,end=3.,focus_transition_in=.4,focus_transition_out=.4)
    camera['segments'][2].update(start=3.,end=4.)
    crop=deepcopy(camera['segments'][1]);crop.update(start=0.,end=4.)
    crop.pop('focus_transition_in');crop.pop('focus_transition_out')
    source={'mode':'adaptive_timeline','segments':[{'start':0.,'end':4.,'mode':'full_frame_blur'}]}
    cameras=[source,{'mode':'adaptive_timeline','segments':[crop]},camera]
    frames=[];audios=[]
    for index,item in enumerate(cameras):
        target=tmp_path/f'composition_{index}.mkv'
        parts,label=_adaptive_camera_parts(item,640,360,180,320,4.)
        result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=20:d=4',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
            '-filter_complex',';'.join(parts),'-map',label,'-map','1:a:0','-t','4',
            '-c:v','ffv1','-c:a','aac','-b:a','128k','-threads','2','-filter_complex_threads','2',str(target)],
            capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        cap=cv2.VideoCapture(str(target));selected={};count=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok:
                    break
                if count in (20,24,28,40,52,56,60):
                    selected[count]=frame
                    assert min(frame[:4].mean(),frame[-4:].mean(),frame[:,:4].mean(),frame[:,-4:].mean())>5
                count+=1
        finally:
            cap.release()
        assert count==80
        frames.append(selected)
        audios.append(subprocess.run(['ffmpeg','-v','error','-i',str(target),'-vn','-ac','1',
            '-ar','48000','-f','s16le','pipe:1'],capture_output=True,check=True).stdout)
    wide,portrait,blended=frames
    assert audios[0]==audios[1]==audios[2]
    assert np.abs(blended[20].astype(float)-wide[20]).mean()<1.
    assert np.abs(blended[40].astype(float)-portrait[40]).mean()<1.
    for index in (24,56):
        midpoint=(wide[index].astype(float)+portrait[index].astype(float))/2
        assert np.abs(blended[index].astype(float)-midpoint).mean()<2.
        assert np.abs(blended[index].astype(float)-wide[index]).mean()>5.
        assert np.abs(blended[index].astype(float)-portrait[index]).mean()>5.
