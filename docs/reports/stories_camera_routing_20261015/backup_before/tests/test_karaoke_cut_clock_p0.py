"""Regression: seeked Stories must use the same zero-based PTS as the ASS clock."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ldporto_curator.render import _base_cmd, _finish_video_parts
from ldporto_curator.subtitle_presets import write_episode_subtitles


def test_subtitles_follow_rebased_avtb_video_clock():
    parts, label = _finish_video_parts([], '[vcam]', 'CAPTIONS.ass', None, 0)
    assert label == '[vsub]'
    assert len(parts) == 1
    assert parts[0].startswith('[vcam]settb=AVTB,setpts=PTS-STARTPTS,subtitles=')


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_real_seeked_video_cumulative_white_starts_at_word_onset(tmp_path):
    """Test actual decoded MP4 frames, not just ASS expressions or source timestamps."""
    import numpy as np
    from PIL import Image

    src = tmp_path / 'input.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=0x202020:s=320x180:r=24:d=4', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000:duration=4', '-shortest',
                    '-c:v', 'libx264', '-g', '48', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-y', str(src)], check=True)
    start = 1.125
    text = 'PILOTO NAVEGANDO AGORA'
    data = {'segments':[{'segment_id':'S1','start':start,'end':start+2,
        'text':text,'words':[
           {'word_id':'W1','word':'PILOTO','start':start,'end':start+.4},
           {'word_id':'W2','word':'NAVEGANDO','start':start+.5,'end':start+.85},
           {'word_id':'W3','word':'AGORA','start':start+1.2,'end':start+1.5}]}]}
    episode = {'episode_id':'fixture','source_start':start,'source_end':start+2,'duration':2}
    results = write_episode_subtitles(data,episode,tmp_path/'caption',preset='LDP_REELS_KARAOKE')
    assert results['sync']['renderable']
    cfg = {'render':{'preview_width':540,'preview_height':960,'audio_lufs':-14,
                      'audio_true_peak':-1.5},'title':{'duration':0}}
    clip = episode | {'camera_plan':{'mode':'full_frame_blur'}, 'title_duration':0}
    out=tmp_path/'encoded.mp4'
    cmd,_,_=_base_cmd(None,clip,src,out,Path(results['ass']),None,cfg,True,'libx264')
    subprocess.run(cmd[:1] + ['-hide_banner','-v','error'] + cmd[1:],check=True,timeout=75)
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                          'frame=best_effort_timestamp_time','-of','json',str(out)],
                          capture_output=True,text=True,check=True)
    pts=[float(f['best_effort_timestamp_time']) for f in json.loads(probe.stdout)['frames']]
    before=max((i for i,t in enumerate(pts) if t<.5-.001),key=lambda i:pts[i])
    after=min((i for i,t in enumerate(pts) if t>=.5-.001),key=lambda i:pts[i])
    assert pts[after]-pts[before]<=.05

    def frame(index):
        result=subprocess.run(['ffmpeg','-hide_banner','-v','error','-i',str(out),'-vf',
             f'select=eq(n\\,{index})','-frames:v','1','-f','image2pipe','-vcodec','png','-'],
             capture_output=True,check=True,timeout=30)
        import io
        return np.array(Image.open(io.BytesIO(result.stdout)).convert('RGB'))[680:850]

    first,second=frame(before),frame(after)
    def color_counts(pixels):
        r,g,b=pixels[:,:,0].astype(int),pixels[:,:,1].astype(int),pixels[:,:,2].astype(int)
        white=int(((r>183)&(g>183)&(b>183)&(np.maximum.reduce((r,g,b))-np.minimum.reduce((r,g,b))<48)).sum())
        yellow=int(((r>160)&(g>95)&(b<145)&((r-b)>75)).sum())
        return white,yellow
    wb,yb=color_counts(first);wa,ya=color_counts(second)
    assert wa>wb+25, (pts[before],pts[after],(wb,yb),(wa,ya))
    assert ya<yb-25, (pts[before],pts[after],(wb,yb),(wa,ya))
