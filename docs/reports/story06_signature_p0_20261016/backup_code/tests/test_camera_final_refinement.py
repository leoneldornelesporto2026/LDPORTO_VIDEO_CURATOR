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


def test_legacy_graphics_candidates_cannot_duplicate_a_shirt_or_shelves():
    micro=evidence()
    micro['broadcast_graphics']={'intervals':[{'start':0.,'end':12.,'regions':[
        {'kind':'lower_third','persistent':True,'y_start':.7,'y_end':.9,
         'confidence':.75,'needs_review':True,'measurement':'graphic_candidate_not_text_recognition'}]}]}
    result=refine_from_existing_metadata({'source_start':0.,'source_end':12.},META,micro=micro)
    assert all(row['mode']=='full_frame_blur' for row in result['segments'])
    assert result['diagnostics']['unreviewed_graphics_source_preserved']>=1


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


@pytest.mark.skipif(shutil.which('ffmpeg') is None,reason='FFmpeg unavailable')
@pytest.mark.parametrize('audio_mode',['original','normalize'])
def test_static_dynamic_and_graphics_cameras_preserve_the_full_editorial_audio_clock(tmp_path,audio_mode):
    import cv2
    import json
    from ldporto_curator.render import _base_cmd
    from ldporto_curator.media_effects import extend_render_command
    source=tmp_path/'source.mkv'
    result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=0x225588:s=640x360:r=24000/1001:d=4',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
        '-c:v','ffv1','-c:a','pcm_s16le','-threads','2',str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    ass=tmp_path/'captions.ass'
    ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 180\nPlayResY: 320\n\n[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        'Style: Default,Arial,12,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,20,1\n\n[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n',encoding='utf-8')
    duration=2.37
    crop=crop_plan()['segments'][0]
    crop.update(start=.7,end=1.9,zoom_start=1.,zoom_end=1.035,
                zoom_transition_start=.1,zoom_transition_duration=.8)
    fallback={'mode':'full_frame_blur','start':0.,'end':.7}
    gc={**crop,'start':0.,'end':duration,'graphics_policy':'single_copy_source_strip',
        'graphics_regions':[{'kind':'lower_third','persistent':True,'y_start':.6,'y_end':.91}],
        'panel_source_height':.6}
    for key in ('zoom_start','zoom_end','zoom_transition_start','zoom_transition_duration'):
        gc.pop(key,None)
    plain_crop=crop_plan()['segments'][0];plain_crop.update(start=0.,end=duration)
    cameras=[{'mode':'full_frame_blur'}, {'mode':'adaptive_timeline','segments':[plain_crop]},
        {'mode':'adaptive_timeline','segments':[fallback,crop,{**fallback,'start':1.9,'end':duration}]},
        {'mode':'adaptive_timeline','segments':[{**gc,'mode':'crop'}]},
        {'mode':'adaptive_timeline','segments':[{**gc,'mode':'split_screen','split_centers_x':[.3,.7]}]}]
    settings={'render':{'preview_width':180,'preview_height':320}}
    audios=[]
    for index,camera in enumerate(cameras):
        target=tmp_path/f'camera_{index}.mp4'
        cmd,_,_=_base_cmd(None,{'source_start':.13,'duration':duration,'camera_plan':camera},
                         source,target,ass,None,settings,True,'libx264')
        assert '-shortest' not in cmd
        assert cmd[cmd.index('-t')+1]=='2.370'
        assert cmd[cmd.index('-af')+1]=='loudnorm=I=-14:TP=-1.5:LRA=11'
        cmd=extend_render_command(cmd,{'audio':{'mode':audio_mode}},180,320,duration,tmp_path)
        assert ('-af' in cmd)==(audio_mode=='normalize')
        cmd[-1:-1]=['-threads','2','-filter_complex_threads','2','-loglevel','error']
        result=subprocess.run(cmd,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        pcm=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-vn','-ac','1','-ar','48000',
                            '-f','s16le','pipe:1'],capture_output=True,check=True).stdout
        audios.append(pcm)
        probe=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
            '-show_entries','stream=duration','-of','json',str(target)],capture_output=True,text=True,check=True).stdout)
        assert abs(float(probe['streams'][0]['duration'])-duration)<.001
        cap=cv2.VideoCapture(str(target))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC,1000)
            ok,frame=cap.read()
            assert ok
            assert min(frame[0].mean(),frame[-1].mean(),frame[:,0].mean(),frame[:,-1].mean())>20
        finally:
            cap.release()
    assert all(audio==audios[0] for audio in audios[1:])
