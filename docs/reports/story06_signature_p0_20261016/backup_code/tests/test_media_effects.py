from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image
import pytest

from ldporto_curator.media_effects import effect_input_fingerprints, extend_render_command


def _command(source="source.mp4",output="out.mp4",title=None):
    cmd=["ffmpeg","-y","-ss","0","-i",str(source)]
    filters="[0:v]scale=270:480[vout]"
    if title:
        cmd += ["-loop","1","-framerate","20","-i",str(title)]
        filters="[0:v]scale=270:480[base];[base][1:v]overlay=0:0:eof_action=pass[vout]"
    return cmd+["-t","1.6","-filter_complex",filters,"-map","[vout]","-map","0:a?",
                "-af","loudnorm=I=-14:TP=-1.5:LRA=11","-c:v","libx264","-preset","ultrafast",
                "-pix_fmt","yuv420p","-c:a","aac","-ar","48000","-shortest",str(output)]


def test_default_policy_preserves_original_audio_and_command_input_is_unchanged(tmp_path):
    command=_command(); original=deepcopy(command)
    modified=extend_render_command(command,{},270,480,1.6,tmp_path)
    assert command==original
    assert "-af" not in modified
    assert modified.count("-i")==1
    assert modified[modified.index("-map",modified.index("-map")+1)+1]=="0:a?"
    assert effect_input_fingerprints({})=={"audio_mode":"original","watermark":None}


def test_normalization_is_an_explicit_choice(tmp_path):
    modified=extend_render_command(_command(),{"audio":{"mode":"normalize"}},270,480,1.6,tmp_path)
    assert modified[modified.index("-af")+1]=="loudnorm=I=-14:TP=-1.5:LRA=11"


@pytest.mark.parametrize("audio", [
    {"mode":"stems"}, {"mode":"original","gain":.5}, {"mode":"original","volume":.2},
    {"mode":"original","ducking":True}, {"music_path":"absent.wav"}, "normalize",
])
def test_unimplemented_or_unbound_audio_controls_are_rejected(audio):
    with pytest.raises(ValueError):
        effect_input_fingerprints({"audio":audio})


@pytest.mark.parametrize("rights", [False,None,1,"true"])
def test_music_needs_exact_explicit_rights_confirmation(tmp_path,rights):
    path=tmp_path/"provided.wav"; path.write_bytes(b"provided fixture bytes")
    with pytest.raises(ValueError,match="direitos"):
        effect_input_fingerprints({"audio":{"music_path":str(path),"rights_confirmed":rights}})


def test_music_input_hash_tracks_actual_local_file_and_detects_changes(tmp_path):
    path=tmp_path/"provided.wav"; path.write_bytes(b"user-provided fixture bytes")
    episode={"audio":{"music_path":str(path),"rights_confirmed":True,"volume":.1,"ducking":False}}
    fingerprint=effect_input_fingerprints(episode)
    assert fingerprint["music"]["sha256"]==hashlib.sha256(path.read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(fingerprint)
    episode["audio"]["music_sha256"]=fingerprint["music"]["sha256"]
    path.write_bytes(b"changed music bytes")
    with pytest.raises(ValueError,match="SHA-256"):
        effect_input_fingerprints(episode)


@pytest.mark.parametrize("controls", [
    {"volume":float("nan")},{"volume":1.1},{"volume":-.1},{"ducking":"yes"},
])
def test_music_volume_and_ducking_are_validated(tmp_path,controls):
    path=tmp_path/"provided.wav"; path.write_bytes(b"fixture")
    with pytest.raises(ValueError):
        effect_input_fingerprints({"audio":{"music_path":str(path),"rights_confirmed":True,**controls}})


@pytest.mark.parametrize("watermark", [True,{"text":"marca","position":"center"},{"text":"marca","opacity":2},
                                        {"text":"marca","font_size_final":120},{"text":"marca","logo_url":"https://unused"}])
def test_watermark_rejects_unsupported_or_unsafe_controls(watermark):
    with pytest.raises(ValueError):
        effect_input_fingerprints({"watermark":watermark})


def test_watermark_uses_local_transparent_png_and_correct_title_input_index(tmp_path):
    episode={"watermark":{"text":"l.d.porto.oficial {\\N}","position":"bottom_right"}}
    result=extend_render_command(_command(title="title.png"),episode,270,480,1.6,tmp_path)
    assert result.count("-i")==3
    assert "[2:v]format=rgba[ldp_watermark]" in result[result.index("-filter_complex")+1]
    assert result[result.index("-map")+1]=="[ldp_effect_video]"
    with Image.open(tmp_path/"WATERMARK.png") as image:
        assert image.mode=="RGBA" and image.size==(270,480)
        assert image.getpixel((0,0))[3]==0


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,reason="FFmpeg local ausente")
@pytest.mark.parametrize("ducking", [False,True])
def test_real_ffmpeg_watermark_music_and_original_voice_are_retained(tmp_path,ducking):
    source=tmp_path/"source.mp4"; music=tmp_path/"music.wav"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","color=c=gray:s=270x480:r=20:d=1.6",
                    "-f","lavfi","-i","sine=frequency=440:duration=1.6","-c:v","libx264","-preset","ultrafast",
                    "-pix_fmt","yuv420p","-c:a","aac","-shortest",str(source)],check=True)
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=110:duration=0.4",
                    str(music)],check=True)
    original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    title=tmp_path/"title.png"; Image.new("RGBA",(270,480),(0,0,0,0)).save(title)
    output=tmp_path/"effects.mp4"
    episode={"watermark":"l.d.porto.oficial", "audio":{"mode":"original","music_path":str(music),
                                                        "rights_confirmed":True,"volume":.2,"ducking":ducking}}
    command=extend_render_command(_command(source,output,title),episode,270,480,1.6,tmp_path)
    command[1:1]=["-hide_banner","-loglevel","error"]
    command[-1:-1]=["-threads","2","-filter_complex_threads","2"]
    subprocess.run(command,check=True)
    probe=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(output)],
                                    check=True,capture_output=True,text=True).stdout)
    assert abs(float(probe["format"]["duration"])-1.6)<.12
    assert {row["codec_type"] for row in probe["streams"]}=={"video","audio"}
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original_hash
    pcm=subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-i",str(output),"-vn","-f","f32le","-ac","1","-ar","8000","pipe:1"],
                       check=True,capture_output=True).stdout
    samples=np.frombuffer(pcm,dtype="<f4")
    spectrum=np.abs(np.fft.rfft(samples))
    frequencies=np.fft.rfftfreq(len(samples),1/8000)
    assert spectrum[np.argmin(abs(frequencies-440))]>10, "original source voice/tone disappeared"
    assert spectrum[np.argmin(abs(frequencies-110))]>.5, "provided music did not mix or loop"
    frame=tmp_path/"effects_frame.png"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss","0.8","-i",str(output),"-frames:v","1",str(frame)],check=True)
    with Image.open(frame) as image:
        assert max(pixel[0] for pixel in image.convert("RGB").crop((20,370,230,395)).getdata())>180
