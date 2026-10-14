from types import SimpleNamespace
import pytest
from ldporto_curator.eta import CuratorEta
from ldporto_curator.source_video import resolve_source, SourceUnavailable


def test_eta_does_not_extrapolate_total_from_equal_stage_counts(tmp_path):
    clock=[0.]; eta=CuratorEta(tmp_path/'history.json',{},clock=lambda:clock[0])
    eta.context({'duration':120},[{'duration':30}])
    event={'stage':'1:render','step':1,'plan':['render','finalize'],'stage_fraction':0}
    assert eta.update(event)['stage_range_seconds'] is None
    for i in range(1,5):
        clock[0]=i*2
        result=eta.update({**event,'stage_fraction':i/10})
    assert result['stage_range_seconds'][0] == pytest.approx(12)
    assert result['total_range_seconds'] is None


def test_missing_source_requires_explicit_rehydration_and_rejects_wrong_original(tmp_path):
    bundle=SimpleNamespace(root=tmp_path/'analysis', video_id='no_source', analysis={'metadata':{'sha256':'0'*64}})
    cfg={'paths':{'source_cache':str(tmp_path/'cache')}}
    with pytest.raises(SourceUnavailable):
        resolve_source(bundle,'no_source',cfg)
    video=tmp_path/'source.mp4'; video.write_bytes(b'wrong media')
    cfg['source_media']={'path':str(video)}
    with pytest.raises(ValueError, match='SHA256'):
        resolve_source(bundle,'no_source',cfg)


def test_eta_history_separates_gpu_and_resets_costs_for_a_new_operation(tmp_path, monkeypatch):
    from ldporto_curator import eta
    monkeypatch.setattr(eta,'gpu_profile',lambda:['GPU_A'],raising=False)
    model=CuratorEta(tmp_path/'history.json',{})
    model.context({'duration':120},[{'duration':30}],operation='preview')
    first=model.key
    model.costs={'1:previous':100}
    monkeypatch.setattr(eta,'gpu_profile',lambda:['GPU_B'])
    model.context({'duration':120},[{'duration':30}],operation='preview')
    assert model.key != first
    assert model.costs == {}
