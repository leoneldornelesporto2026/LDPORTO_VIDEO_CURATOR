from pathlib import Path
from types import SimpleNamespace
import subprocess
import cv2
import numpy as np
import pytest
from ldporto_curator.render import render_clip
from ldporto_curator.config import load_config


@pytest.mark.parametrize('mode', ['split_screen', 'crop'])
def test_real_ffmpeg_split_keeps_one_lower_third_audio_subtitles_and_both_resolutions(tmp_path, mode):
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / 'config.yaml')
    cfg['render']['prefer_nvenc'] = False
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=1920x1080:r=10:d=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-vf', 'drawbox=x=0:y=810:w=1920:h=216:color=red:t=fill',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True)
    bundle = SimpleNamespace(captions=[{'start': 0, 'end': 2, 'text': 'Fala literal preservada.'}])
    camera = {'mode': 'adaptive_timeline', 'segments': [{'start': 0, 'end': 2, 'mode': mode,
        'split_centers_x': [.2, .8], 'panel_source_height': .75, 'graphics_policy': 'single_copy_source_strip',
        'graphics_regions': [{'kind': 'lower_third', 'persistent': True, 'y_start': .75, 'y_end': .95}]}]}
    clip = {'clip_id': 'GC_TEST', 'source_start': 0, 'source_end': 2, 'duration': 2, 'title_text': 'Teste de composição', 'camera_plan': camera}
    for preview in (True, False):
        output = render_clip(bundle, clip, source, tmp_path / ('preview' if preview else 'final'), cfg, preview=preview, log=lambda *a: None)
        cap = cv2.VideoCapture(str(output))
        cap.set(cv2.CAP_PROP_POS_MSEC, 1200)
        got, frame = cap.read()
        cap.release()
        assert got
        red = ((frame[:, :, 2].astype(float) > 120) & (frame[:, :, 1] < 80) & (frame[:, :, 0] < 80)).mean(axis=1) > .6
        starts = np.count_nonzero(np.diff(np.r_[False, red].astype(int)) == 1)
        assert starts == 1, 'GC duplicated across face panels'
        assert (output.parent / 'captions.ass').exists() or list(output.parent.glob('*.ass'))
