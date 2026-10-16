import cv2
import numpy as np
from ldporto_curator.micro_perception import inspect_clip
from ldporto_curator.camera_refinement import refine_camera_plan


def make_video(path, seconds=8, cut=False):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 360))
    assert writer.isOpened()
    for i in range(seconds * 10):
        frame = np.full((360, 640, 3), 30 if cut and i >= 40 else 160, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def face(x=.4):
    return {'face_bbox': {'x': x, 'y': .2, 'width': .12, 'height': .2}, 'detection_confidence': .95, 'safe_crop_possible': True}


def test_micro_perception_is_clip_only_cached_and_resets_tracks_at_cut(tmp_path):
    video = tmp_path / 'short.avi'
    make_video(video, cut=True)
    calls = []
    def detect(frame):
        calls.append(1)
        return [face()]
    clip = {'source_start': 1, 'source_end': 7}
    first = inspect_clip(video, clip, tmp_path / 'cache', {'sample_fps': 6}, detector=detect)
    second = inspect_clip(video, clip, tmp_path / 'cache', {'sample_fps': 6}, detector=detect)
    assert 30 <= len(calls) <= 42
    assert second['cache_hit']
    assert first['sampled_start'] >= 1 and first['sampled_end'] <= 7
    assert len(first['shots']) == 2
    assert len({r['track_id'] for r in first['observations']}) == 2
    assert not any(r.get('speaker_identity_confirmed') for r in first['observations'])


def test_stable_dominant_target_does_not_follow_small_jitter_or_guess_voice():
    observations = []
    for i in range(40):
        row = face(.4 + (.003 if i % 2 else 0))
        observations.append({**row, 'time': i / 5, 'track_id': 'T', 'person_id': 'LOCAL_T', 'shot_id': 'SHOT_0', 'face_visible': True})
    micro = {'observations': observations, 'shots': [{'shot_id': 'SHOT_0', 'start': 0, 'end': 8}],
             'broadcast_graphics': {'intervals': []}, 'status': 'measured'}
    plan = refine_camera_plan(micro, {'width': 1920, 'height': 1080}, 0, 8)
    crops = [s for s in plan['segments'] if s['mode'] == 'crop']
    assert crops
    assert plan['diagnostics']['target_switches'] <= 1
    assert all(s['evidence_role'] == 'DOMINANT_FACE' and s['speaker_identity_confirmed'] is False for s in crops)
    assert max(s.get('center_x_end', s['center_x']) for s in crops) - min(s.get('center_x_start', s['center_x']) for s in crops) < .01


def test_broadcast_safe_split_uses_one_strip_and_avoids_face_overlap():
    observations = []
    for i in range(40):
        for pid, x in [('A', .15), ('B', .7)]:
            observations.append({**face(x), 'time': i / 5, 'track_id': pid, 'person_id': pid, 'shot_id': 'SHOT_0', 'face_visible': True})
    graphics = {'intervals': [{'start': 0, 'end': 8, 'regions': [{'kind': 'lower_third', 'persistent': True, 'y_start': .75, 'y_end': .95}]}]}
    micro = {'observations': observations, 'shots': [{'shot_id': 'SHOT_0', 'start': 0, 'end': 8}], 'broadcast_graphics': graphics, 'status': 'measured'}
    plan = refine_camera_plan(micro, {'width': 1920, 'height': 1080}, 0, 8, suggested_layout='split_screen')
    split = [s for s in plan['segments'] if s['mode'] == 'split_screen']
    assert split and all(s['graphics_policy'] == 'single_copy_source_strip' for s in split)
    assert all(s['panel_source_height'] <= .75 for s in split)
    micro['observations'] = [{**r, 'face_bbox': {**r['face_bbox'], 'y': .7}} for r in observations]
    blocked = refine_camera_plan(micro, {'width': 1920, 'height': 1080}, 0, 8, suggested_layout='split_screen')
    assert all(s['mode'] == 'full_frame_blur' for s in blocked['segments'])


def test_second_curator_source_preserve_layout_is_honored():
    observations = [{**face(), 'time':i/5, 'track_id':'T', 'person_id':'LOCAL_T', 'shot_id':'S', 'face_visible':True} for i in range(40)]
    micro={'observations':observations,'shots':[{'shot_id':'S','start':0,'end':8}],'broadcast_graphics':{'intervals':[]}}
    plan=refine_camera_plan(micro,{'width':1920,'height':1080},0,8,suggested_layout='source_preserve')
    assert all(row['mode']=='full_frame_blur' for row in plan['segments'])


def test_reuse_requires_real_geometry_and_evidence_not_summary_or_uncertain_voice():
    from ldporto_curator.camera_refinement import use_analyzer_director
    source={'start':0,'end':10,'layout':'single_person','crop':{'safe':True},'focus_person':'P',
            'focus_confidence':.95,'camera_evidence_role':'DOMINANT_FACE','source_shot_id':'S',
            'camera':{'center_start':[.4,.5],'center_end':[.4,.5],'zoom_start':1,'zoom_end':1}}
    good=use_analyzer_director([source],1,9)
    assert good['diagnostics']['micro_perception_skipped']
    assert good['segments'][0]['speaker_identity_confirmed'] is False
    assert use_analyzer_director([{**source,'camera_evidence_role':'SOURCE_PRESERVE'}],1,9) is None
    assert use_analyzer_director([{**source,'crop':None,'safe_crop':True}],1,9) is None
    assert use_analyzer_director([{**source,'camera':{}}],1,9) is None


def test_static_split_releases_when_a_face_leaves_its_original_panel():
    observations=[]
    for i in range(70):
        for pid,x in [('A',.1+i*.008),('B',.8)]:
            observations.append({**face(x), 'time':i/5,'track_id':pid,'person_id':pid,'shot_id':'S','face_visible':True})
    micro={'observations':observations,'shots':[{'shot_id':'S','start':0,'end':14}],'broadcast_graphics':{'intervals':[]}}
    plan=refine_camera_plan(micro,{'width':1920,'height':1080},0,14,suggested_layout='split_screen')
    assert any(r['mode']=='split_screen' for r in plan['segments'])
    assert plan['diagnostics']['unsafe_crop_avoided'] > 0


def test_director_partial_window_keeps_its_original_motion_position():
    import pytest
    from ldporto_curator.camera_refinement import use_analyzer_director
    source={'start':0,'end':10,'layout':'single_person','crop':{'safe':True},'focus_person':'P',
            'focus_confidence':.95,'camera_evidence_role':'DOMINANT_FACE','source_shot_id':'S',
            'camera':{'center_start':[.3,.5],'center_end':[.7,.5],'zoom_start':1,'zoom_end':1}}
    good=use_analyzer_director([source],5,10)
    assert good['segments'][0]['center_x_start'] == pytest.approx(.5)
    bad={**source,'camera':{**source['camera'],'zoom_start':float('nan')}}
    assert use_analyzer_director([bad],0,10) is None


def test_long_valid_decision_keeps_bounds_and_uses_source_when_micro_budget_is_exceeded(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pytest
    from ldporto_curator import final_camera
    video=tmp_path/'source.avi'; make_video(video)
    bundle=SimpleNamespace(director=[],analysis={'metadata':{'width':640,'height':360,'duration':8}})
    clip={'source_start':0.,'source_end':6.,'camera_plan':{}}
    monkeypatch.setattr(final_camera,'inspect_clip',lambda *args,**kwargs:pytest.fail('Dense perception exceeded its budget'))
    plan=final_camera.refine_clip(bundle,clip,video,tmp_path/'output',{'micro_perception':{'max_clip_seconds':2}})
    assert plan['micro_status']=='skipped_budget'
    assert plan['segments'][0]['end']==6.
    assert plan['segments'][0]['mode']=='full_frame_blur'
    assert clip['source_end']==6.
    with pytest.raises(ValueError,match='actual source duration'):
        final_camera.refine_clip(bundle,{**clip,'source_end':9.},video,tmp_path/'bad',{'micro_perception':{'max_clip_seconds':2}})
