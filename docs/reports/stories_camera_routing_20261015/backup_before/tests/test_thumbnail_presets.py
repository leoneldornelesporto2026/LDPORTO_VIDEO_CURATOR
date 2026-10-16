import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from ldporto_curator.thumbnail_presets import generate_thumbnail_choices


def _fake_extract(video,time,out):
    out.parent.mkdir(parents=True,exist_ok=True)
    frame=Image.new("RGB",(960,540),"#4876A8")
    frame.putpixel((0,0),(240,0,0))
    frame.save(out)
    return out


def _episode():
    return {"episode_id":"HISTORIA_001","series_id":"SERIE_TESTE","order":1,"source_start":0,"source_end":2,
            "original_excerpt_support":"O avião aparece no mapa.","segment_ids":["s1"]}


def test_three_editable_real_frame_designs_safe_dimensions_and_hashes(tmp_path,monkeypatch):
    monkeypatch.setattr("ldporto_curator.thumbnail_presets.extract_frame",_fake_extract)
    source=tmp_path/"source.mp4"
    source.write_bytes(b"controlled media fixture")
    result=generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs")
    assert len(result["choices"])==3
    assert {choice["layout"] for choice in result["choices"]} == {"IMPACTO","DOCUMENTAL","MINIMALISTA"}
    for choice in result["choices"]:
        path=tmp_path/"thumbs"/choice["file"]
        with Image.open(path) as image:
            assert image.size == (1080,1920)
        assert choice["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert 0<=choice["source_timestamp"]<2
        assert choice["original_dimensions"]==[960,540]
        assert choice["frame_composition"]=="full_source_preserve"
        assert choice["state"]=="thumbnail_candidate"
        assert choice["cover_title"]["human_approved"] is False
        assert choice["cover_title"]["literal_excerpt_match"] is True
        for left,top,right,bottom in choice["title_metrics"]["text_boxes"]:
            assert 1080*.08-1<=left<right<=1080*.84+1
            assert 1920*.12<=top<bottom<=1920*.82
        assert (tmp_path/"thumbs"/choice["editable_file"]).is_file()
    assert result["choices"][0]["sha256"] != result["choices"][1]["sha256"]
    manifest=json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_sha256"]==hashlib.sha256(source.read_bytes()).hexdigest()
    assert str(tmp_path) not in Path(result["manifest"]).read_text(encoding="utf-8")


def test_title_edit_does_not_become_a_verified_fact(tmp_path,monkeypatch):
    monkeypatch.setattr("ldporto_curator.thumbnail_presets.extract_frame",_fake_extract)
    source=tmp_path/"source.mp4"; source.write_bytes(b"source")
    result=generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs",titles=["Hipótese editorial para revisar"])
    assert all(choice["cover_title"]["status"]=="FACT_CHECK_REQUIRED" for choice in result["choices"])
    assert all(choice["cover_title"]["literal_excerpt_match"] is False for choice in result["choices"])


@pytest.mark.parametrize("times", [[-.1,.5,1],[0,1,2],[float("nan"),.5,1],[.5]])
def test_frame_selection_rejects_invalid_or_outside_source_interval(tmp_path,times):
    source=tmp_path/"source.mp4"; source.write_bytes(b"source")
    with pytest.raises(ValueError):
        generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs",overrides={"frame_times":times})


def test_source_media_hash_must_match_before_extraction(tmp_path):
    source=tmp_path/"source.mp4"; source.write_bytes(b"source")
    with pytest.raises(ValueError,match="SHA-256"):
        generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs",source_sha256="0"*64)


def test_layout_cannot_move_titles_over_source_pixels(tmp_path,monkeypatch):
    monkeypatch.setattr("ldporto_curator.thumbnail_presets.extract_frame",_fake_extract)
    source=tmp_path/"source.mp4"; source.write_bytes(b"source")
    with pytest.raises(ValueError):
        generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs",overrides={"layout_overrides":{"IMPACTO":{"title_y":.5}}})


@pytest.mark.skipif(shutil.which("ffmpeg") is None,reason="FFmpeg local ausente")
def test_real_ffmpeg_frames_become_three_vertical_covers(tmp_path):
    source=tmp_path/"synthetic_fixture.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",
                    "testsrc2=s=640x360:r=8:d=2","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",str(source)],check=True)
    result=generate_thumbnail_choices(source,_episode(),tmp_path/"thumbs",titles=["O avião aparece no mapa."])
    assert len(result["choices"])==3
    assert all((tmp_path/"thumbs"/choice["frame_file"]).is_file() for choice in result["choices"])
    assert all(choice["frame_sha256"] != choice["sha256"] for choice in result["choices"])


def test_five_distinct_real_source_frames_opt_in(tmp_path,monkeypatch):
    monkeypatch.setattr('ldporto_curator.thumbnail_presets.extract_frame',_fake_extract)
    video=tmp_path/'source.mp4';video.write_bytes(b'controlled source')
    result=generate_thumbnail_choices(video,_episode(),tmp_path/'five',titles=['O avião aparece no mapa.'],overrides={'frame_count':5})
    assert len(result['choices'])==5
    assert len({choice['source_timestamp'] for choice in result['choices']})==5
    for choice in result['choices']:
        assert (tmp_path/'five'/choice['file']).is_file()
        assert (tmp_path/'five'/choice['frame_file']).is_file()
        assert choice['cover_title']['human_approved'] is False
