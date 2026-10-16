"""Render only the frozen Story Parte 1 with the existing Reels karaoke style.

Creates a separate review project and evidence; never approves or renders the
other fifteen Stories. No Analyzer, transcription, curation, or model is run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import html
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ldporto_curator.approval import file_hash
from ldporto_curator.config import load_config
from ldporto_curator.render import _ass_filter_path
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles

EPISODE = "PROP_f654d728d26180f2fb0e5816"
REFERENCE = ROOT / "output/renders/zd_wjssZ7mc/revisions/55bf1ca6c93243e1865879065f379598/SECOND_LDP26_REEL_01_01/batches/988aaf8d4e7440ff8620be399b559858/SECOND_LDP26_REEL_01_01_FINAL.mp4"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run(arguments):
    return subprocess.run(arguments, check=True, capture_output=True)


def seconds(value):
    hours, minutes, sec = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(sec)


def verify(sync, expected_ids, directory):
    """Audit absolute serialized transitions against immutable Analyzer words."""
    events = sync["events"]
    ids = [word for event in events for word in event["word_ids"]]
    assert ids == expected_ids and len(ids) == len(set(ids)) == 71
    assert sync["preset"]["name"] == "LDP_REELS_KARAOKE"
    assert sync["preset"]["reveal_mode"] == "block" and sync["renderable"]
    assert sync["visual_behavior"] == "yellow_phrase_cumulative_white_at_measured_onset"
    assert sync["no_color_anticipation"] is True
    ass_text = (directory / "CAPTIONS.ass").read_text(encoding="utf-8-sig")
    rows = [line.split(",", 9) for line in ass_text.splitlines() if line.startswith("Dialogue:")]
    cues = (directory / "CAPTIONS.srt").read_text(encoding="utf-8").strip().split("\n\n")
    assert len(rows) == len(cues) == len(events)
    assert "\\fad" not in ass_text and "\\move" not in ass_text and "\\kf" not in ass_text
    original = {word["word_id"]: word for segment in sync["segments"] for word in segment["words"]}
    transitions = []
    for event, row, cue in zip(events, rows, cues):
        assert 0 <= event["start"] < event["end"] <= sync["duration"] + 1e-8
        assert 1 <= len(event["word_ids"]) <= 6 and event["method"] == "word"
        layout = event["layout"]
        assert 1 <= len(layout["visual_lines"]) <= 2 and layout["fits_safe_box"]
        assert layout["x"] == 270 and layout["y"] == 800
        assert layout["ass_font_size"] == 30 and layout["font_size_final"] == 60
        assert "\n".join(cue.splitlines()[2:]) == event["literal_text"]
        body = re.sub(r"\{[^}]*\}", "", row[9]).replace("\\N", "\n")
        assert body.split() == event["literal_text"].split()
        ass_start, ass_end = map(seconds, row[1:3])
        cue_start, cue_end = map(seconds, cue.splitlines()[1].split(" --> "))
        assert abs(ass_start-event["start"]) <= .005001 and abs(ass_end-event["end"]) <= .005001
        assert abs(cue_start-event["start"]) <= .000501 and abs(cue_end-event["end"]) <= .000501
        # Each positive step is an absolute word onset relative to the serialized
        # event start. No duration summation, end reset, or color interpolation.
        serialized_steps = re.findall(r"\\t\((\d+),(\d+),\\1?c&H(?:00)?FFFFFF&\)", row[9])
        assert all(left == right for left, right in serialized_steps)
        expected_steps = []
        for word in event["words"]:
            source_word = original[word["word_id"]]
            assert word["source_start"] == source_word["source_start"]
            assert word["source_end"] == source_word["source_end"]
            onset = max(0., word["source_start"]-sync["source_start"])
            offset = max(0, math.ceil((onset-ass_start)*1000-1e-7))
            if offset:
                expected_steps.append((str(offset), str(offset)))
            serialized_onset = ass_start + offset/1000
            assert serialized_onset >= onset-1e-7
            # ASS event boundaries are centiseconds; color steps are milliseconds.
            assert serialized_onset-onset <= .005001
            transitions.append({"event_id": event["event_id"], "word_id": word["word_id"],
                                "text": word["text"], "analyzer_source_onset": word["source_start"],
                                "clip_onset": onset, "ass_absolute_onset": serialized_onset,
                                "white_until_block_end": event["end"]})
        assert serialized_steps == expected_steps, (event["event_id"], serialized_steps, expected_steps)
    style = next(line.removeprefix("Style: ").split(",") for line in ass_text.splitlines() if line.startswith("Style: Sub,"))
    assert style[1] == "Segoe UI" and float(style[2]) == 30 and style[7] == "-1"
    assert style[5].upper() == "&H00101010"
    assert [float(style[index]) for index in (16, 17, 18)] == [3., 1., 2.]
    assert [int(style[index]) for index in (19, 20, 21)] == [65, 65, 160]
    return {"canonical_blocks": len(events), "word_ids": len(ids), "ordered_lossless_unique": True,
            "block_word_count_distribution": dict(Counter(len(event["word_ids"]) for event in events)),
            "max_lines": max(len(event["layout"]["visual_lines"]) for event in events),
            "all_within_safe_box": True, "full_phrase_before_future_word_onsets": True,
            "cumulative_white_no_end_reset": True, "absolute_measured_color_transitions": transitions,
            "ass_no_color_anticipation": True, "srt_text_and_block_times_equivalent": True,
            "style_equivalent_to_current_reels": True, "human_audio_review": "PENDING"}


def media_info(path):
    data = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate", "-of", "json", str(path)]).stdout)
    stream = data["streams"][0]
    return {"width": stream["width"], "height": stream["height"],
            "fps": float(Fraction(stream["r_frame_rate"]))}


def video_frame(media, time, path):
    info = media_info(media)
    index = max(0, round(time*info["fps"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-i", str(media), "-vf",
         f"select=eq(n\\,{index}),scale=540:960", "-frames:v", "1", "-fps_mode", "vfr", str(path)])
    return {"file": path.name, "frame_index": index, "presentation_time": index/info["fps"],
            "requested_time": time, "sha256": file_hash(path)}


def subtitle_frame(ass, time, path):
    from PIL import Image
    import numpy as np
    # libass evaluates milliseconds. The report records that precision and the
    # encoded video separately; encoded color changes occur at its next frame.
    quantized = round(time*1000)/1000
    filters = f"format=rgb24,setpts=PTS+{round(quantized*1000)},subtitles='{_ass_filter_path(ass)}',format=rgb24"
    data = run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black:s=540x960:r=1000:d=0.001", "-vf", filters,
                "-frames:v", "1", "-f", "rawvideo", "-"]).stdout
    image = Image.frombytes("RGB", (540, 960), data)
    image.save(path)
    pixels = np.asarray(image).astype(int)
    r, g, b = [pixels[:, :, channel] for channel in range(3)]
    return {"file": path.name, "presentation_time": quantized,
            "white_fill_pixels": int(((r > 190) & (g > 190) & (b > 190)).sum()),
            "yellow_fill_pixels": int(((r > 190) & (g > 130) & (b < 70)).sum()),
            "sha256": file_hash(path)}


def verify_encoded_karaoke(preview, ass, sync, directory, *, assert_valid=True):
    """Read real MP4 frame PTS and classify glyph fills using ASS-derived masks.

    A rendered word mask excludes the video background. First words additionally
    require future glyphs in their new phrase to be yellow, distinguishing the
    new phrase from the preceding white phrase at the same screen position.
    """
    import numpy as np
    from PIL import Image
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    frame_data = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(preview)]).stdout)
    timestamps = [float(frame["best_effort_timestamp_time"]) for frame in frame_data["frames"]]
    interval = sorted(b-a for a, b in zip(timestamps, timestamps[1:]))[len(timestamps)//2-1]
    masks = []
    crop_top, crop_height = 680, 160
    for event_index, event in enumerate(sync["events"], 1):
        group = []
        for word_index, word in enumerate(event["words"], 1):
            onset = max(0., word["source_start"]-sync["source_start"])
            after = directory / f"mask_{event_index:02d}_{word_index:02d}_at.png"
            subtitle_frame(ass, onset+.001, after)
            with Image.open(after) as image:
                at = np.asarray(image).astype(int)
            mask = np.all(at > 220, axis=2)
            if word_index > 1:
                before = directory / f"mask_{event_index:02d}_{word_index:02d}_before.png"
                subtitle_frame(ass, onset-.001, before)
                with Image.open(before) as image:
                    prior = np.asarray(image).astype(int)
                mask &= (prior[:, :, 0] > 200) & (prior[:, :, 1] > 130) & (prior[:, :, 2] < 60)
            ys, xs = np.where(mask)
            assert len(xs) >= 3, (word["word_id"], "insufficient solid glyph fill")
            assert ys.min() >= crop_top and ys.max() < crop_top+crop_height
            group.append({"event_id": event["event_id"], "word_id": word["word_id"],
                          "text": word["text"], "onset": onset, "block_start": event["start"],
                          "first_in_block": word_index == 1, "mask_pixels": len(xs),
                          "ys": ys-crop_top, "xs": xs, "first_white": None})
        # All supplied production phrases have 3–6 words, so each first word has
        # a future yellow phrase that identifies when its block actually appears.
        future_ys = np.concatenate([item["ys"] for item in group[1:]])
        future_xs = np.concatenate([item["xs"] for item in group[1:]])
        group[0]["future_ys"], group[0]["future_xs"] = future_ys, future_xs
        masks.extend(group)
    command = ["ffmpeg", "-v", "error", "-i", str(preview), "-vf",
               f"crop=540:{crop_height}:0:{crop_top}", "-fps_mode", "passthrough",
               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_size = 540*crop_height*3
    for frame_index, timestamp in enumerate(timestamps):
        raw = process.stdout.read(frame_size)
        assert len(raw) == frame_size, (frame_index, len(raw), frame_size)
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape((crop_height, 540, 3)).astype(int)
        for item in masks:
            if item["first_white"] is not None or not item["onset"]-2*interval <= timestamp <= item["onset"]+2*interval:
                continue
            if not item["first_in_block"] and timestamp < item["block_start"]:
                continue
            values = pixels[item["ys"], item["xs"]]
            white = np.all(values > 165, axis=1) & (np.ptp(values, axis=1) < 65)
            white_fraction = float(white.mean())
            if white_fraction < .6:
                continue
            if item["first_in_block"]:
                future = pixels[item["future_ys"], item["future_xs"]]
                yellow = (future[:, 0] > 150) & (future[:, 1] > 110) & (future[:, 2] < 130) & (future[:, 0]-future[:, 2] > 70)
                if float(yellow.mean()) < .5:
                    continue
            item["first_white"] = {"frame_index": frame_index, "pts": timestamp,
                                   "solid_fill_white_fraction": white_fraction}
    process.stdout.close()
    stderr = process.stderr.read()
    assert process.wait() == 0, stderr.decode(errors="replace")
    results = []
    for item in masks:
        found = item["first_white"]
        early = found is not None and found["pts"] < item["onset"]-.001
        late = found is None or found["pts"]-item["onset"] > interval+.001
        results.append({key: item[key] for key in ("event_id", "word_id", "text", "onset", "first_in_block", "mask_pixels")} | {
            "first_white_encoded_frame": found, "early": early, "later_than_first_available_frame": late,
            "passes": found is not None and not early and not late})
    report = {"method": "actual decoded MP4 presentation timestamps and solid per-word ASS glyph fill masks",
              "frame_interval_seconds": interval, "decoded_frames": len(timestamps), "word_count": len(results),
              "passed": sum(result["passes"] for result in results), "failed": sum(not result["passes"] for result in results),
              "color_anticipation_tolerance_seconds": .001, "words": results}
    save(directory / "ENCODED_KARAOKE_VALIDATION.json", report)
    if assert_valid:
        assert report["failed"] == 0, [(result["word_id"], result["onset"], result["first_white_encoded_frame"]) for result in results if not result["passes"]]
    return report


def extract_evidence(preview, original, previous, reference, sync, directory):
    from PIL import Image, ImageDraw, ImageFont
    frames = directory / "frames"
    frames.mkdir()
    samples = []
    first = next(event for event in sync["events"] if len(event["words"]) >= 3)
    # Sample two changes, including the measured boundary itself, and both sides
    # of the first block replacement. Color state is derived from source onsets.
    boundaries = [("palavra_2", first["words"][1]["source_start"]-sync["source_start"]),
                  ("palavra_3", first["words"][2]["source_start"]-sync["source_start"]),
                  ("fim_bloco_1", first["end"]), ("inicio_bloco_2", sync["events"][1]["start"])]
    fps = media_info(preview)["fps"]
    for name, boundary in boundaries:
        for label, time in (("antes", boundary-.01), ("no_tempo", boundary), ("depois", boundary+.01)):
            if not 0 <= time < sync["duration"]:
                continue
            exact = subtitle_frame(directory / "CAPTIONS.ass", time, frames / f"ass_{name}_{label}.png")
            active = [event for event in sync["events"] if event["start"] <= exact["presentation_time"] < event["end"]]
            exact["expected_words"] = [{"event_id": event["event_id"], "text": event["literal_text"],
                "white": [word["word_id"] for word in event["words"] if word["source_start"]-sync["source_start"] <= exact["presentation_time"]],
                "yellow": [word["word_id"] for word in event["words"] if word["source_start"]-sync["source_start"] > exact["presentation_time"]]}
                for event in active]
            samples.append({"boundary": name, "position": label, "exact_ass": exact})
        next_frame = math.ceil(boundary*fps-1e-7)
        for offset, label in ((-1, "antes"), (0, "primeiro_frame"), (1, "depois")):
            time = (next_frame+offset)/fps
            if 0 <= time < sync["duration"]:
                samples.append({"boundary": name, "position": label,
                                "encoded_preview": video_frame(preview, time, frames / f"video_{name}_{label}.png")})
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 20)
    panel_times = (.60, 1.20)
    comparisons = []
    for time in panel_times:
        contact = Image.new("RGB", (2160, 1000), "#151b25")
        for column, (kind, media, stamp) in enumerate((
                ("Reel atual (referência)", reference, .60),
                ("Story original preservado", original, time),
                ("Prévia anterior: palavra isolada", previous, time),
                ("Nova Parte 1: karaokê dos Reels", preview, time))):
            name = f"comparacao_{column}_{time:.2f}.png"
            record = video_frame(media, stamp, frames / name)
            with Image.open(frames / name) as frame:
                contact.paste(frame.convert("RGB"), (column*540, 40))
            ImageDraw.Draw(contact).text((column*540+8, 8), kind, font=font, fill="white")
            comparisons.append(dict(record, label=kind, time=stamp))
        contact.save(frames / f"COMPARACAO_{time:.2f}s.jpg", quality=93)
    raster_checks = []
    for name in ("palavra_2", "palavra_3"):
        group = {sample["position"]: sample["exact_ass"] for sample in samples
                 if sample["boundary"] == name and "exact_ass" in sample}
        before, onset, after = [group[key] for key in ("antes", "no_tempo", "depois")]
        assert before["white_fill_pixels"] < onset["white_fill_pixels"] == after["white_fill_pixels"]
        assert before["yellow_fill_pixels"] > onset["yellow_fill_pixels"] == after["yellow_fill_pixels"]
        raster_checks.append({"boundary": name, "actual_fill_color_step_at_onset": True,
                              "white_preserved_after_onset": True})
    # Inspect every real phrase on a plain background so the actual libass glyph
    # and outline bounds can be distinguished from the presenter's video.
    geometry = []
    for index, event in enumerate(sync["events"], 1):
        frame = frames / f"layout_bloco_{index:02d}.png"
        stamp = min(event["end"]-.01, event["start"]+.01)
        subtitle_frame(directory / "CAPTIONS.ass", stamp, frame)
        with Image.open(frame) as image:
            bbox = image.point(lambda value: 255 if value > 10 else 0).getbbox()
        assert bbox is not None
        left, top, right, bottom = bbox
        safe = event["layout"]["safe_bounds"]
        assert left >= safe["left"] and right <= safe["right"]
        assert top >= safe["top"] and bottom <= safe["bottom"]
        geometry.append({"event_id": event["event_id"], "frame": frame.name,
                         "actual_libass_bbox": list(bbox), "inside_safe_margins": True})
    return {"samples": samples, "comparisons": comparisons, "raster_color_checks": raster_checks,
            "all_blocks_actual_raster_geometry": geometry,
            "ass_sample_precision_seconds": .001, "preview_frame_duration_seconds": 1/fps,
            "first_word_semantics": "O bloco surge com a primeira palavra já branca em seu início real; as seguintes permanecem amarelas. Não se acrescenta um frame amarelo que atrasaria o primeiro destaque."}


def main(args):
    parent = SeriesProject(args.project, load_config(ROOT / "config.yaml"), log=lambda text: print(text, flush=True))
    episode = parent.episode(EPISODE)
    original = parent.directory / episode["preview"]["project_path"]
    assert file_hash(original) == episode["preview"]["sha256"]
    assert file_hash(args.source) == parent.evidence["source"]["sha256"]
    assert args.previous.is_file() and args.reference_reel.is_file()
    protected = {str(path): file_hash(path) for path in (original, args.previous, args.reference_reel,
                  parent.directory / "series_index.json", parent.directory / "evidence.json")}
    args.report.mkdir(parents=True, exist_ok=True)
    demo = args.report / "story_parte_1"
    assert not demo.exists(), "A pasta de comparação já existe; escolha outra revisão."
    derived = parent.derive_caption_revision(args.derived, episode_ids=[EPISODE], subtitle_preset="LDP_REELS_KARAOKE")
    assert [row["episode_id"] for row in derived.episodes()] == [EPISODE]
    print("Renderizando somente Parte 1, com câmera, título e capas congelados.", flush=True)
    preview = derived.render(EPISODE, args.source, preview=True)
    demo.mkdir()
    names = ("CAPTIONS.ass", "CAPTIONS.srt", "SUBTITLE_SYNC.json", "episode.json", "camera_plan.json",
             "TITLE_LAYOUT.json", "RENDER_RUN.json", "RENDER_VALIDATION.json", "PREVIEW_REVIEW_V5.json", "PREVIEW_540x960.mp4")
    for name in names:
        shutil.copy2(preview.parent / name, demo / name)
    sync = read(demo / "SUBTITLE_SYNC.json")
    checks = verify(sync, episode["word_ids"], demo)
    selected = derived.episode(EPISODE)
    final = write_episode_subtitles(derived.evidence, selected, demo / "resolution_1080x1920",
        preset=selected["subtitle_preset"], overrides=selected.get("subtitle_overrides"),
        width=1080, height=1920, canonical_timeline=sync)
    assert final["sync"]["canonical_timeline_sha256"] == sync["canonical_timeline_sha256"]
    frames = extract_evidence(demo / "PREVIEW_540x960.mp4", original, args.previous, args.reference_reel, sync, demo)
    assert all(file_hash(path) == digest for path, digest in protected.items())
    frozen_assets = selected["caption_revision"]["frozen_assets"]["files"]
    assert all(file_hash(derived.directory / item["project_path"]) == item["sha256"] for item in frozen_assets)
    save(demo / "KARAOKE_VALIDATION.json", {"checks": checks, "frames": frames,
        "source_sha256": parent.evidence["source"]["sha256"], "preserved_media_and_plans": protected,
        "frozen_asset_count": len(frozen_assets), "human_audio_review": "PENDING"})
    save(args.report / "DELIVERY.json", {"created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_project": str(parent.directory), "derived_project": str(derived.directory),
        "preview": str(demo / "PREVIEW_540x960.mp4"), "checks": checks,
        "rendered_story_count": 1, "other_story_count_untouched": 15,
        "new_human_approvals": 0, "new_final_renders": 0, "curation_runs": 0,
        "source_sha256": parent.evidence["source"]["sha256"]})
    rows = "".join(f"<tr><td>{i}</td><td>{event['start']:.3f}–{event['end']:.3f}</td><td>{html.escape(event['literal_text'])}</td><td>{len(event['word_ids'])}</td></tr>" for i, event in enumerate(sync["events"], 1))
    figures = "".join(f'<figure><a href="story_parte_1/frames/COMPARACAO_{time:.2f}s.jpg"><img src="story_parte_1/frames/COMPARACAO_{time:.2f}s.jpg"></a><figcaption>Story em {time:.2f}s; referência Reel em 0.60s. Conteúdos diferentes para comparar o estilo.</figcaption></figure>' for time in (.60, 1.20))
    (args.report / "REVISAO.html").write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Parte 1 — karaokê dos Reels</title><style>body{font:16px system-ui;max-width:1400px;margin:auto;padding:24px;background:#111827;color:#fff}video{max-height:80vh;max-width:100%}img{max-width:100%}td{padding:8px;border-bottom:1px solid #475569}a{color:#9de1ff}figure{margin:24px 0}</style>'
        '<h1>Parte 1 — karaokê dos Reels</h1><p>O bloco completo aparece; palavras futuras ficam amarelas e cada palavra falada fica branca até o fim do bloco. 71 palavras originais preservadas, em blocos com até duas linhas.</p>'
        '<video controls src="story_parte_1/PREVIEW_540x960.mp4"></video><p>' + html.escape(frames["first_word_semantics"]) + '</p><p>Os outros 15 Stories permanecem intocados. Conferência humana do áudio pendente.</p>'
        '<h2>Comparação visual</h2>' + figures + '<h2>Blocos preservados</h2><table><tr><th>Bloco</th><th>Tempo</th><th>Texto original</th><th>Palavras</th></tr>' + rows + '</table></html>', encoding="utf-8")
    print(json.dumps({"report": str(args.report), "preview": str(demo / "PREVIEW_540x960.mp4"),
        "canonical_blocks": checks["canonical_blocks"], "word_ids": checks["word_ids"],
        "rendered_stories": 1, "other_stories_untouched": 15}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--derived", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--previous", type=Path, default=ROOT / "docs/reports/captions_p0_20261015_v2/story_parte_1/PREVIEW_540x960.mp4")
    parser.add_argument("--reference-reel", type=Path, default=REFERENCE)
    main(parser.parse_args())
