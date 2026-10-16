"""Exercise the actual libass renderer, including silence between measured words."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from ldporto_curator.render import _ass_filter_path
from ldporto_curator.subtitle_presets import write_episode_subtitles


pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg local ausente")


def _frame(ass: Path, time: float, size=(540, 960)):
    # A single synthetic frame carries the requested presentation timestamp into
    # libass. This tests millisecond changes without video-frame quantization.
    width, height = size
    filters = (f"format=rgb24,setpts=PTS+{round(time*1000)},"
               f"subtitles='{_ass_filter_path(ass)}',format=rgb24")
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=black:s={width}x{height}:r=1000:d=0.001",
        "-vf", filters, "-frames:v", "1", "-f", "rawvideo", "-",
    ], check=True, capture_output=True)
    return np.asarray(Image.frombytes("RGB", size, result.stdout)).astype(int)


def _masks(pixels):
    red, green, blue = [pixels[:, :, channel] for channel in range(3)]
    return {
        "white": (red > 190) & (green > 190) & (blue > 190),
        "yellow": (red > 190) & (green > 130) & (blue < 70),
        "glyph": red > 100,
    }


def _synthetic(tmp_path):
    starts = (.205, .907, 1.803)
    ends = (.405, 1.207, 2.107)
    evidence = {
        "segments": [{"segment_id": "gaps", "start": 0., "end": 2.3,
                      "text": "WWW WWW WWW"}],
        "words": [{"word_id": f"w{i}", "segment_id": "gaps", "word": "WWW",
                   "start": start, "end": end}
                  for i, (start, end) in enumerate(zip(starts, ends), 1)],
    }
    return write_episode_subtitles(
        evidence, {"episode_id": "raster", "source_start": 0., "source_end": 2.3},
        tmp_path, preset="LDP_REELS_KARAOKE",
        overrides={"pause_threshold_seconds": 1., "block_max_seconds": 4.},
    )


def test_real_libass_reveals_whole_phrase_then_keeps_spoken_words_white(tmp_path):
    result = _synthetic(tmp_path)
    assert len(result["sync"]["events"]) == 1
    assert result["sync"]["events"][0]["word_ids"] == ["w1", "w2", "w3"]
    samples = (.220, .600, .906, .909, 1.400, 1.802, 1.805, 2.090)
    rendered = [_masks(_frame(Path(result["ass"]), time)) for time in samples]
    # All three complete glyph groups exist from the first spoken word. Their
    # aggregate geometry never changes while only their fill colors change.
    baseline = rendered[0]["glyph"]
    rows, columns = np.where(baseline)
    assert len(columns) > 300
    bounds = (int(columns.min()), int(rows.min()), int(columns.max()), int(rows.max()))
    column_has_glyph = baseline.any(axis=0)
    runs = []
    for column in np.flatnonzero(column_has_glyph):
        if not runs or column > runs[-1][-1] + 1:
            runs.append([int(column)])
        else:
            runs[-1].append(int(column))
    # Three W glyphs share each word; gaps between words exceed glyph gaps.
    gaps = [(right[0] - left[-1], left[-1], right[0]) for left, right in zip(runs, runs[1:])]
    word_boundaries = sorted((left + right) // 2 for _, left, right in sorted(gaps, reverse=True)[:2])
    assert len(word_boundaries) == 2
    slices = [slice(0, word_boundaries[0]), slice(word_boundaries[0], word_boundaries[1]), slice(word_boundaries[1], 540)]
    for time, masks in zip(samples, rendered):
        ys, xs = np.where(masks["glyph"])
        assert (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) == bounds
        intersection = np.logical_and(baseline, masks["glyph"]).sum()
        union = np.logical_or(baseline, masks["glyph"]).sum()
        # RGB/YUV color conversion changes antialiased edge intensities slightly;
        # the exact outer bounds and >98% fill overlap detect layout movement.
        assert intersection / union > .98, f"The phrase moved at {time}s"
        spoken = sum(onset <= time for onset in (.205, .907, 1.803))
        for index, columns_slice in enumerate(slices):
            white = int(masks["white"][:, columns_slice].sum())
            yellow = int(masks["yellow"][:, columns_slice].sum())
            if index < spoken:
                assert white > 100 and yellow == 0, (time, index, white, yellow)
            else:
                assert yellow > 100 and white == 0, (time, index, white, yellow)
    layout = result["sync"]["events"][0]["layout"]
    safe = layout["safe_bounds"]
    assert safe["left"] <= bounds[0] <= bounds[2] <= safe["right"]
    assert safe["top"] <= bounds[1] <= bounds[3] <= safe["bottom"]


def test_real_libass_never_turns_first_fractional_onset_white_early(tmp_path):
    result = _synthetic(tmp_path)
    before = _masks(_frame(Path(result["ass"]), .204))
    onset = _masks(_frame(Path(result["ass"]), .205))
    after = _masks(_frame(Path(result["ass"]), .207))
    assert before["white"].sum() == 0
    assert onset["white"].sum() > 100
    assert after["white"].sum() > 100
    assert after["yellow"].sum() > 100


def test_real_libass_replaces_completed_block_without_overlay_or_fade(tmp_path):
    evidence = {
        "segments": [
            {"segment_id": "a", "start": 0., "end": 1., "text": "WWW WWW WWW"},
            {"segment_id": "b", "start": 1., "end": 2., "text": "III III III"},
        ],
        "words": [
            {"word_id": f"{sid}{i}", "segment_id": sid, "word": word,
             "start": offset + i * .2, "end": offset + i * .2 + .2}
            for sid, offset, word in (("a", 0., "WWW"), ("b", 1., "III"))
            for i in range(3)
        ],
    }
    result = write_episode_subtitles(evidence, {"source_start": 0., "source_end": 2.},
                                     tmp_path, preset="LDP_REELS_KARAOKE")
    assert len(result["sync"]["events"]) == 2
    first = _masks(_frame(Path(result["ass"]), .59))
    gap = _masks(_frame(Path(result["ass"]), .80))
    replacement = _masks(_frame(Path(result["ass"]), 1.01))
    assert first["white"].sum() > 300 and first["yellow"].sum() == 0
    assert gap["glyph"].sum() == 0
    assert replacement["white"].sum() > 50 and replacement["yellow"].sum() > 100
    assert replacement["glyph"].sum() < first["glyph"].sum() / 2
