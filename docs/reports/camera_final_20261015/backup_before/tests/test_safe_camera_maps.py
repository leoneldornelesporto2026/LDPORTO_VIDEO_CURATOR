from copy import deepcopy

import pytest

from ldporto_curator.series_workflow import conservative_camera


def _episode(mode="AUTO_CONSERVADOR"):
    return {"source_start":0.,"source_end":10.,"duration":10.,"camera_mode":mode}


def _geometry():
    return {"timeline":[{"start":0.,"end":10.,"people_positions":[{"center":{"x":.5,"y":.4},
               "face_bbox":{"x":.4,"y":.2,"width":.2,"height":.3},"safe_crop_possible":True}]}]}


def _assert_preserved(result):
    assert result["mode"]=="full_frame_blur"
    assert result["speaker_identity"]=="unverified"
    assert result["crop_safe"] is False
    assert all(segment["mode"]=="full_frame_blur" for segment in result["segments"])


@pytest.mark.parametrize("kind", ["mapa de rota","cockpit e instrumentos","gráfico","OCR","tela com altitude"])
@pytest.mark.parametrize("field", ["timeline","scenes"])
def test_critical_visuals_preserve_source_despite_face_geometry(kind,field):
    evidence=_geometry()
    evidence.setdefault(field,[]).append({"start":0,"end":10,"description":kind})
    _assert_preserved(conservative_camera(evidence,_episode(),{}))


@pytest.mark.parametrize("mode", ["AUTO_CONSERVADOR","FOCO_PESSOA","DOIS_PARTICIPANTES"])
def test_absent_geometry_never_creates_tracking_or_confirmed_speaker(mode):
    _assert_preserved(conservative_camera({"timeline":[{"start":0,"end":10,"speaker":"SPEAKER_00"}]},_episode(mode),{}))


@pytest.mark.parametrize("change", [{"safe_crop_possible":False},{"safe_crop_possible":None},{}])
def test_missing_or_unsafe_crop_confirmation_preserves_source(change):
    evidence=_geometry()
    evidence["timeline"][0]["people_positions"][0].pop("safe_crop_possible")
    evidence["timeline"][0]["people_positions"][0].update(change)
    _assert_preserved(conservative_camera(evidence,_episode(),{}))


def test_visual_geometry_gap_remains_fallback():
    evidence=_geometry(); evidence["timeline"][0]["end"]=4
    _assert_preserved(conservative_camera(evidence,_episode(),{}))


def test_original_camera_always_preserves_source():
    _assert_preserved(conservative_camera(_geometry(),_episode("SOURCE_PRESERVE"),{}))


def test_single_visual_face_does_not_become_confirmed_active_speaker(monkeypatch):
    monkeypatch.setattr("ldporto_curator.camera.build_camera_plan",lambda *args:
        {"mode":"adaptive_timeline","segments":[{"start":0,"end":10,"mode":"crop","reason":"single_detection"}]})
    _assert_preserved(conservative_camera(_geometry(),_episode("FOCO_PESSOA"),{}))
    result=conservative_camera(_geometry(),_episode(),{})
    assert result["speaker_identity"]=="unverified"
    assert result["crop_safe"]=="needs_human_review"
    assert not result["segments"][0].get("speaker_evidence")


def test_two_participants_requires_real_split_geometry(monkeypatch):
    monkeypatch.setattr("ldporto_curator.camera.build_camera_plan",lambda *args:
        {"mode":"adaptive_timeline","segments":[{"start":0,"end":10,"mode":"crop","reason":"single_detection"}]})
    _assert_preserved(conservative_camera(_geometry(),_episode("DOIS_PARTICIPANTES"),{}))


@pytest.mark.parametrize("point", [{"time":0,"x":1.1},{"time":0,"zoom":1.4},{"time":float("nan")},{"time":-1}])
def test_manual_keyframes_reject_unphysical_values(point):
    episode=_episode("MANUAL_KEYFRAMES"); episode["camera_keyframes"]=[point]
    with pytest.raises(ValueError):
        conservative_camera({},episode,{})


def test_manual_camera_rejects_excessive_motion_speed():
    episode=_episode("MANUAL_KEYFRAMES")
    episode["camera_keyframes"]=[{"time":0,"x":.1},{"time":1,"x":.9}]
    with pytest.raises(ValueError,match="velocidade"):
        conservative_camera({},episode,{})


def test_critical_visual_at_sample_timestamp_also_preserves_source():
    evidence=_geometry()
    evidence["frame_samples"]=[{"time":5,"description":"Mapa de rota e altitude na tela","scene_id":"map_scene"}]
    _assert_preserved(conservative_camera(evidence,_episode(),{}))


def test_explicit_visual_crop_risk_preserves_source():
    evidence=_geometry()
    evidence["scenes"]=[{"start":0,"end":10,"crop_risk":"high","critical_content":True}]
    _assert_preserved(conservative_camera(evidence,_episode(),{}))


def test_episode_risk_flag_preserves_unmeasured_critical_visual():
    episode=_episode(); episode["risk_flags"]=["critical_visuals_need_source_preservation"]
    _assert_preserved(conservative_camera(_geometry(),episode,{}))
