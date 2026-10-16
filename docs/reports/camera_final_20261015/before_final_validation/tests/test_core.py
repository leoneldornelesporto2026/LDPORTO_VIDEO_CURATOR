import json, tempfile, pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ldporto_curator.analysis_loader import load_bundle
from ldporto_curator.curator import curate
from ldporto_curator.camera import build_camera_plan
from ldporto_curator.subtitles import ass_time,srt_time,wrap_caption
from ldporto_curator.config import load_config
ROOT=pathlib.Path(__file__).resolve().parents[1]
FIX=ROOT/'tests'/'fixture'/'video_87cfcb5f5347'

def test_fixture_loads():
    b=load_bundle(FIX); assert b.video_id=='wA1ipztt54c'; assert len(b.words)>2000; assert len(b.scenes)>100

def test_human_curated_first():
    b=load_bundle(FIX); cfg=load_config(ROOT/'config.yaml'); ds=curate(b,cfg,ROOT); assert ds[0]['rank']==1; assert 30<=ds[0]['duration']<=120; assert 'CHARLIE BROWN' in ds[0]['title_text']

def test_camera_safe():
    b=load_bundle(FIX); cfg=load_config(ROOT/'config.yaml'); d=curate(b,cfg,ROOT)[0]; c=build_camera_plan(b,d); assert 0.15<=c['normalized_center_x']<=0.85; assert c['dynamic_active_speaker'] is False

def test_times(): assert ass_time(62.34)=='0:01:02.34' and srt_time(62.34).startswith('00:01:02,')
def test_wrap_max_two_lines(): assert wrap_caption('um dois tres quatro cinco seis sete oito nove dez onze doze',12).count('\\N')<=1

def test_title_card_is_real_white_box(tmp_path):
    from PIL import Image
    from ldporto_curator.title_card import create_title_card
    cfg=load_config(ROOT/'config.yaml')
    p=create_title_card({'title_text':'RICK PEITOU O CHEFE PELO CHARLIE BROWN JR.'},tmp_path,cfg,preview=True)
    assert p and p.exists()
    im=Image.open(p).convert('RGBA')
    px=list(im.getdata())
    assert any(r>245 and g>245 and b>245 and a==255 for r,g,b,a in px)
    assert any(r<30 and g<30 and b<30 and a>200 for r,g,b,a in px)


def test_single_face_plus_body_never_splits():
    from ldporto_curator.camera import _classify_interval
    t={'recommended_layout':'two_person_scene','people_positions':[
        {'center':{'x':0.35},'face_bbox':{'x':0.28,'y':0.2,'width':0.14,'height':0.2},'safe_crop_possible':True},
        {'center':{'x':0.36},'bbox':{'x':0.20,'y':0.15,'width':0.30,'height':0.70},'bbox_kind':'body','safe_crop_possible':True},
    ]}
    assert _classify_interval(t)['mode']=='crop'


def test_two_distinct_faces_can_split():
    from ldporto_curator.camera import _classify_interval
    t={'recommended_layout':'two_person_scene','people_positions':[
        {'center':{'x':0.24},'face_bbox':{'x':0.17,'y':0.2,'width':0.13,'height':0.18},'safe_crop_possible':True},
        {'center':{'x':0.76},'face_bbox':{'x':0.69,'y':0.2,'width':0.13,'height':0.18},'safe_crop_possible':True},
    ]}
    d=_classify_interval(t)
    assert d['mode']=='split_screen' and len(d['split_centers_x'])==2


def test_speaker_mapping_has_priority_over_split():
    from types import SimpleNamespace
    from ldporto_curator.camera import _classify_interval
    b=SimpleNamespace(
        timeline=[{'start':10,'end':12,'speaker':'SPEAKER_01','active_person':None,'primary_person':None}],
        speaker_person_mapping=[{'speaker':'SPEAKER_01','person_id':'P_RIGHT','confidence':0.95}],
    )
    t={'start':10,'end':12,'recommended_layout':'two_person_scene','people_positions':[
        {'person_id':'P_LEFT','center':{'x':0.25},'face_bbox':{'x':0.18,'y':0.2,'width':0.13,'height':0.2},'safe_crop_possible':True},
        {'person_id':'P_RIGHT','center':{'x':0.75},'face_bbox':{'x':0.68,'y':0.2,'width':0.13,'height':0.2},'safe_crop_possible':True},
    ]}
    d=_classify_interval(t,bundle=b,camera_cfg={})
    assert d['mode']=='crop' and d['center_x']>0.7 and d['speaker_evidence'] is True


def test_lip_activity_can_choose_active_face():
    from ldporto_curator.camera import _classify_interval
    t={'start':0,'end':1,'recommended_layout':'two_person_scene','people_positions':[
        {'person_id':'A','center':{'x':0.25},'face_bbox':{'x':0.18,'y':0.2,'width':0.13,'height':0.2},'safe_crop_possible':True,'lip_activity':0.03,'samples':5},
        {'person_id':'B','center':{'x':0.75},'face_bbox':{'x':0.68,'y':0.2,'width':0.13,'height':0.2},'safe_crop_possible':True,'lip_activity':0.12,'samples':5},
    ]}
    d=_classify_interval(t,bundle=None,camera_cfg={'lip_min_samples':3,'lip_min_activity':0.035,'lip_activity_margin':1.35})
    assert d['mode']=='crop' and d['center_x']>0.7 and d['reason']=='lip_activity'


