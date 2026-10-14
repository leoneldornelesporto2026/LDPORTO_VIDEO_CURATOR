from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image
import pytest

from ldporto_curator.subtitle_presets import write_episode_subtitles


LITERAL = ("Esta é uma demonstração sintética local do Curator. "
           "O primeiro episódio explica um painel com três caixas numeradas, "
           "que representam a ordem dos episódios e preservam todo contexto.")


def long_evidence(literal=LITERAL):
    return {"source": {"width": 1920, "height": 1080},
            "segments": [{"segment_id": "S1", "start": 2.125, "end": 12.375, "text": literal}], "words": []}


def episode(padding=True):
    return {"episode_id": "H001", "source_start": 2.125, "source_end": 12.375,
            "camera_plan": {"mode": "full_frame_blur"} if padding else {"mode": "manual_crop"}}


def test_long_fallback_is_one_measured_event_readable_and_inside_source_padding(tmp_path):
    result = write_episode_subtitles(long_evidence(), episode(), tmp_path)
    sync = result["sync"]
    assert sync["alignment"] == "segment" and len(sync["events"]) == 1
    event = sync["events"][0]
    assert (event["source_start"], event["source_end"]) == (2.125, 12.375)
    assert (event["start"], event["end"]) == (0, 10.25)
    assert event["literal_text"] == LITERAL and event["active_word_ids"] == []
    layout = event["layout"]
    assert layout["font_size"] >= 20 and layout["font_size_final"] >= 40
    assert len(layout["visual_lines"]) > 2
    assert "".join(layout["visual_lines"]) == LITERAL
    assert layout["mode"] == "lower_caption_block"
    assert layout["padding_evidence"] == "full_frame_blur_source_dimensions"
    assert layout["bounds"]["top"] > layout["source_foreground_end"]
    assert layout["fits_safe_box"] and not sync["needs_human_review"]
    assert layout["bounds"]["left"] >= layout["safe_bounds"]["left"]
    assert layout["bounds"]["right"] <= layout["safe_bounds"]["right"]
    assert layout["bounds"]["bottom"] <= layout["safe_bounds"]["bottom"]
    ass = Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert ass.count("Dialogue:") == 1 and "\\N" in ass
    assert "CaptionBlock" in ass and "\\q2" in ass
    assert LITERAL in Path(result["srt"]).read_text(encoding="utf-8")
    assert sync["font_resolution"]["measurement"].startswith("Pillow")


def test_low_requested_font_is_raised_to_readable_minimum_with_diagnostic(tmp_path):
    result = write_episode_subtitles(long_evidence("Texto literal curto."), episode(), tmp_path,
        overrides={"font_size_final": 20})
    layout = result["sync"]["events"][0]["layout"]
    assert layout["font_size"] == 20
    assert layout["readable_minimum_applied"]
    assert any(row["code"] == "readable_font_minimum_applied" for row in result["sync"]["diagnostics"])


def test_font_lower_bound_scales_for_final_1080_resolution(tmp_path):
    result = write_episode_subtitles(long_evidence(), episode(), tmp_path, width=1080, height=1920)
    layout = result["sync"]["events"][0]["layout"]
    assert layout["font_size"] >= 40 and layout["fits_safe_box"]
    assert "".join(layout["visual_lines"]) == LITERAL


def test_overflow_keeps_exact_srt_and_one_measured_metadata_event_requires_review(tmp_path):
    literal = "Um texto muito longo para a área segura. " * 150
    result = write_episode_subtitles(long_evidence(literal), episode(), tmp_path)
    sync = result["sync"]
    assert len(sync["events"]) == 1 and sync["events"][0]["literal_text"] == literal
    assert sync["events"][0]["source_start"] == 2.125
    assert sync["events"][0]["source_end"] == 12.375
    assert sync["events"][0]["layout"]["font_size"] >= 20
    assert not sync["events"][0]["ass_event_written"]
    assert sync["needs_human_review"]
    assert any(row["code"] == "caption_overflow_requires_human_review" for row in sync["diagnostics"])
    assert literal in Path(result["srt"]).read_text(encoding="utf-8")


