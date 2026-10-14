"""Additive V5 caption styles with literal text and auditable word alignment.

Word highlights use separate ASS events at actual start/end boundaries. They do
not infer word timing by distributing a segment duration or summing karaoke tags.
The legacy V4.4 writer remains available in :mod:`subtitles`.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re

from .subtitles import esc_ass, srt_time
from .title_card import _load_font


_BASE = {
    "font": "Segoe UI", "font_size_final": 68, "bold": True,
    "color": "#FFFFFF", "highlight_color": "#C5FF35",
    "outline_color": "#101010", "box_color": "#000000",
    "outline": 5.0, "shadow": 2.0, "box_opacity": 0.0,
    "position_y": 0.76, "safe_zone": {"left": .08, "right": .16, "top": .12, "bottom": .18},
    "uppercase": False, "animation": "none", "max_words": 5,
    "max_chars": 28, "max_lines": 2, "highlight_words": [], "word_highlight": False,
}
SUBTITLE_PRESETS = {
    "LDP_KARAOKE_POP": dict(_BASE, word_highlight=True),
    "LDP_IMPACTO": dict(_BASE, font_size_final=94, max_words=3, word_highlight=True, highlight_color="#FFD335"),
    "LDP_CLEAN": dict(_BASE, font_size_final=60, outline=3.0, shadow=1.0, max_words=12),
    "LDP_DOCUMENTARIO": dict(_BASE, font_size_final=56, bold=False, outline=2.0, shadow=1.0, max_words=14, box_opacity=.65),
    "LDP_PALAVRA_CHAVE": dict(_BASE, word_highlight=True, highlight_color="#FFD335", max_words=7),
    "SEM_LEGENDA": dict(_BASE, enabled=False),
}
PRESET_ALIASES = {"LDP_KARAOKE_VERDE": "LDP_KARAOKE_POP", "LDP_IMPACTO_AMARELO": "LDP_IMPACTO"}


def _finite(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: número obrigatório") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name}: número finito obrigatório")
    return value


def resolve_subtitle_preset(preset="LDP_KARAOKE_POP", overrides=None):
    """Return a validated independent preset; sizes are expressed at 1080x1920."""
    key = PRESET_ALIASES.get(preset, preset) if isinstance(preset, str) else "PERSONALIZADO"
    if isinstance(preset, dict):
        result = deepcopy(_BASE)
        values = deepcopy(preset)
    else:
        if key not in SUBTITLE_PRESETS:
            raise ValueError(f"Preset de legenda desconhecido: {preset}")
        result = deepcopy(SUBTITLE_PRESETS[key])
        values = {}
    values.update(deepcopy(overrides or {}))
    unknown = set(values) - set(_BASE) - {"enabled", "name"}
    if unknown:
        raise ValueError("Controles de legenda desconhecidos: " + ", ".join(sorted(unknown)))
    if "safe_zone" in values:
        values["safe_zone"] = dict(result["safe_zone"], **values["safe_zone"])
    result.update(values)
    result["name"] = values.get("name", key)
    if not isinstance(result["font"], str) or not result["font"].strip() or re.search(r"[,\r\n{}\\]", result["font"]):
        raise ValueError("Família de fonte ASS inválida")
    for field in ("color", "highlight_color", "outline_color", "box_color"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(result[field])):
            raise ValueError(f"Cor inválida: {field}; use #RRGGBB")
    for field, low, high in (("font_size_final", 20, 160), ("outline", 0, 16), ("shadow", 0, 16), ("box_opacity", 0, 1)):
        result[field] = _finite(result[field], field)
        if not low <= result[field] <= high:
            raise ValueError(f"{field} fora de {low}–{high}")
    for field, maximum in (("max_words", 30), ("max_chars", 80), ("max_lines", 3)):
        value = _finite(result[field], field)
        if value != int(value) or not 1 <= value <= maximum:
            raise ValueError(f"{field} inválido")
        result[field] = int(value)
    for field in ("uppercase", "bold", "word_highlight", "enabled"):
        if field in result and not isinstance(result[field], bool):
            raise ValueError(f"{field}: booleano obrigatório")
    if result["animation"] not in {"none", "fade"}:
        raise ValueError("Animação disponível: none ou fade")
    zone = result["safe_zone"]
    if set(zone) != {"left", "right", "top", "bottom"}:
        raise ValueError("Zona segura exige left/right/top/bottom")
    for field in zone:
        zone[field] = _finite(zone[field], "safe_zone." + field)
        if not 0 <= zone[field] < .45:
            raise ValueError("Margem de zona segura inválida")
    result["position_y"] = _finite(result["position_y"], "position_y")
    if not zone["top"] < result["position_y"] <= 1-zone["bottom"]:
        raise ValueError("Legenda fora da zona segura vertical")
    if not isinstance(result["highlight_words"], list) or any(not isinstance(x, str) for x in result["highlight_words"]):
        raise ValueError("highlight_words deve ser lista de palavras")
    return result


def save_subtitle_preset(path, preset):
    resolved = resolve_subtitle_preset(preset)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_subtitle_preset(path):
    return resolve_subtitle_preset(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def _get(evidence, field):
    return (evidence.get(field) if isinstance(evidence, dict) else getattr(evidence, field, None)) or []


def _ass_time(seconds):
    # Integer centiseconds avoid legacy rollover strings such as 0:00:60.00.
    cs = max(0, int(round(seconds * 100)))
    return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"


def _ass_color(hex_color, opacity=1):
    color = hex_color.lstrip("#")
    return f"&H{int(round((1-opacity)*255)):02X}{color[4:6]}{color[2:4]}{color[0:2]}"


def _token(value):
    return re.sub(r"[^\w]", "", value, flags=re.UNICODE).casefold()


def _align_words(segment, global_words):
    literal = str(segment.get("text") or segment.get("literal_text") or "")
    segment_id = str(segment.get("segment_id") or segment.get("id") or "")
    words = segment.get("words")
    if not words:
        words = [w for w in global_words if isinstance(w, dict) and
                 ((segment_id and str(w.get("segment_id") or "") == segment_id) or
                  (not w.get("segment_id") and _overlaps(w, segment["start"], segment["end"])))]
    if not words:
        return [], "missing_word_timestamps"
    text_tokens = list(re.finditer(r"\S+", literal))
    if len(text_tokens) != len(words):
        return [], "incomplete_word_alignment"
    mapped = []
    for index, (word, match) in enumerate(zip(words, text_tokens)):
        if not isinstance(word, dict):
            return [], "invalid_word_record"
        raw = str(word.get("word") or word.get("raw") or word.get("text") or "").strip()
        try:
            start, end = _finite(word.get("start"), "word.start"), _finite(word.get("end"), "word.end")
        except ValueError:
            return [], "invalid_word_timestamps"
        if start < 0 or end <= start or start < segment["start"]-.02 or end > segment["end"]+.02:
            return [], "invalid_word_timestamps"
        if not _token(raw) or _token(raw) != _token(match.group()):
            return [], "word_text_mismatch"
        if mapped and start < mapped[-1]["source_start"]:
            return [], "unordered_word_timestamps"
        mapped.append({"word_id": str(word.get("word_id") or word.get("id") or f"{segment_id}:w{index}"),
                       "source_start": start, "source_end": end, "text": match.group(),
                       "char_start": match.start(), "char_end": match.end()})
    return mapped, None


def _overlaps(item, start, end):
    try:
        a, b = _finite(item.get("start"), "start"), _finite(item.get("end"), "end")
        return b > a >= 0 and b > start and a < end
    except (ValueError, AttributeError):
        return False


@lru_cache(maxsize=64)
def _font_resolution(family, bold):
    """Resolve a local font and report the actual family used by libass."""
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = {
        "segoe ui": ("segoeuib.ttf", "segoeui.ttf"), "arial": ("arialbd.ttf", "arial.ttf"),
        "calibri": ("calibrib.ttf", "calibri.ttf"), "tahoma": ("tahomabd.ttf", "tahoma.ttf"),
        "verdana": ("verdanab.ttf", "verdana.ttf"), "times new roman": ("timesbd.ttf", "times.ttf"),
        "impact": ("impact.ttf", "impact.ttf"),
    }
    pair = names.get(family.casefold())
    preferred = win / pair[0 if bold else 1] if pair else None
    font = _load_font(40, str(preferred) if preferred and preferred.exists() else None)
    path = getattr(font, "path", None)
    actual_family, actual_style = font.getname() if hasattr(font, "getname") else ("default_bitmap", "unknown")
    return str(path) if path else None, {"requested_family": family, "resolved_family": actual_family,
        "resolved_style": actual_style, "font_file": Path(path).name if path else None,
        "fallback": actual_family.casefold() != family.casefold(), "measurement": "Pillow local font bounding boxes and metrics"}


@lru_cache(maxsize=256)
def _sized_font(size, path):
    return _load_font(size, path)


def _measured_wrap(text, font, max_width, max_chars=None, uppercase=False):
    """Return added break offsets; slicing retains every original character."""
    breaks, line_start, previous_end = [], 0, 0
    for match in re.finditer(r"\S+", text):
        separator = text[previous_end:match.start()]
        if "\n" in separator:
            line_start = text.rfind("\n", previous_end, match.start()) + 1
        line = text[line_start:match.end()]
        box = font.getbbox(line.upper() if uppercase else line)
        too_wide = box[2] - box[0] > max_width
        if match.start() > line_start and (too_wide or max_chars and len(line) > max_chars):
            breaks.append(match.start())
            line_start = match.start()
        previous_end = match.end()
    cursor, fragments = 0, []
    for offset in breaks:
        fragments.extend((text[cursor:offset], "\n"))
        cursor = offset
    fragments.append(text[cursor:])
    return breaks, "".join(fragments).split("\n")


def _caption_layout(literal, preset, width, height, font_path, episode, evidence):
    scale = width / 1080
    minimum = max(1, int(math.ceil(40 * scale)))
    requested = preset["font_size_final"] * scale
    desired = max(minimum, int(round(requested)))
    zone = preset["safe_zone"]
    safe = {"left": width * zone["left"], "right": width * (1-zone["right"]),
        "top": height * zone["top"], "bottom": height * (1-zone["bottom"])}
    decoration = max(1, (preset["outline"] + preset["shadow"]) * scale) + 2*scale
    max_width = safe["right"] - safe["left"] - 2*decoration
    center = (safe["left"] + safe["right"]) / 2
    ordinary_bottom = min(height * preset["position_y"], safe["bottom"] - decoration)
    padding_top = None
    source = evidence.get("source") or evidence.get("metadata") or {} if isinstance(evidence, dict) else (getattr(evidence, "analysis", {}).get("metadata") or {})
    camera = episode.get("camera_plan") or {}
    if isinstance(camera, dict) and camera.get("mode") == "full_frame_blur":
        try:
            sw, sh = float(source.get("width")), float(source.get("height"))
            if math.isfinite(sw+sh) and sw > 0 and sh > 0:
                foreground_height = sh * min(width/sw, height/sh)
                padding_top = (height+foreground_height)/2 + max(2, 8*scale)
        except (TypeError, ValueError):
            pass

    def measure(size, chars=None):
        font = _sized_font(size, font_path)
        breaks, lines = _measured_wrap(literal, font, max_width, chars, preset["uppercase"])
        boxes = [font.getbbox(line.upper() if preset["uppercase"] else line) for line in lines]
        widths = [box[2]-box[0] for box in boxes]
        metrics = font.getmetrics() if hasattr(font, "getmetrics") else (size, size*.4)
        line_height = max(size, sum(metrics))
        return breaks, lines, max(widths, default=0), line_height*len(lines), line_height

    def result(size, measured, bottom, mode, overlap=False):
        breaks, lines, text_width, text_height, line_height = measured
        bounds = {"left": center-text_width/2-decoration, "right": center+text_width/2+decoration,
            "top": bottom-text_height-decoration, "bottom": bottom+decoration}
        fits = (bounds["left"] >= safe["left"]-.01 and bounds["right"] <= safe["right"]+.01
            and bounds["top"] >= safe["top"]-.01 and bounds["bottom"] <= safe["bottom"]+.01)
        return {"font_size": size, "font_size_final": size/scale, "requested_font_size": requested,
            "readable_minimum_final": 40, "visual_break_char_offsets": breaks, "visual_lines": lines,
            "line_height": line_height, "bounds": bounds, "safe_bounds": safe, "fits_safe_box": fits,
            "x": center, "y": bottom, "mode": mode, "padding_evidence": "full_frame_blur_source_dimensions" if padding_top is not None else None,
            "source_foreground_end": padding_top-max(2,8*scale) if padding_top is not None else None,
            "needs_human_review": overlap or not fits, "readable_minimum_applied": requested < minimum}

    # Ordinary captions keep the requested position and number of lines when possible.
    for size in range(desired, minimum-1, -1):
        measured = measure(size, preset["max_chars"])
        layout = result(size, measured, ordinary_bottom, "inline")
        if len(measured[1]) <= preset["max_lines"] and layout["fits_safe_box"]:
            return layout
    # A long measured segment remains one event; more lines are a visual operation.
    lower_top = max(safe["top"], padding_top if padding_top is not None else height*.66)
    bottom = safe["bottom"]-decoration
    for size in range(desired, minimum-1, -1):
        measured = measure(size)
        layout = result(size, measured, bottom, "lower_caption_block", overlap=padding_top is None)
        if layout["fits_safe_box"] and layout["bounds"]["top"] >= lower_top:
            return layout
    # Using the wider safe vertical region may cover source content and needs review.
    for size in range(desired, minimum-1, -1):
        layout = result(size, measure(size), bottom, "caption_block_over_source", overlap=True)
        if layout["fits_safe_box"]:
            return layout
    return result(minimum, measure(minimum), bottom, "overflow_not_rendered", overlap=True)


def _styled_body(literal, spans, active, layout, preset, keywords):
    breaks = set(layout["visual_break_char_offsets"])
    edges = sorted({0, len(literal), *breaks, *[span[key] for span in spans for key in ("char_start", "char_end")]})
    fragments = []
    for left, right in zip(edges, edges[1:]):
        if left in breaks:
            fragments.append("\\N")
        span = next((span for span in spans if span["char_start"] <= left < span["char_end"]), None)
        if span:
            highlighted = span["word_id"] in active
            if preset["name"] == "LDP_PALAVRA_CHAVE":
                highlighted = highlighted and _token(literal[span["char_start"]:span["char_end"]]) in keywords
            fragments.append("{\\c" + _ass_color(preset["highlight_color"] if highlighted else preset["color"]) + "}")
        text = literal[left:right]
        fragments.append(esc_ass(text.upper() if preset["uppercase"] else text))
    return "".join(fragments)


def _header(preset, width, height, font_family=None):
    scale = width/1080
    font_size = preset["font_size_final"]*scale
    zone = preset["safe_zone"]
    family = font_family or preset["font"]
    style = f"{family},{font_size:.2f},{_ass_color(preset['color'])},{_ass_color(preset['highlight_color'])},{_ass_color(preset['outline_color'])}"
    return (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{style},{_ass_color(preset['box_color'],preset['box_opacity'])},{-1 if preset['bold'] else 0},0,0,0,100,100,0,0,{3 if preset['box_opacity'] else 1},{preset['outline']*scale:.2f},{preset['shadow']*scale:.2f},2,{int(width*zone['left'])},{int(width*zone['right'])},{int(height*zone['bottom'])},1\n"
        f"Style: CaptionBlock,{family},{font_size:.2f},{_ass_color(preset['color'])},{_ass_color(preset['highlight_color'])},{_ass_color(preset['box_color'],max(.65,preset['box_opacity']))},{_ass_color(preset['box_color'],max(.65,preset['box_opacity']))},{-1 if preset['bold'] else 0},0,0,0,100,100,0,0,3,{preset['outline']*scale:.2f},0,2,{int(width*zone['left'])},{int(width*zone['right'])},{int(height*zone['bottom'])},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def write_episode_subtitles(evidence, episode, directory, preset="LDP_KARAOKE_POP", overrides=None, width=540, height=960):
    """Export SRT, ASS and precise source/relative synchronization metadata.

    SRT always contains the unchanged available segment text. Visual uppercase and
    highlighting live exclusively in ASS and in the explicit preset metadata.
    An incomplete lexical/timing alignment falls back to a segment event.
    """
    st, en = _finite(episode.get("source_start"), "source_start"), _finite(episode.get("source_end"), "source_end")
    if st < 0 or en <= st:
        raise ValueError("Intervalo de episódio inválido")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("Resolução inválida")
    selected = resolve_subtitle_preset(preset, overrides)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    segments = _get(evidence, "segments") or _get(evidence, "captions")
    segments = sorted((s for s in segments if _overlaps(s, st, en)), key=lambda s: (float(s["start"]), float(s["end"])))
    global_words = _get(evidence, "words")
    metadata = {"schema": "LDP_SUBTITLE_SYNC_V5.1", "episode_id": episode.get("episode_id"),
                "source_start": st, "source_end": en, "preset": selected,
                "literal_transcript_unchanged": True, "visual_case_transform": "uppercase" if selected["uppercase"] else "none",
                "time_precision": {"srt_seconds": .001, "ass_seconds": .01},
                "enabled": selected.get("enabled", True), "segments": [], "events": [], "diagnostics": []}
    font_path, font_info = _font_resolution(selected["font"], selected["bold"])
    metadata["font_resolution"] = font_info
    metadata["needs_human_review"] = False
    ass = [_header(selected, width, height, font_info["resolved_family"])]
    srt = []
    zone = selected["safe_zone"]
    keyword_tokens = {_token(value) for value in selected["highlight_words"]}
    layouts = {}

    def event(start, end, literal, spans, active, segment_id, method):
        if end <= start or not selected.get("enabled", True):
            return
        if literal not in layouts:
            layouts[literal] = _caption_layout(literal, selected, width, height, font_path, episode, evidence)
        layout = layouts[literal]
        body = _styled_body(literal, spans, active, layout, selected, keyword_tokens)
        prefix = f"{{\\an2\\q2\\pos({layout['x']:.2f},{layout['y']:.2f})\\fs{layout['font_size']:.2f}}}"
        if selected["animation"] == "fade" and method == "segment":
            prefix += "{\\fad(60,60)}"
        a, b = max(st,start)-st, min(en,end)-st
        # Preserve events below ASS centisecond resolution in metadata; no zero-length ASS events.
        rendered = _ass_time(b) != _ass_time(a) and layout["fits_safe_box"]
        if rendered:
            style = "Sub" if layout["mode"] == "inline" else "CaptionBlock"
            ass.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},{style},,0,0,0,,{prefix}{body}\n")
        if layout["needs_human_review"]:
            metadata["needs_human_review"] = True
            code = "caption_overflow_requires_human_review" if not layout["fits_safe_box"] else "caption_block_requires_source_visual_review"
            if not any(row.get("segment_id") == segment_id and row["code"] == code for row in metadata["diagnostics"]):
                metadata["diagnostics"].append({"segment_id": segment_id, "code": code, "layout": layout["mode"], "needs_human_review": True})
        if layout["readable_minimum_applied"] and not any(row.get("segment_id") == segment_id and row["code"] == "readable_font_minimum_applied" for row in metadata["diagnostics"]):
            metadata["diagnostics"].append({"segment_id": segment_id, "code": "readable_font_minimum_applied", "requested_font_size": layout["requested_font_size"], "rendered_font_size": layout["font_size"]})
        metadata["events"].append({"start": a, "end": b, "source_start": max(st,start), "source_end": min(en,end),
                                   "segment_id": segment_id, "method": method, "literal_text": literal,
                                   "active_word_ids": sorted(active), "ass_event_written": rendered, "layout": deepcopy(layout)})

    for index, original in enumerate(segments, 1):
        segment = dict(original, start=float(original["start"]), end=float(original["end"]))
        literal = str(segment.get("text") or segment.get("literal_text") or "")
        sid = str(segment.get("segment_id") or segment.get("id") or f"segment_{index}")
        a, b = max(st,segment["start"]), min(en,segment["end"])
        words, reason = _align_words(segment, global_words)
        method = "word" if words else "segment"
        visible_words = [w for w in words if w["source_end"]>st and w["source_start"]<en]
        clip_literal = literal[visible_words[0]["char_start"]:visible_words[-1]["char_end"]] if visible_words else literal
        # A verified word map can restrict the displayed text to speech actually
        # intersecting the cut, without rewriting any of its characters.
        srt.append(f"{index}\n{srt_time(a-st)} --> {srt_time(b-st)}\n{clip_literal}\n\n")
        clipped_words = [dict(w, start=max(st,w["source_start"])-st, end=min(en,w["source_end"])-st,
                              clipped=w["source_start"]<st or w["source_end"]>en)
                         for w in words if w["source_end"]>st and w["source_start"]<en]
        metadata["segments"].append({"segment_id": sid, "source_start": segment["start"], "source_end": segment["end"],
                                     "start": a-st, "end": b-st, "literal_text": literal, "clip_literal_text": clip_literal, "speaker": segment.get("speaker"),
                                     "alignment": method, "fallback_reason": reason, "clipped": a!=segment["start"] or b!=segment["end"],
                                     "words": clipped_words})
        if reason:
            metadata["diagnostics"].append({"segment_id": sid, "code": reason, "fallback": "segment"})
            if a!=segment["start"] or b!=segment["end"]:
                metadata["diagnostics"].append({"segment_id": sid, "code": "clipped_segment_text_boundary_unresolved", "fallback": "literal_segment"})
        if not words or not selected["word_highlight"]:
            event(a,b,clip_literal,[],set(),sid,"segment")
            continue
        # Groups are literal contiguous slices. Boundaries include both word starts
        # and ends, so a silence produces an event with no highlighted words.
        for offset in range(0,len(visible_words),selected["max_words"]):
            group = visible_words[offset:offset+selected["max_words"]]
            ga, gb = max(st,group[0]["source_start"]), min(en,max(w["source_end"] for w in group))
            if gb <= ga:
                continue
            char_start, char_end = group[0]["char_start"], group[-1]["char_end"]
            phrase = literal[char_start:char_end]
            spans = [dict(w,char_start=w["char_start"]-char_start,char_end=w["char_end"]-char_start) for w in group]
            edges = sorted({ga,gb,*[max(ga,min(gb,w[k])) for w in group for k in ("source_start","source_end")]})
            for left,right in zip(edges,edges[1:]):
                midpoint = (left+right)/2
                active = {w["word_id"] for w in group if w["source_start"]<=midpoint<w["source_end"]}
                event(left,right,phrase,spans,active,sid,"word")

    alignments = [s["alignment"] for s in metadata["segments"]]
    metadata["alignment"] = "word" if alignments and all(a=="word" for a in alignments) else "mixed" if "word" in alignments else "segment" if alignments else "missing"
    paths = {"ass": directory/"CAPTIONS.ass", "srt": directory/"CAPTIONS.srt", "sync_metadata": directory/"SUBTITLE_SYNC.json"}
    paths["ass"].write_text("".join(ass), encoding="utf-8-sig")
    paths["srt"].write_text("".join(srt), encoding="utf-8")
    paths["sync_metadata"].write_text(json.dumps(metadata,ensure_ascii=False,indent=2), encoding="utf-8")
    return {**{name: str(path) for name,path in paths.items()}, "sync": metadata, "preset": selected}
