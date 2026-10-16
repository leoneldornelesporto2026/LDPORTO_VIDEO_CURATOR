import pytest
from ldporto_curator.timeline_editor import TimelineRange,timestamp


def test_preview_drag_does_not_mutate_saved_episode():
    episode={'source_start':12,'source_end':40}
    model=TimelineRange(100,12,40,boundaries=[12,40,50])
    model.drag('end',501,1000)
    assert model.end==50 and episode=={'source_start':12,'source_end':40}


def test_millisecond_boundaries_no_early_rounding():
    model=TimelineRange(900,0,899.999)
    model.drag('end',1000,1000,snap=False)
    assert model.end==900
    model.drag('start',999.9999,1000,snap=False)
    assert model.end-model.start==pytest.approx(.001)


def test_long_video_zoom_pan_and_canonical_pixel_roundtrip():
    model=TimelineRange(7200,4200.125,4220.125)
    model.zoom(120,4210)
    assert model.view_end-model.view_start==60
    for seconds in (4200.125,4210,4220.125):
        assert model.from_pixel(model.to_pixel(seconds,1000),1000)==pytest.approx(seconds)
    model.pan(-1000);assert model.view_start==0
    model.pan(1000);assert model.view_end==7200


def test_snap_is_optional_and_never_far_away():
    model=TimelineRange(100,10,80,boundaries=[60])
    model.drag('end',601,1000,snap=False);assert model.end==pytest.approx(60.1)
    model.drag('end',601,1000,snap=True);assert model.end==60
    model.drag('end',650,1000,snap=True);assert model.end==65


@pytest.mark.parametrize('start,end',[(20,10),(-1,10),(0,101),(0,float('nan'))])
def test_invalid_selection_rejected(start,end):
    with pytest.raises(ValueError):TimelineRange(100,start,end)


def test_timestamp_rollover():
    assert timestamp(59.9996)=='00:01:00.000'
