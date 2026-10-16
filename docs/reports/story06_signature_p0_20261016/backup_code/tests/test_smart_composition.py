"""Camera safety: conservative face zoom, verified map ROI, and untouched source history."""
from copy import deepcopy

from ldporto_curator.smart_composition import improve_camera_plan

META = {'width': 1920, 'height': 1080}
SHA = 'a' * 64


def plan(mode='crop', n=8):
    return {'mode': 'adaptive_timeline', 'schema_version': '4.4.0', 'needs_review': True,
        'segments': [{'start': 0., 'end': float(n), 'mode': mode,
            'person_id': 'LITO' if mode == 'crop' else None,
            'person_ids': [], 'zoom': 1., 'center_x': .47,
            'center_x_start': .47, 'center_x_end': .47,
            'center_y_start': .5, 'center_y_end': .5,
            'motion_follow': mode == 'crop', 'motion_easing': 'smoothstep',
            'reason': 'DOMINANT_FACE' if mode == 'crop' else 'SOURCE_PRESERVE',
            'evidence_role': 'DOMINANT_FACE' if mode == 'crop' else 'SOURCE_PRESERVE',
            'graphics_policy': 'none', 'crop_safe': True}],
        'diagnostics': {}}


def face_micro(stable=True, high_quality=True):
    rows=[]
    for i in range(16):
        rows.append({'time': i*.5, 'person_id': 'LITO' if stable else 'OTHER',
            'face_visible': True, 'safe_crop_possible': True,
            'face_bbox': {'x': .42, 'y': .20, 'width': .10, 'height': .18},
            'sharpness': 120. if high_quality else None})
    return {'observations':rows}


def map_region(kind='map', bbox=None, verified=True):
    bbox=bbox or {'x': .57, 'y': .23, 'width': .11, 'height': .25}
    return {'kind':kind,'evidence_kind':'visual_region', 'reviewed':verified,
       'start':2.,'end':6., 'samples':[{'observed_at':t, 'frame_sha256':SHA,'bbox':bbox}
             for t in (2.,4.,6.)]}


def test_host_zoom_only_with_verified_stable_geometry():
    original=plan()
    micro=face_micro()
    before=deepcopy(original)
    enhanced=improve_camera_plan(original,micro,META,0.,8.)
    assert 1.0 < enhanced['segments'][0]['zoom'] <= 1.045
    assert enhanced['segments'][0]['zoom_evidence'] == 'face_geometry_sharpness_verified'
    assert enhanced['diagnostics']['content_aware_camera']['host_micro_zoom_segments']==1
    assert enhanced['needs_review'] is True
    assert original == before


def test_no_zoom_if_quality_unknown_or_person_uncertain():
    for micro in (face_micro(high_quality=False), face_micro(stable=False), {},
                  {'observations':face_micro()['observations'][:3]}):
        enhanced=improve_camera_plan(plan(),micro,META,0.,8.)
        assert enhanced['segments'][0]['zoom']==1.


def test_no_invented_map_by_spoken_words():
    micro={'transcript': 'olha o mapa do aviao sobre a rota'}
    out=improve_camera_plan(plan('full_frame_blur'),micro,META,0.,8.)
    assert len(out['segments'])==1
    assert out['segments'][0]['mode']=='full_frame_blur'
    assert out['diagnostics']['content_aware_camera']['map_spatial_roi_segments']==0


def test_verified_map_region_focuses_safely_then_releases():
    micro={'visual_focus_regions':[map_region()]}
    output=improve_camera_plan(plan('full_frame_blur'),micro,META,0.,8.)
    segments=output['segments']
    assert [(s['start'],s['end']) for s in segments]==[(0,2),(2,6),(6,8)]
    assert [s['mode'] for s in segments]==['full_frame_blur','crop','full_frame_blur']
    assert segments[1]['evidence_role']=='MEASURED_MAP_ROI'
    assert segments[1]['zoom']==1.0
    assert segments[1]['needs_review'] is True
    assert output['diagnostics']['content_aware_camera']['map_spatial_roi_segments']==1


def test_wide_map_preserves_full_source():
    micro={'visual_focus_regions':[map_region(bbox={'x':.2,'y':.1,'width':.6,'height':.8})]}
    output=improve_camera_plan(plan('full_frame_blur'),micro,META,0.,8.)
    assert output['segments'][1]['mode']=='full_frame_blur'
    assert output['segments'][1]['reason']=='MAP_WIDE_KEEP_ALL_LABELS'
    assert output['diagnostics']['content_aware_camera']['map_wide_source_preserved_segments']==1


def test_unrefereed_unreviewed_or_invalid_map_is_ignored():
    for variant in ({'reviewed':False}, {'evidence_kind':'spoken_reference'},
                    {'samples':[{'observed_at':2,'frame_sha256':SHA,'bbox':{'x':.2,'y':.1,'width':.1,'height':.2}}]},
                    {'samples':[{'observed_at':t,'frame_sha256':'bad','bbox':{'x':.5,'y':.2,'width':.1,'height':.2}} for t in (2,4,6)]}):
        reg=map_region()
        reg.update(variant)
        result=improve_camera_plan(plan('full_frame_blur'),{'visual_focus_regions':[reg]},META,0.,8.)
        assert len(result['segments'])==1
        assert result['segments'][0]['mode']=='full_frame_blur'


def test_overlap_annotations_not_guessed():
    a=map_region(); b=map_region(); b.update(start=4.,end=7.)
    b['samples']=[{'observed_at':t,'frame_sha256':SHA, 'bbox':{'x':.4,'y':.2,'width':.1,'height':.2}} for t in (4,5,7)]
    result=improve_camera_plan(plan('full_frame_blur'),{'visual_focus_regions':[a,b]},META,0.,8.)
    assert len(result['segments'])==1
    assert result['segments'][0]['mode']=='full_frame_blur'


def test_no_tampering_with_other_camera_modes():
    original=plan('split_screen')
    original['segments'][0]['split_centers_x']=[.2,.8]
    result=improve_camera_plan(original,face_micro(),META,0.,8.)
    assert result['segments'][0]['mode']=='split_screen'
    assert result['segments'][0]['zoom']==1.


def test_out_of_scope_map_is_ignored():
    r=map_region(); r['end']=9.
    result=improve_camera_plan(plan('full_frame_blur'),{'visual_focus_regions':[r]},META,0.,8.)
    assert result['segments'][0]['mode']=='full_frame_blur' and len(result['segments'])==1


def test_refinement_pipeline_calls_content_policy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ldporto_curator import final_camera
    micro = face_micro()
    micro['status'] = 'measured'
    micro['shots']=[{'shot_id':'S','start':0.,'end':8.}]
    for row in micro['observations']:
        row.update(track_id='TRACK_LITO',shot_id='S',detection_confidence=.98)
    micro['broadcast_graphics']={'intervals':[]}
    monkeypatch.setattr(final_camera,'inspect_clip',lambda *args,**kwargs:micro)
    video=tmp_path/'original.mp4'
    video.write_bytes(b'not decoded because perception injected')
    bundle=SimpleNamespace(director=[], analysis={'metadata':META})
    clip={'source_start':0.,'source_end':8.,'camera_plan':{}}
    result=final_camera._refine_clip(bundle,clip,video,tmp_path,{'camera_v44':{}},None)
    assert result['diagnostics']['content_aware_camera']['host_micro_zoom_segments'] >= 0
    assert (tmp_path/'FINAL_CAMERA_PLAN_V44.json').is_file()
    assert clip['camera_plan'] is result
    assert all(seg.get('zoom',1.)<=1.045 for seg in result['segments'])