def test_question_turn_focus_uses_other_face_when_answerer_appears_next():
    from types import SimpleNamespace
    from ldporto_curator.camera import _apply_question_focus
    bundle=SimpleNamespace(
        questions_answers=[],
        captions=[
            {'start':1.0,'end':2.0,'text':'Qual a sua porcentagem de acerto?'},
            {'start':4.0,'end':5.0,'text':'Eu falo que tem potencial.'},
        ],
    )
    classified=[
        {'abs_start':0.0,'abs_end':3.0,'interval':{},'decision':{
            'mode':'split_screen','split_centers_x':[0.25,0.75],
            'person_ids':['GUEST','HOST'],'reason':'two_faces_speaker_uncertain'}},
        {'abs_start':5.2,'abs_end':7.0,'interval':{},'decision':{
            'mode':'crop','center_x':0.25,'reason':'single_detection'}},
    ]
    out=_apply_question_focus(classified,bundle,0.0,8.0,{
        'question_focus_heuristic':True,'question_focus_lookahead_seconds':9.0,'question_focus_match_x':0.16})
    d=out[0]['decision']
    assert d['mode']=='crop' and d['center_x']>0.7 and d['reason']=='question_turn_focus_inference'


def test_dense_observation_two_faces_beats_coarse_group_label():
    from types import SimpleNamespace
    from ldporto_curator.camera import _build_observation_intervals
    obs=[]
    for i,t in enumerate([0.10,0.25,0.40,0.55,0.70]):
        obs += [
            {'time':t,'face_visible':True,'safe_crop_possible':True,'person_id':'L','center':{'x':0.24,'y':0.4},'bbox':{'x':0.18,'y':0.25,'width':0.12,'height':0.20},'bbox_kind':'face','face_bbox':{'x':0.18,'y':0.25,'width':0.12,'height':0.20},'detection_confidence':0.9,'lip_opening':None},
            {'time':t,'face_visible':True,'safe_crop_possible':True,'person_id':'R','center':{'x':0.76,'y':0.4},'bbox':{'x':0.70,'y':0.25,'width':0.12,'height':0.20},'bbox_kind':'face','face_bbox':{'x':0.70,'y':0.25,'width':0.12,'height':0.20},'detection_confidence':0.9,'lip_opening':None},
        ]
    bundle=SimpleNamespace(people_observations=obs,scenes=[{'start':0,'end':2,'scene_id':'S','scene_type':'group'}])
    ints=_build_observation_intervals(bundle,0,1,{'observation_window_seconds':0.9})
    assert ints and ints[0]['recommended_layout']=='two_person_scene' and len(ints[0]['people_positions'])==2

def test_motion_follow_tracks_subject_and_limits_speed():
    from types import SimpleNamespace
    from ldporto_curator.camera import _motion_points_for_segment
    obs=[]
    for i,t in enumerate([0.0,0.3,0.6,0.9,1.2,1.5,1.8,2.1]):
        x=0.30+0.05*i
        obs.append({'time':t,'face_visible':True,'safe_crop_possible':True,'person_id':'STAR','center':{'x':x,'y':0.40},'head_center':{'x':x,'y':0.40},'bbox_kind':'face','bbox':{'x':x-0.05,'y':0.30,'width':0.10,'height':0.18},'face_bbox':{'x':x-0.05,'y':0.30,'width':0.10,'height':0.18},'detection_confidence':0.95,'lip_opening':0.18})
    b=SimpleNamespace(people_observations=obs)
    seg={'start':0.0,'end':2.1,'mode':'crop','center_x':0.30,'person_id':'STAR','speaker_evidence':True}
    cfg={'motion_keyframe_seconds':0.60,'motion_ema_alpha':0.5,'motion_deadzone_x':0.0,'motion_deadzone_y':0.0,'max_pan_speed_per_second':0.20,'max_tilt_speed_per_second':0.12,'smart_zoom':True,'min_zoom':1.0,'max_zoom':1.13,'zoom_face_height_small':0.10,'zoom_face_height_large':0.30,'zoom_max_step':0.02}
    pts=_motion_points_for_segment(b,seg,0.0,cfg)
    assert len(pts)>=2
    assert pts[-1]['x']>pts[0]['x']
    for a,c in zip(pts,pts[1:]):
        dt=max(1e-6,c['time']-a['time'])
        assert abs(c['x']-a['x'])/dt<=0.205
        assert 1.0<=c['zoom']<=1.13


def test_smart_zoom_opens_when_subject_moves_fast():
    from ldporto_curator.camera import _zoom_for_point
    cfg={'smart_zoom':True,'min_zoom':1.0,'max_zoom':1.13,'zoom_face_height_small':0.10,'zoom_face_height_large':0.30,'zoom_speaker_bonus':0.012,'zoom_motion_speed_threshold':0.10,'zoom_motion_widening':0.04,'zoom_max_step':1.0}
    still=_zoom_for_point({'h':0.12,'motion_speed':0.0,'lip_opening':0.1},True,cfg,None)
    fast=_zoom_for_point({'h':0.12,'motion_speed':0.22,'lip_opening':0.1},True,cfg,None)
    assert still>fast>=1.0


def test_motion_segments_keep_non_crop_modes_unchanged():
    from types import SimpleNamespace
    from ldporto_curator.camera import _expand_motion_segments
    segs=[{'start':0.0,'end':2.0,'mode':'split_screen','split_centers_x':[0.2,0.8]}]
    out=_expand_motion_segments(SimpleNamespace(people_observations=[]),segs,10.0,{'motion_follow':True})
    assert out==segs


def test_render_motion_crop_uses_time_expression():
    from ldporto_curator.render import _motion_crop_filter
    s={'start':0.0,'end':1.0,'center_x_start':0.25,'center_x_end':0.55,'center_y_start':0.4,'center_y_end':0.42,'zoom':1.08,'motion_follow':True}
    f=_motion_crop_filter('seg0',s,1920,1080,540,960,0)
    assert 'min(t\\,' in f and 'crop=' in f and 'scale=540:960' in f