def test_long_block_without_proven_padding_requires_visual_review(tmp_path):
    result = write_episode_subtitles(long_evidence(), episode(padding=False), tmp_path)
    layout = result["sync"]["events"][0]["layout"]
    assert layout["fits_safe_box"] and layout["padding_evidence"] is None
    assert result["sync"]["needs_human_review"]
    assert any(row["code"] == "caption_block_requires_source_visual_review" for row in result["sync"]["diagnostics"])


def test_wrapping_uses_actual_font_widths_not_character_count(tmp_path):
    thin = write_episode_subtitles(long_evidence("iii " * 20), episode(), tmp_path / "thin", overrides={"max_chars": 80})
    wide = write_episode_subtitles(long_evidence("WWW " * 20), episode(), tmp_path / "wide", overrides={"max_chars": 80})
    thin_lines = thin["sync"]["events"][0]["layout"]["visual_lines"]
    wide_lines = wide["sync"]["events"][0]["layout"]["visual_lines"]
    assert len(wide_lines) > len(thin_lines)


def test_unavailable_font_family_falls_back_explicitly_and_ass_matches_measured_font(tmp_path):
    result = write_episode_subtitles(long_evidence("Texto."), episode(), tmp_path, overrides={"font": "MissingLocalFamily999"})
    resolved = result["sync"]["font_resolution"]
    assert resolved["fallback"] and resolved["resolved_family"] != "MissingLocalFamily999"
    assert "Style: Sub," + resolved["resolved_family"] + "," in Path(result["ass"]).read_text(encoding="utf-8-sig")


def test_word_highlight_spans_receive_visual_breaks_without_changed_boundaries(tmp_path):
    words = ["Interoperabilidade", "documental", "temporal", "verificável"]
    data = {"segments": [{"segment_id": "S1", "start": 0, "end": 4, "text": " ".join(words)}],
        "words": [{"segment_id": "S1", "word_id": f"W{index}", "word": word, "start": index, "end": index+.8} for index, word in enumerate(words)]}
    result = write_episode_subtitles(data, {"source_start": 0, "source_end": 4}, tmp_path, overrides={"max_words": 4, "max_chars": 20})
    sync = result["sync"]
    assert sync["alignment"] == "word"
    assert [(event["start"], event["end"]) for event in sync["events"]] == [(0,.8),(.8,1),(1,1.8),(1.8,2),(2,2.8),(2.8,3),(3,3.8)]
    ass = Path(result["ass"]).read_text(encoding="utf-8-sig")
    assert "\\N" in ass
    assert all(event["layout"]["font_size"] >= 20 for event in sync["events"])
    assert all(event["literal_text"] == " ".join(words) for event in sync["events"])


def test_unicode_case_expansion_keeps_original_word_span_mapping(tmp_path):
    literal = "Straße groß Straße groß"
    data = long_evidence(literal)
    result = write_episode_subtitles(data, episode(), tmp_path, overrides={"uppercase": True, "max_chars": 12})
    assert result["sync"]["events"][0]["literal_text"] == literal
    assert "".join(result["sync"]["events"][0]["layout"]["visual_lines"]) == literal
    assert literal in Path(result["srt"]).read_text(encoding="utf-8")
    assert "STRASSE" in Path(result["ass"]).read_text(encoding="utf-8-sig")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg local ausente")
def test_actual_libass_long_block_is_legible_inside_lower_padding(tmp_path):
    from ldporto_curator.render import _ass_filter_path
    result = write_episode_subtitles(long_evidence(), episode(), tmp_path / "captions")
    frame = tmp_path / "actual_long_caption.png"
    subtitle_filter = "subtitles='" + _ass_filter_path(Path(result["ass"])) + "'"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=gray:s=540x960:r=20:d=1", "-vf", subtitle_filter, "-frames:v", "1", str(frame)], check=True)
    with Image.open(frame) as image:
        pixels = image.convert("RGB")
        rows = [y for y in range(pixels.height) if any(all(value > 220 for value in pixels.getpixel((x,y))) for x in range(pixels.width))]
    assert rows and min(rows) > 632 and max(rows) <= 787
    groups = []
    for y in rows:
        # Accents and descenders can leave a one-pixel gap inside a glyph row.
        if not groups or y > groups[-1][-1] + 3:
            groups.append([])
        groups[-1].append(y)
    assert len(groups) > 2
    assert min(group[-1]-group[0]+1 for group in groups) >= 12
