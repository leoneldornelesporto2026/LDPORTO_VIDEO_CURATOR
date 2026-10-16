"""The encoded MP4, libass and speech must share the post-seek output clock."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from ldporto_curator.render import _base_cmd, _finish_video_parts
from ldporto_curator.subtitle_presets import write_episode_subtitles


pytestmark=pytest.mark.skipif(shutil.which("ffmpeg") is None,reason="FFmpeg local ausente")


def run(*args):
    return subprocess.run([str(value) for value in args],check=True,capture_output=True)


def frames(path):
    result=run("ffmpeg","-v","error","-i",path,"-map","0:v:0","-f","rawvideo","-pix_fmt","rgb24","-")
    return np.frombuffer(result.stdout,dtype=np.uint8).reshape((-1,480,270,3))


def audio(path,*seek):
    result=run("ffmpeg","-v","error",*seek,"-i",path,"-map","0:a:0","-ac","1","-ar","48000","-f","f32le","-")
    return np.frombuffer(result.stdout,dtype=np.float32)


def source(tmp_path):
    path=tmp_path/"source.mp4"
    # Real 25fps MP4 frames carry a changing gray marker above the subtitles;
    # AAC contains a measured tone beginning at source .113s. A seek to .013s
    # leaves the first decoded video frame at .027s on FFmpeg's input clock.
    run("ffmpeg","-v","error","-y","-f","lavfi","-i",
        "color=c=black:s=270x480:r=25:d=1,geq=lum='16+mod(N,20)*4':cb=128:cr=128",
        "-f","lavfi","-i","aevalsrc=if(between(t\\,0.113\\,0.153)\\,0.5*sin(2*PI*1000*t)\\,0):s=48000:d=1",
        "-c:v","libx264","-preset","ultrafast","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-shortest",path)
    return path


def test_finish_resets_output_clock_immediately_before_libass():
    parts,label=_finish_video_parts([],"[vcam]","captions.ass",None,0)
    assert parts==["[vcam]setpts=PTS-STARTPTS,subtitles='captions.ass'[vsub]"]
    assert label=="[vsub]"


def test_actual_seeked_mp4_colors_never_anticipate_word_and_audio_keeps_its_timing(tmp_path):
    media=source(tmp_path)
    seek=.013
    words=[{"word_id":f"W{i}","segment_id":"S","word":"WWW","start":seek+a,"end":seek+b}
           for i,(a,b) in enumerate(((0,.06),(.1,.2),(.25,.5)))]
    result=write_episode_subtitles(
        {"segments":[{"segment_id":"S","start":seek,"end":seek+.6,"text":"WWW WWW WWW"}],"words":words},
        {"source_start":seek,"source_end":seek+.6},tmp_path/"captions",
        preset="LDP_REELS_KARAOKE",width=270,height=480)
    assert len(result["sync"]["events"])==1
    clip={"source_start":seek,"duration":.6,"camera_plan":{"mode":"manual_crop"}}
    cfg={"render":{"preview_width":270,"preview_height":480,"audio_lufs":-14,"audio_true_peak":-1.5}}
    out=tmp_path/"encoded.mp4"
    command,_,_=_base_cmd(None,clip,media,out,Path(result["ass"]),None,cfg,True,"libx264")
    run(*command)

    decoded=frames(out)
    counts=np.all(decoded[:,350:450,:,:]>190,axis=3).sum(axis=(1,2))
    one_word=int(counts[0]);assert one_word>30
    # At output .08s, libass must still show just the first word in white.
    # Before the clock reset it evaluated .107s and whitened word two early.
    assert int(counts[2])<one_word*1.4
    assert int(counts[3])>one_word*1.7
    first_two=next(index for index,count in enumerate(counts) if count>one_word*1.7)
    assert first_two==3 and first_two/25>=.1

    probe=json.loads(run("ffprobe","-v","error","-select_streams","v:0","-show_entries",
        "frame=best_effort_timestamp_time","-of","json",out).stdout)
    times=[float(frame["best_effort_timestamp_time"]) for frame in probe["frames"]]
    assert times[:4]==pytest.approx([0,.04,.08,.12])

    # The correction changes the evaluation clock, not which decoded source
    # frames are shown. Compare the marker with a plain precise-seek reference.
    reference=tmp_path/"reference.mp4"
    run("ffmpeg","-v","error","-y","-ss",str(seek),"-i",media,"-t","0.6",
        "-an","-c:v","libx264","-crf","20","-pix_fmt","yuv420p",reference)
    baseline=frames(reference)
    assert len(decoded)==len(baseline)
    assert np.max(np.abs(decoded[:,:100,:,:].astype(int)-baseline[:,:100,:,:].astype(int)))<=3

    # Loudness normalization and AAC encoding may change amplitude and create
    # small edge ringing. Their tone onset must retain the original seek-relative
    # timing; there is no audio offset or sample-clock correction in this fix.
    original=audio(media,"-ss",str(seek))
    encoded=audio(out)
    def onset(samples):
        energy=np.convolve(samples.astype(float)**2,np.ones(48)/48,mode="same")
        return int(np.flatnonzero(energy>energy.max()*.1)[0])/48000
    assert onset(original)==pytest.approx(.1,abs=.003)
    assert onset(encoded)==pytest.approx(onset(original),abs=.003)
