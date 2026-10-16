import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ldporto_curator.render import _ffmpeg_progress_fraction


def test_ffmpeg_progress_fraction():
    assert abs(_ffmpeg_progress_fraction(5_000_000, 10.0) - 0.5) < 1e-6
    assert _ffmpeg_progress_fraction(99_000_000, 10.0) == 1.0


def test_pipeline_emit_has_remaining_shape(tmp_path):
    from ldporto_curator.pipeline import Pipeline
    events=[]
    p=Pipeline({'paths':{}}, tmp_path, progress=events.append)
    plan=['A','B','C']
    p._emit(plan, 2, 'B', 0.5, 'meio')
    e=events[-1]
    assert e['step']==2 and e['total_steps']==3
    assert abs(e['overall_fraction']-0.5) < 1e-6
    assert e['stage_fraction']==0.5 and e['detail']=='meio'
