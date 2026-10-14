import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from ldporto_curator.subtitle_presets import (
    load_subtitle_preset, resolve_subtitle_preset, save_subtitle_preset,
    write_episode_subtitles,
)


def evidence():
    return {"segments": [{"segment_id": "s1", "start": 10, "end": 12, "text": "Olá, avião!", "speaker": "SPEAKER_00"}],
            "words": [{"word_id": "w1", "segment_id": "s1", "start": 10.2, "end": 10.7, "word": "Olá,"},
                      {"word_id": "w2", "segment_id": "s1", "start": 10.8, "end": 11.8, "word": "avião!"}]}


def test_word_events_preserve_real_gap_and_source_and_relative_timestamps(tmp_path):
    result = write_episode_subtitles(evidence(), {"episode_id": "H001", "source_start": 10, "source_end": 12}, tmp_path)
    sync = result["sync"]
    assert sync["alignment"] == "word"
    assert [(event["start"], event["end"], event["active_word_ids"]) for event in sync["events"]] == [
        (pytest.approx(.2), pytest.approx(.7), ["w1"]),
        (pytest.approx(.7), pytest.approx(.8), []),
        (pytest.approx(.8), pytest.approx(1.8), ["w2"])]
    ass = Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "0:00:00.70,0:00:00.80" in ass
    assert "\\k" not in ass
    assert "Olá," in ass and "avião!" in ass
    assert "Olá, avião!" in Path(result["srt"]).read_text(encoding="utf-8")


def test_clip_edges_clamp_word_events_without_fabricating_timestamps(tmp_path):
    result = write_episode_subtitles(evidence(), {"source_start": 10.4, "source_end": 11.2}, tmp_path)
    words = result["sync"]["segments"][0]["words"]
    assert all(word["clipped"] for word in words)
    assert words[0]["source_start"] == 10.2
    assert words[0]["start"] == 0
    assert words[1]["end"] == pytest.approx(.8)
    assert all(0 <= event["start"] < event["end"] <= .8+1e-9 for event in result["sync"]["events"])
    assert "00:00:00,000 --> 00:00:00,800" in Path(result["srt"]).read_text()


def test_words_outside_cut_do_not_appear_in_rendered_caption(tmp_path):
    result=write_episode_subtitles(evidence(),{"source_start":10.8,"source_end":11.8},tmp_path)
    assert "Olá," not in Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "Olá," not in Path(result["srt"]).read_text(encoding="utf-8")
    assert result["sync"]["segments"][0]["literal_text"] == "Olá, avião!"
    assert result["sync"]["segments"][0]["clip_literal_text"] == "avião!"


@pytest.mark.parametrize("mutate,reason", [
    (lambda data: data["words"].pop(), "incomplete_word_alignment"),
    (lambda data: data["words"][0].update(start=-.1), "invalid_word_timestamps"),
    (lambda data: data["words"][0].update(start=float("nan")), "invalid_word_timestamps"),
    (lambda data: data["words"][0].update(word="inventado"), "word_text_mismatch"),
])
def test_insufficient_alignment_falls_back_explicitly_to_literal_segment(tmp_path,mutate,reason):
    data=evidence()
    mutate(data)
    result=write_episode_subtitles(data,{"source_start":10,"source_end":12},tmp_path)
    assert result["sync"]["alignment"] == "segment"
    assert result["sync"]["diagnostics"][0]["code"] == reason
    assert result["sync"]["events"][0]["literal_text"] == "Olá, avião!"
    assert result["sync"]["events"][0]["active_word_ids"] == []


def test_overlapping_word_intervals_remain_explicit(tmp_path):
    data=evidence()
    data["words"][1]["start"]=10.6
    result=write_episode_subtitles(data,{"source_start":10,"source_end":12},tmp_path)
    assert any(event["active_word_ids"] == ["w1","w2"] for event in result["sync"]["events"])


def test_literal_ass_characters_and_uppercase_remain_separate_from_transcript(tmp_path):
    literal="Preço, {teste} \\ caminho: atenção!"
    data={"segments":[{"start":0,"end":2,"text":literal}]}
    result=write_episode_subtitles(data,{"source_start":0,"source_end":2},tmp_path,overrides={"uppercase":True})
    assert literal in Path(result["srt"]).read_text(encoding="utf-8")
    ass=Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "\\{TESTE\\}" in ass and "\\\\" in ass
    assert result["sync"]["segments"][0]["literal_text"] == literal
    assert result["sync"]["visual_case_transform"] == "uppercase"


