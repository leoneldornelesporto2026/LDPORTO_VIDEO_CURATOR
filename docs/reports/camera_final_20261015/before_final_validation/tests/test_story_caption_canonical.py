"""Production regression: the immutable VARIG Story and adverse word evidence."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from ldporto_curator.subtitle_presets import canonical_timeline_hash, write_episode_subtitles


FIXTURE = Path(__file__).parent / "fixture" / "story_prop_f654d728d26180f2fb0e5816.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def emit(data, directory, **kwargs):
    return write_episode_subtitles(data["evidence"], data["episode"], directory, preset="LDP_CLEAN", **kwargs)


def parse_srt(path):
    rows = Path(path).read_text(encoding="utf-8").strip().split("\n\n")
    def seconds(value):
        h,m,s = value.replace(",", ".").split(":")
        return int(h)*3600+int(m)*60+float(s)
    return [(seconds(row.splitlines()[1].split(" --> ")[0]),seconds(row.splitlines()[1].split(" --> ")[1]),
             "\n".join(row.splitlines()[2:])) for row in rows if row.strip()]


def parse_ass(path):
    result=[]
    for row in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not row.startswith("Dialogue:"):
            continue
        fields=row.split(",",9)
        def seconds(value):
            h,m,s=value.split(":")
            return int(h)*3600+int(m)*60+float(s)
        result.append((seconds(fields[1]),seconds(fields[2]),re.sub(r"\{[^}]*\}","",fields[9]).replace(r"\N","\n")))
    return result


def test_real_story_all_71_words_once_no_future_text_and_equivalent_ass_srt(tmp_path):
    data=fixture();before=deepcopy(data)
    result=emit(data,tmp_path);sync=result["sync"]
    events=sync["events"]
    assert data==before
    assert len(events)==71 and len(sync["segments"])==5
    assert [wid for event in events for wid in event["word_ids"]]==data["episode"]["word_ids"]
    assert len(set(wid for event in events for wid in event["word_ids"]))==71
    assert sync["no_word_anticipation"] and sync["renderable"]
    assert sync["audio_review_status"]=="NEEDS_HUMAN_AUDIO_REVIEW"
    assert not sync["audiovisual_sync_homologated"]
    for event in events:
        assert len(event["word_ids"])==1 and event["method"]=="word"
        word=event["words"][0]
        assert event["literal_text"]==word["text"]
        assert event["source_start"]==word["source_start"] and event["source_end"]==word["source_end"]
        assert event["start"]==word["source_start"]-data["episode"]["source_start"]
        assert event["end"]==word["source_end"]-data["episode"]["source_start"]
        assert 0<=event["start"]<event["end"]<=26.22
        assert len(event["layout"]["visual_lines"])<=2 and event["layout"]["fits_safe_box"]
        assert event["layout"]["font_size_final"]==60
        assert event["active_word_ids"]==[] and event["ass_event_written"]
        assert event["review_status"]=="NEEDS_HUMAN_AUDIO_REVIEW"
    assert len({(event["layout"]["x"],event["layout"]["y"]) for event in events})==1
    ass,srt=parse_ass(result["ass"]),parse_srt(result["srt"])
    assert len(ass)==len(srt)==71
    for expected,actual_ass,actual_srt in zip(events,ass,srt):
        assert actual_ass[2]==actual_srt[2]==expected["literal_text"]
        assert actual_ass[:2]==pytest.approx(actual_srt[:2],abs=.0051)
        assert actual_ass[:2]==pytest.approx((expected["start"],expected["end"]),abs=.0051)
    for segment in sync["segments"]:
        segment_events=[event for event in events if event["segment_id"]==segment["segment_id"]]
        assert "".join(event["literal_prefix"]+event["literal_text"]+event["literal_suffix"] for event in segment_events)==segment["literal_text"]


def test_highlight_does_not_change_grouping_and_frozen_final_never_regroups(tmp_path,monkeypatch):
    data=fixture();preview=emit(data,tmp_path/"preview")
    highlighted=emit(data,tmp_path/"highlight",overrides={"word_highlight":True})
    assert preview["sync"]["canonical_timeline_sha256"]==highlighted["sync"]["canonical_timeline_sha256"]
    assert parse_srt(preview["srt"])==parse_srt(highlighted["srt"])
    def forbidden(*args,**kwargs):
        raise AssertionError("Frozen final must not call timeline grouping")
    monkeypatch.setattr("ldporto_curator.subtitle_presets._canonical_events",forbidden)
    final=emit(data,tmp_path/"final",width=1080,height=1920,canonical_timeline=preview["sync"])
    assert final["sync"]["frozen_timeline_reused"]
    assert final["sync"]["canonical_timeline_sha256"]==preview["sync"]["canonical_timeline_sha256"]
    assert parse_srt(preview["srt"])==parse_srt(final["srt"])
    for small,large in zip(preview["sync"]["events"],final["sync"]["events"]):
        assert large["layout"]["font_size"]==2*small["layout"]["font_size"]
        assert large["layout"]["ass_font_size"]==2*small["layout"]["ass_font_size"]
        assert large["layout"]["bounds"]==pytest.approx({key:2*value for key,value in small["layout"]["bounds"].items()})


@pytest.mark.parametrize("change",["delete","duplicate","text","timing","span","source"])
def test_frozen_timeline_rejects_changed_evidence_even_with_recomputed_hash(tmp_path,change):
    data=fixture();frozen=emit(data,tmp_path/"initial")["sync"]
    if change=="delete":
        frozen["events"].pop()
    elif change=="duplicate":
        frozen["events"].append(deepcopy(frozen["events"][-1]))
    elif change=="text":
        frozen["events"][0]["literal_text"]="invented"
    elif change=="timing":
        event=frozen["events"][0];event["source_end"]-=.01;event["end"]-=.01
    elif change=="span":
        frozen["events"][0]["words"][0]["source_end"]-=.01
    else:
        data["evidence"]["segments"][0]["words"][0]["end"]-=.01
    frozen["canonical_timeline_sha256"]=canonical_timeline_hash(frozen["events"])
    with pytest.raises(ValueError,match="[Ff]rozen|Duplicate"):
        emit(data,tmp_path/"changed",canonical_timeline=frozen)


def synthetic(words,starts=None,ends=None,text=None):
    starts=starts or [i*.4 for i in range(len(words))]
    ends=ends or [a+.3 for a in starts]
    literal=text if text is not None else " ".join(words)
    return {"episode":{"source_start":0,"source_end":max(ends,default=1)},
        "evidence":{"segments":[{"segment_id":"S","start":0,"end":max(ends,default=1),"text":literal,
            "words":[{"word_id":f"W{i}","word":word,"start":a,"end":b} for i,(word,a,b) in enumerate(zip(words,starts,ends))]}]}}


def test_literal_whitespace_unicode_names_and_real_pause_survive(tmp_path):
    data=synthetic(["Cesar","Garces,","Lockheed","Electra."],starts=[0,.5,2,2.3],ends=[.4,.9,2.2,3],
                   text="  Cesar  Garces,\tLockheed\nElectra. ")
    sync=emit(data,tmp_path)["sync"]
    assert [e["literal_text"] for e in sync["events"]]==["Cesar","Garces,","Lockheed","Electra."]
    assert "".join(e["literal_prefix"]+e["literal_text"]+e["literal_suffix"] for e in sync["events"])==data["evidence"]["segments"][0]["text"]
    assert sync["events"][1]["end"]==.9 and sync["events"][2]["start"]==2


def test_opt_in_blocks_obey_two_lines_count_duration_and_real_pause(tmp_path):
    data=fixture();result=emit(data,tmp_path,overrides={"reveal_mode":"block","word_highlight":True})
    events=result["sync"]["events"]
    assert 5<len(events)<71 and result["sync"]["renderable"]
    assert not result["sync"]["no_word_anticipation"]
    assert [wid for event in events for wid in event["word_ids"]]==data["episode"]["word_ids"]
    assert all(len(event["word_ids"])<=5 and len(event["layout"]["visual_lines"])<=2 for event in events)
    assert all(event["end"]-event["start"]<=2.2+1e-7 or len(event["word_ids"])==1 for event in events)
    assert len(parse_ass(result["ass"]))==len(parse_srt(result["srt"]))==len(events)
    assert r"\t(" in Path(result["ass"]).read_text(encoding="utf-8-sig")


def test_fast_word_below_ass_precision_is_preserved_and_blocks_unsafe_preview(tmp_path):
    data=synthetic(["fast"],starts=[.001],ends=[.002])
    result=emit(data,tmp_path);sync=result["sync"]
    assert sync["events"][0]["word_ids"]==["W0"]
    assert sync["events"][0]["start"]==.001 and sync["events"][0]["end"]==.002
    assert not sync["renderable"] and sync["needs_human_review"]
    assert any(row["code"]=="caption_below_format_time_resolution" for row in sync["diagnostics"])
    assert "fast" in Path(result["srt"]).read_text(encoding="utf-8")


def test_mid_word_cut_and_60_second_edge_keep_original_evidence_and_pending_review(tmp_path):
    data=synthetic(["inside","edge"],starts=[59,59.8],ends=[59.5,60.3])
    data["episode"]={"source_start":59.2,"source_end":60}
    sync=emit(data,tmp_path)["sync"]
    assert [event["word_ids"] for event in sync["events"]]==[["W0"],["W1"]]
    assert sync["events"][0]["source_start"]==59 and sync["events"][0]["start"]==0
    assert sync["events"][-1]["source_end"]==60.3 and sync["events"][-1]["end"]==pytest.approx(.8)
    assert sync["needs_human_review"]


def test_empty_interval_and_cross_segment_overlap_are_explicit_and_not_renderable(tmp_path):
    empty={"episode":{"source_start":0,"source_end":1},"evidence":{"segments":[]}}
    result=emit(empty,tmp_path/"empty");assert not result["sync"]["renderable"] and not result["sync"]["no_word_anticipation"]
    data=synthetic(["first"],starts=[0],ends=[1])
    data["evidence"]["segments"].append({"segment_id":"S2","start":.5,"end":1,"text":"second",
        "words":[{"word_id":"W1","word":"second","start":.5,"end":1}]})
    result=emit(data,tmp_path/"overlap")
    assert not result["sync"]["renderable"] and result["sync"]["needs_human_review"]
    assert "Dialogue:" not in Path(result["ass"]).read_text(encoding="utf-8-sig")


def test_indivisible_long_word_never_shrinks_or_exceeds_safe_box(tmp_path):
    data=synthetic(["W"*100]);result=emit(data,tmp_path)
    event=result["sync"]["events"][0]
    assert event["layout"]["font_size_final"]==60
    assert event["literal_text"]=="W"*100 and event["word_ids"]==["W0"]
    assert not event["ass_event_written"] and not result["sync"]["renderable"]


@pytest.mark.parametrize("duplicate",[False,True])
def test_frozen_unaligned_segment_without_ids_cannot_disappear_or_repeat(tmp_path,duplicate):
    data={"episode":{"source_start":0,"source_end":1},
          "evidence":{"segments":[{"segment_id":"S","start":0,"end":1,"text":"literal"}]}}
    frozen=emit(data,tmp_path/"initial")["sync"]
    if duplicate:
        frozen["events"].append(deepcopy(frozen["events"][0]))
    else:
        frozen["events"].clear()
    frozen["canonical_timeline_sha256"]=canonical_timeline_hash(frozen["events"])
    with pytest.raises(ValueError,match="[Ff]rozen"):
        emit(data,tmp_path/"invalid",canonical_timeline=frozen)


def test_duplicate_source_segment_ids_are_rejected(tmp_path):
    data=synthetic(["literal"])
    data["evidence"]["segments"].append(deepcopy(data["evidence"]["segments"][0]))
    with pytest.raises(ValueError,match="Duplicate source segment"):
        emit(data,tmp_path)


FRAGMENT_FIXTURE = Path(__file__).parent / "fixture" / "story_caption_fragment_records.json"


@pytest.mark.parametrize("segment_id,fragment",[
    ("SEG_00316",".500"),("SEG_00333",".112"),("SEG_00352","-feira,")])
def test_real_contiguous_asr_fragments_keep_every_measured_id_and_literal(tmp_path,segment_id,fragment):
    raw=json.loads(FRAGMENT_FIXTURE.read_text(encoding="utf-8"))
    segment=next(segment for segment in raw["segments"] if segment["segment_id"]==segment_id)
    words=[word for word in raw["words"] if word["segment_id"]==segment_id]
    before=deepcopy((segment,words))
    data={"episode":{"source_start":segment["start"],"source_end":segment["end"]},
          "evidence":{"segments":[segment],"words":words}}
    result=emit(data,tmp_path/"preview");sync=result["sync"]
    assert (segment,words)==before
    assert sync["alignment"]=="word" and sync["renderable"] and sync["no_word_anticipation"]
    assert len(sync["events"])==len(words)
    assert [event["word_ids"][0] for event in sync["events"]]==[word["word_id"] for word in words]
    assert "".join(event["literal_prefix"]+event["literal_text"]+event["literal_suffix"] for event in sync["events"])==segment["text"]
    event=next(event for event in sync["events"] if event["literal_text"]==fragment)
    original=next(word for word in words if word["word_id"]==event["word_ids"][0])
    assert event["literal_prefix"]==""
    assert event["source_start"]==original["start"] and event["source_end"]==original["end"]
    assert event["start"]==original["start"]-segment["start"]
    assert event["end"]==original["end"]-segment["start"]
    assert len(parse_ass(result["ass"]))==len(parse_srt(result["srt"]))==len(words)
    final=emit(data,tmp_path/"final",width=1080,height=1920,canonical_timeline=sync)
    assert final["sync"]["canonical_timeline_sha256"]==sync["canonical_timeline_sha256"]


def test_real_segment_without_word_records_stays_review_fallback(tmp_path):
    raw=json.loads(FRAGMENT_FIXTURE.read_text(encoding="utf-8"))
    segment=next(segment for segment in raw["segments"] if segment["segment_id"]=="SEG_00163")
    assert not any(word["segment_id"]==segment["segment_id"] for word in raw["words"])
    data={"episode":{"source_start":segment["start"],"source_end":segment["end"]},
          "evidence":{"segments":[segment],"words":raw["words"]}}
    sync=emit(data,tmp_path)["sync"]
    assert sync["alignment"]=="segment" and sync["needs_human_review"]
    assert sync["events"][0]["fallback_reason"]=="missing_word_timestamps"
    assert sync["events"][0]["literal_text"]==segment["text"]
    assert sync["events"][0]["word_ids"]==[] and sync["events"][0]["words"]==[]
    assert not sync["no_word_anticipation"]


def test_fragment_fixture_selected_jsonl_records_match_unmodified_source_values():
    fixture=json.loads(FRAGMENT_FIXTURE.read_text(encoding="utf-8"))
    for kind in ("segments","words"):
        path=FRAGMENT_FIXTURE.with_name(f"story_caption_fragment_{kind}.jsonl")
        assert [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]==fixture[kind]


@pytest.mark.parametrize("literal,words",[("8.500",["8",".500"]),("1.112",["1",".112"]),
    ("ter\u00e7a-feira,",["ter\u00e7a","-feira,"])])
def test_inline_fragments_are_separate_events_with_no_future_characters(tmp_path,literal,words):
    data=synthetic(words,text=literal)
    sync=emit(data,tmp_path)["sync"]
    assert [event["literal_text"] for event in sync["events"]]==words
    assert all(event["literal_prefix"]=="" for event in sync["events"])
    assert all(len(event["word_ids"])==1 for event in sync["events"])
    assert sync["events"][0]["end"]==.3 and sync["events"][1]["start"]==.4


def test_lexical_concat_cannot_move_record_across_literal_whitespace(tmp_path):
    data=synthetic(["a","bc"],text="ab c")
    sync=emit(data,tmp_path)["sync"]
    assert sync["alignment"]=="segment" and sync["needs_human_review"]
    assert sync["events"][0]["fallback_reason"]=="word_text_mismatch"
