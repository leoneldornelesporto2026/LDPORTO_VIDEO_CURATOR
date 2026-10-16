"""Stories reuse the Reels serializer with real, independently timed onsets."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from ldporto_curator.subtitle_presets import resolve_subtitle_preset, write_episode_subtitles
from ldporto_curator.subtitles import _karaoke_chunk, measured_karaoke_body


def evidence(text="One two three four", starts=(.205,.607,.909,1.311), ends=(.4,.8,1.1,1.5)):
    words=text.split()
    return {"segments":[{"segment_id":"S","start":0,"end":2,"text":text,
        "words":[{"word_id":f"W{i}","word":word,"start":a,"end":b}
                 for i,(word,a,b) in enumerate(zip(words,starts,ends))]}]}


def emit(tmp_path,data=None,**kwargs):
    return write_episode_subtitles(data or evidence(),{"source_start":0,"source_end":2},tmp_path,
        preset="LDP_REELS_KARAOKE",**kwargs)


def test_whole_phrase_one_fixed_dialogue_absolute_onsets_and_permanent_white(tmp_path):
    data=evidence();before=deepcopy(data)
    result=emit(tmp_path,data)
    ass=Path(result["ass"]).read_text(encoding="utf-8-sig")
    events=result["sync"]["events"]
    assert data==before and len(events)==1 and events[0]["literal_text"]=="One two three four"
    assert ass.count("Dialogue:")==1 and r"\k" not in ass and r"\fad" not in ass
    assert r"\1c&H00D7FF&" in ass
    # Serialized ASS begins .20; the first measured onset is .205, so it also
    # waits before whitening. Real pauses are not replaced with word durations.
    assert re.findall(r"\\t\((\d+),(\d+),\\1c&HFFFFFF&\)",ass)==[
        ("5","5"),("407","407"),("709","709"),("1111","1111")]
    assert [item["ass_offset_ms"] for item in events[0]["color_transitions"]]==[5,407,709,1111]
    assert all(item["persists_until_block_end"] for item in events[0]["color_transitions"])
    assert result["sync"]["no_color_anticipation"] and not result["sync"]["no_word_anticipation"]
    assert [word["source_start"] for word in events[0]["words"]]==list((.205,.607,.909,1.311))
    assert "One two three four" in Path(result["srt"]).read_text(encoding="utf-8")


def test_submillisecond_onsets_round_up_and_zero_transform_is_never_emitted():
    words=[{"char_start":0,"char_end":3,"source_start":.2},
           {"char_start":4,"char_end":7,"source_start":.600001}]
    body=measured_karaoke_body("one two",words,.2)
    assert r"\t(0,0," not in body
    assert r"{\1c&HFFFFFF&}one" in body
    assert r"\t(401,401,\1c&HFFFFFF&)" in body


def test_reels_and_stories_share_exact_same_serialization():
    words=[{"start":5.2,"end":5.5},{"start":5.9,"end":6.2},{"start":6.3,"end":6.6}]
    spans=[dict(word,char_start=a,char_end=b) for word,a,b in zip(words,(0,4,8),(3,7,13))]
    expected=measured_karaoke_body("One two three",spans,5.2,break_offsets=[8])
    assert _karaoke_chunk(["One","two","three"],words,2,5.2,6.6)==expected


def test_new_profile_exact_accepted_reels_style_and_proportional_font(tmp_path):
    preview=emit(tmp_path/"preview")
    final=emit(tmp_path/"final",width=1080,height=1920,canonical_timeline=preview["sync"])
    ass=Path(final["ass"]).read_text(encoding="utf-8-sig")
    assert "Style: Sub,Segoe UI,60.00,&H00FFFFFF,&H0000D7FF,&H00101010,&H60000000,-1,0,0,0,100,100,0,0,1,6.00,2.00,2,130,130,320,1" in ass
    assert r"\pos(540.00,1600.00)\fs60.00" in ass
    small,large=preview["sync"]["events"][0],final["sync"]["events"][0]
    assert small["layout"]["ass_font_size"]==30 and large["layout"]["ass_font_size"]==60
    assert preview["sync"]["canonical_timeline_sha256"]==final["sync"]["canonical_timeline_sha256"]
    assert large["layout"]["fits_safe_box"] and len(large["layout"]["visual_lines"])<=2


def test_real_part_one_groups_three_to_six_without_losing_ids_or_literal(tmp_path):
    path=Path(__file__).parent/"fixture"/"story_prop_f654d728d26180f2fb0e5816.json"
    data=json.loads(path.read_text(encoding="utf-8"));before=deepcopy(data)
    result=write_episode_subtitles(data["evidence"],data["episode"],tmp_path,preset="LDP_REELS_KARAOKE")
    events=result["sync"]["events"]
    assert data==before and len(events)==15 and result["sync"]["renderable"]
    assert all(3<=len(event["literal_text"].split())<=6 for event in events)
    assert [wid for event in events for wid in event["word_ids"]]==data["episode"]["word_ids"]
    assert all(len(event["layout"]["visual_lines"])<=2 for event in events)
    assert all(event["layout"]["x"]==270 and event["layout"]["y"]==800 for event in events)


def test_measured_fragments_keep_one_complete_lexical_word_and_separate_color_steps(tmp_path):
    data=evidence("8.500",starts=(0,),ends=(1,))
    data["segments"][0]["words"]=[{"word_id":"W0","word":"8","start":0,"end":.1},
        {"word_id":"W1","word":".500","start":.6,"end":1}]
    result=emit(tmp_path,data)
    assert [event["literal_text"] for event in result["sync"]["events"]]==["8.500"]
    event=result["sync"]["events"][0]
    assert event["word_ids"]==["W0","W1"] and len(event["color_transitions"])==2
    assert event["color_transitions"][1]["ass_offset_ms"]==600


def test_historical_frozen_word_mode_remains_readable_without_new_profile_fields(tmp_path):
    old=write_episode_subtitles(evidence(),{"source_start":0,"source_end":2},tmp_path/"old",preset="LDP_CLEAN")
    frozen=deepcopy(old["sync"])
    frozen["engine_version"]="5.2.2"
    for key in ("color_progression","font_size_metric","shadow_opacity"):
        frozen["preset"].pop(key)
    result=write_episode_subtitles(evidence(),{"source_start":0,"source_end":2},tmp_path/"reused",
        preset="LDP_CLEAN",canonical_timeline=frozen)
    assert result["sync"]["frozen_timeline_reused"]
    assert result["sync"]["canonical_timeline_sha256"]==frozen["canonical_timeline_sha256"]
    assert len(result["sync"]["events"])==4


def test_cumulative_profile_without_measured_words_blocks_visual_preview(tmp_path):
    data=evidence();data["segments"][0].pop("words")
    result=emit(tmp_path,data)
    assert not result["sync"]["renderable"] and not result["sync"]["no_color_anticipation"]
    assert "Dialogue:" not in Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "One two three four" in Path(result["srt"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("overrides",[{"reveal_mode":"word"},{"word_highlight":False},{"color_progression":"guess"}])
def test_contradictory_cumulative_profiles_are_rejected(overrides):
    with pytest.raises(ValueError):
        resolve_subtitle_preset("LDP_REELS_KARAOKE",overrides)