def test_srt_retains_literal_display_text_is_not_used_as_source(tmp_path):
    data={"segments":[{"start":0,"end":1,"text":"é... avião","display_text":"É avião."}]}
    result=write_episode_subtitles(data,{"source_start":0,"source_end":1},tmp_path)
    assert "é... avião" in Path(result["srt"]).read_text(encoding="utf-8")
    assert "É avião." not in Path(result["srt"]).read_text(encoding="utf-8")


def test_presets_are_independent_and_custom_models_round_trip(tmp_path):
    one=resolve_subtitle_preset("LDP_KARAOKE_VERDE",{"safe_zone":{"left":.1},"color":"#FFAA00"})
    assert resolve_subtitle_preset()["safe_zone"]["left"] == .08
    saved=save_subtitle_preset(tmp_path/"meu_modelo.json",one)
    assert load_subtitle_preset(saved) == one


@pytest.mark.parametrize("overrides", [
    {"position_y":.95}, {"color":"red"}, {"font":"Bad,Font"}, {"font":"x\nStyle: injected"},
    {"safe_zone":{"right":float("inf")}}, {"max_words":0}, {"animation":"bounce"}, {"uppercase":"false"},
])
def test_unsafe_preset_controls_rejected(overrides):
    with pytest.raises(ValueError):
        resolve_subtitle_preset(overrides=overrides)


def test_no_subtitles_is_explicit_choice_with_transcript_still_exported(tmp_path):
    result=write_episode_subtitles(evidence(),{"source_start":10,"source_end":12},tmp_path,preset="SEM_LEGENDA")
    assert result["sync"]["enabled"] is False
    assert "Dialogue:" not in Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "Olá, avião!" in Path(result["srt"]).read_text(encoding="utf-8")


def test_ass_centisecond_rounding_handles_minute_rollover(tmp_path):
    data={"segments":[{"start":59.999,"end":61.1,"text":"Texto"}]}
    result=write_episode_subtitles(data,{"source_start":0,"source_end":62},tmp_path)
    ass=Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "0:01:00.00,0:01:01.10" in ass
    assert "0:00:60.00" not in ass


def test_segment_json_metadata_can_be_read_by_other_process(tmp_path):
    result=write_episode_subtitles(evidence(),{"source_start":10,"source_end":12},tmp_path)
    exported=json.loads(Path(result["sync_metadata"]).read_text(encoding="utf-8"))
    assert exported==result["sync"]


@pytest.mark.parametrize("start,end", [(0,0),(-1,2),(1,float("inf")),(float("nan"),2)])
def test_invalid_episode_times_rejected(tmp_path,start,end):
    with pytest.raises(ValueError):
        write_episode_subtitles(evidence(),{"source_start":start,"source_end":end},tmp_path)


@pytest.mark.skipif(shutil.which("ffmpeg") is None,reason="FFmpeg local ausente")
def test_actual_libass_highlight_stops_during_word_gap(tmp_path):
    from ldporto_curator.render import _ass_filter_path
    data=evidence()
    data["segments"][0].update(start=0,end=2)
    for word in data["words"]:
        word["start"]-=10
        word["end"]-=10
    result=write_episode_subtitles(data,{"source_start":0,"source_end":2},tmp_path/"captions",overrides={"highlight_color":"#00FF00"})
    video=tmp_path/"caption_render.mp4"
    subtitle_filter="subtitles='"+_ass_filter_path(Path(result["ass"]))+"'"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",
                    "color=c=gray:s=540x960:r=20:d=2","-vf",subtitle_filter,"-c:v","libx264","-preset","ultrafast",
                    "-pix_fmt","yuv420p",str(video)],check=True)
    green_counts=[]
    for index,time in enumerate((.3,.75,.9)):
        frame=tmp_path/f"decoded_{index}.png"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",str(time),"-i",str(video),
                        "-frames:v","1",str(frame)],check=True)
        with Image.open(frame) as image:
            green_counts.append(sum(1 for r,g,b in image.convert("RGB").getdata() if g>120 and r<90 and b<90))
    assert green_counts[0]>30
    assert green_counts[1]==0
    assert green_counts[2]>30
