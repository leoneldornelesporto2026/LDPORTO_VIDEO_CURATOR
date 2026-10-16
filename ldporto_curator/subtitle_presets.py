"""V5 caption styles with literal text and auditable measured word alignment.

The Reels-compatible profile keeps one complete yellow phrase on screen and
permanently turns each word white at its measured onset. Explicit legacy word
reveal and temporary word-highlight profiles remain available.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import hashlib
import math
import os
from pathlib import Path
import re

from .subtitles import esc_ass, measured_karaoke_body, srt_time
from .title_card import _load_font


_BASE = {
    "font": "Segoe UI", "font_size_final": 68, "bold": True,
    "color": "#FFFFFF", "highlight_color": "#C5FF35",
    "outline_color": "#101010", "box_color": "#000000",
    "outline": 5.0, "shadow": 2.0, "box_opacity": 0.0, "shadow_opacity": 0.0,
    "position_y": 0.76, "safe_zone": {"left": .08, "right": .16, "top": .12, "bottom": .18},
    "uppercase": False, "animation": "none", "max_words": 5,
    "max_chars": 28, "max_lines": 2, "highlight_words": [], "word_highlight": False,
    "reveal_mode": "word", "block_min_seconds": .8, "block_max_seconds": 2.2, "pause_threshold_seconds": .25,
    "color_progression": "window", "font_size_metric": "measured",
}
SUBTITLE_PRESETS = {
    "LDP_REELS_KARAOKE": dict(_BASE, font_size_final=60, color="#FFFFFF", highlight_color="#FFD700",
        outline=6.0, shadow=2.0, shadow_opacity=159/255, position_y=1600/1920,
        safe_zone={"left":130/1080,"right":130/1080,"top":.12,"bottom":.15},
        max_words=6, max_chars=80, word_highlight=True, reveal_mode="block",
        block_max_seconds=2.6, color_progression="cumulative", font_size_metric="ass"),
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
    for field, low, high in (("font_size_final", 20, 160), ("outline", 0, 16), ("shadow", 0, 16), ("box_opacity", 0, 1), ("shadow_opacity", 0, 1)):
        result[field] = _finite(result[field], field)
        if not low <= result[field] <= high:
            raise ValueError(f"{field} fora de {low}–{high}")
    for field, maximum in (("max_words", 30), ("max_chars", 80), ("max_lines", 2)):
        value = _finite(result[field], field)
        if value != int(value) or not 1 <= value <= maximum:
            raise ValueError(f"{field} inválido")
        result[field] = int(value)
    for field in ("uppercase", "bold", "word_highlight", "enabled"):
        if field in result and not isinstance(result[field], bool):
            raise ValueError(f"{field}: booleano obrigatório")
    if result["reveal_mode"] not in {"word", "block"}:
        raise ValueError("reveal_mode deve ser word ou block")
    if result["color_progression"] not in {"window", "cumulative"}:
        raise ValueError("color_progression deve ser window ou cumulative")
    if result["font_size_metric"] not in {"measured", "ass"}:
        raise ValueError("font_size_metric deve ser measured ou ass")
    if result["color_progression"] == "cumulative" and (result["reveal_mode"] != "block" or not result["word_highlight"]):
        raise ValueError("Karaokê cumulativo exige reveal_mode block e word_highlight")
    for field in ("block_min_seconds", "block_max_seconds", "pause_threshold_seconds"):
        result[field] = _finite(result[field], field)
        if result[field] <= 0:
            raise ValueError(field + ": deve ser positivo")
    if result["block_min_seconds"] > result["block_max_seconds"]:
        raise ValueError("Dura??es de bloco inv?lidas")
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


def _raw_words(segment, global_words):
    words = segment.get("words")
    if words:
        return words if isinstance(words, list) else []
    sid = str(segment.get("segment_id") or segment.get("id") or "")
    return [w for w in global_words if isinstance(w, dict) and
            ((sid and str(w.get("segment_id") or "") == sid) or
             (not w.get("segment_id") and _overlaps(w, segment["start"], segment["end"])))]


def _literal_word_spans(literal, words):
    """Map ASR fragments to exact contiguous source characters, without retiming.

    Whitespace tokens are not necessarily timed words: 8.500 may have measured
    records ``8`` and ``.500``. Only a complete lexical match is accepted; each
    record keeps its own interval and receives its literal source substring.
    """
    matches = list(re.finditer(r"\S+", literal))
    normalized = []
    for word in words:
        if not isinstance(word, dict):
            return [], "invalid_word_record"
        raw = str(word.get("word") or word.get("raw") or word.get("text") or "").strip()
        token = _token(raw)
        if not token:
            return [], "word_text_mismatch"
        normalized.append(token)
    if "".join(normalized) != "".join(_token(match.group()) for match in matches):
        return [], "incomplete_word_alignment" if len(matches)!=len(words) else "word_text_mismatch"
    spans, cursor = [], 0
    for match in matches:
        token = match.group()
        target = _token(token)
        # Each normalized character remembers its original Unicode character.
        positions = [offset for offset,char in enumerate(token) for _ in _token(char)]
        consumed, char_start = 0, match.start()
        if not target:
            return [], "word_text_mismatch"
        while consumed < len(target):
            if cursor>=len(normalized) or not target.startswith(normalized[cursor],consumed):
                return [], "word_text_mismatch"
            consumed += len(normalized[cursor])
            if consumed<len(positions) and positions[consumed-1]==positions[consumed]:
                return [], "unicode_fragment_boundary_ambiguous"
            char_end = match.end() if consumed==len(target) else match.start()+positions[consumed-1]+1
            spans.append((char_start,char_end))
            char_start=char_end
            cursor+=1
    if cursor!=len(words):
        return [], "incomplete_word_alignment"
    return spans, None


def _align_words(segment, global_words):
    """Lexically validate source timings; never manufacture a word interval."""
    literal = str(segment.get("text") or segment.get("literal_text") or "")
    sid = str(segment.get("segment_id") or segment.get("id") or "")
    words = _raw_words(segment, global_words)
    if not words:
        return [], "missing_word_timestamps"
    spans,reason = _literal_word_spans(literal,words)
    if reason:
        return [],reason
    mapped, seen = [], set()
    for index, (word, (char_start,char_end)) in enumerate(zip(words,spans)):
        if not isinstance(word, dict):
            return [], "invalid_word_record"
        raw = str(word.get("word") or word.get("raw") or word.get("text") or "").strip()
        try:
            start, end = _finite(word.get("start"), "word.start"), _finite(word.get("end"), "word.end")
        except ValueError:
            return [], "invalid_word_timestamps"
        if start < 0 or end <= start or start < segment["start"]-.02 or end > segment["end"]+.02:
            return [], "invalid_word_timestamps"
        if not _token(raw) or _token(raw) != _token(literal[char_start:char_end]):
            return [], "word_text_mismatch"
        if mapped and start < mapped[-1]["source_start"]:
            return [], "unordered_word_timestamps"
        # Float representation noise at a shared boundary is not an overlap.
        if mapped and start < mapped[-1]["source_end"]-1e-7:
            return [], "overlapping_word_timestamps"
        wid = str(word.get("word_id") or word.get("id") or f"{sid}:w{index}")
        if wid in seen:
            return [], "duplicate_word_ids"
        seen.add(wid)
        mapped.append({"word_id": wid, "source_start": start, "source_end": end,
                       "text": literal[char_start:char_end], "char_start": char_start, "char_end": char_end,
                       "alignment_origin": word.get("timestamp_method") or "provided_word_timestamps",
                       "source": word.get("source"), "hypothesis_id": word.get("hypothesis_id"),
                       "timestamp_precision_seconds": word.get("timestamp_precision_seconds"),
                       "needs_review": bool(word.get("needs_review")),
                       "review_reasons": deepcopy(word.get("review_reasons") or [])})
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
    """Measure once at final resolution: fixed font, strict lines, stable position.

    Failed layouts are explicit blocked events. Splitting is the timeline builder's
    responsibility and may only happen at measured word boundaries.
    """
    scale = width / 1080
    size_final = max(40, preset["font_size_final"])
    size = size_final*scale
    font = _sized_font(int(round(size_final)), font_path)
    zone = preset["safe_zone"]
    safe_final = {"left": 1080*zone["left"], "right": 1080*(1-zone["right"]),
                  "top": 1920*zone["top"], "bottom": 1920*(1-zone["bottom"])}
    decoration = max(1, preset["outline"]+preset["shadow"])+2
    maximum = safe_final["right"]-safe_final["left"]-2*decoration
    breaks, lines = _measured_wrap(literal, font, maximum, preset["max_chars"], preset["uppercase"])
    boxes = [font.getbbox(line.upper() if preset["uppercase"] else line) for line in lines]
    text_width = max((b[2]-b[0] for b in boxes), default=0)
    metrics = font.getmetrics() if hasattr(font, "getmetrics") else (size_final, size_final*.4)
    line_height = max(size_final, sum(metrics))
    bottom = min(1920*preset["position_y"], safe_final["bottom"]-decoration)
    center = (safe_final["left"]+safe_final["right"])/2
    bounds_final = {"left": center-text_width/2-decoration, "right": center+text_width/2+decoration,
                    "top": bottom-line_height*len(lines)-decoration, "bottom": bottom+decoration}
    safe = {k:v*scale for k,v in safe_final.items()}
    bounds = {k:v*scale for k,v in bounds_final.items()}
    line_limit = min(2, preset["max_lines"])
    fits = (len(lines) <= line_limit and bounds["left"] >= safe["left"]-.01
            and bounds["right"] <= safe["right"]+.01 and bounds["top"] >= safe["top"]-.01
            and bounds["bottom"] <= safe["bottom"]+.01)
    # Never expose 3+ lines as a renderable layout, even on unaligned fallbacks.
    return {"font_size": size, "font_size_final": size_final,
            "ass_font_size": (size_final if preset["font_size_metric"]=="ass" else line_height)*scale,
            "ass_font_normalization": "Exact accepted Reels ASS size" if preset["font_size_metric"]=="ass" else "Pillow ascent plus descent matches libass font-size metrics",
            "requested_font_size": preset["font_size_final"]*scale,
            "readable_minimum_final": 40, "visual_break_char_offsets": breaks if fits else [],
            "visual_lines": lines if fits else [], "required_line_count": len(lines),
            "max_lines": line_limit, "line_height": line_height*scale, "bounds": bounds,
            "safe_bounds": safe, "fits_safe_box": fits, "x": center*scale, "y": bottom*scale,
            "mode": "inline" if fits else "overflow_not_rendered", "padding_evidence": None,
            "source_foreground_end": None, "needs_human_review": not fits,
            "readable_minimum_applied": preset["font_size_final"] < 40}


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
    margin_v = int(round(height*(1-preset["position_y"]))) if preset["font_size_metric"]=="ass" else int(height*zone["bottom"])
    wrap_style = 2 if preset["color_progression"]=="cumulative" else 0
    back_color = _ass_color(preset['box_color'],preset['box_opacity'] or preset['shadow_opacity'])
    style = f"{family},{font_size:.2f},{_ass_color(preset['color'])},{_ass_color(preset['highlight_color'])},{_ass_color(preset['outline_color'])}"
    return (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\nWrapStyle: {wrap_style}\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{style},{back_color},{-1 if preset['bold'] else 0},0,0,0,100,100,0,0,{3 if preset['box_opacity'] else 1},{preset['outline']*scale:.2f},{preset['shadow']*scale:.2f},2,{round(width*zone['left'])},{round(width*zone['right'])},{margin_v},1\n"
        f"Style: CaptionBlock,{family},{font_size:.2f},{_ass_color(preset['color'])},{_ass_color(preset['highlight_color'])},{_ass_color(preset['box_color'],max(.65,preset['box_opacity']))},{_ass_color(preset['box_color'],max(.65,preset['box_opacity']))},{-1 if preset['bold'] else 0},0,0,0,100,100,0,0,3,{preset['outline']*scale:.2f},0,2,{int(width*zone['left'])},{int(width*zone['right'])},{int(height*zone['bottom'])},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


ENGINE_VERSION = "5.3.0"
_CANONICAL_FIELDS = ("event_id", "start", "end", "source_start", "source_end", "segment_id",
    "method", "literal_text", "literal_prefix", "literal_suffix", "word_ids", "words", "transcript_reference", "alignment_origin",
    "alignment_precision", "review_status", "clipped", "fallback_reason")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def canonical_timeline_hash(events):
    """Hash exact editorial/time evidence, excluding resolution and ASS styling."""
    return _digest([{key: deepcopy(event.get(key)) for key in _CANONICAL_FIELDS} for event in events])


def _transcript_reference(segments, global_words, episode, evidence):
    content = []
    for segment in segments:
        words = _raw_words(segment, global_words)
        content.append({"segment_id": segment.get("segment_id") or segment.get("id"),
            "start": segment["start"], "end": segment["end"],
            "text": str(segment.get("text") or segment.get("literal_text") or ""),
            # Invalid values stay diagnosable without producing nonstandard JSON.
            "words": [{key: (value if not isinstance(value, float) or math.isfinite(value) else str(value))
                       for key, value in word.items()} for word in words if isinstance(word, dict)]})
    version = episode.get("transcript_version") or (evidence.get("transcript_version") if isinstance(evidence, dict) else None)
    digest = _digest(content)
    return {"version": version or "sha256:"+digest, "sha256": digest,
            "scope": "literal_source_segments_and_word_evidence", "immutable": True}


def _block_groups(words, literal, selected, layout_for):
    """Group measured words once; color progression never changes the layout."""
    if selected["reveal_mode"] == "word":
        return [[word] for word in words]
    cumulative = selected["color_progression"] == "cumulative"
    limit = min(6 if cumulative else 5, selected["max_words"])
    function_words = {"a", "o", "as", "os", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
                      "para", "por", "com", "e", "que", "um", "uma", "ao", "aos"}
    count = len(words)
    costs, choices = [float("inf") ]*(count+1), {}
    costs[count] = 0
    for left in range(count-1,-1,-1):
        for right in range(left+1,(count if cumulative else min(count,left+limit))+1):
            group = words[left:right]
            phrase = literal[group[0]["char_start"]:group[-1]["char_end"]]
            word_count = len(re.findall(r"\S+",phrase)) if cumulative else len(group)
            if word_count>limit:
                break
            # Analyzer can time pieces such as 8 + .500 separately. Keep the
            # complete lexical word in the same phrase while retaining both IDs
            # and both measured color transitions.
            if cumulative and right<count and not literal[group[-1]['char_end']:words[right]['char_start']]:
                continue
            if word_count>1 and (group[-1]["source_end"]-group[0]["source_start"] > selected["block_max_seconds"] or
                    any(b["source_start"]-a["source_end"] > selected["pause_threshold_seconds"] and
                        (not cumulative or literal[a['char_end']:b['char_start']]) for a,b in zip(group,group[1:]))):
                break
            if not layout_for(phrase)["fits_safe_box"]:
                if len(group)==1:
                    choices[left] = right
                break
            duration = group[-1]["source_end"]-group[0]["source_start"]
            penalty = .25 + max(0,selected["block_min_seconds"]-duration)*2
            if len(group)==1 and count>1:
                penalty += 2
            if cumulative and word_count<3 and count>=3:
                penalty += (3-word_count)*1.5
            if right<count:
                if _token(group[-1]["text"]) in function_words:
                    penalty += 3
                # Prefer retaining obvious name pairs (e.g. Lockheed Electra).
                if group[-1]["text"][:1].isupper() and words[right]["text"][:1].isupper():
                    penalty += 3
                if re.search(r"[,.!?;:]$",group[-1]["text"]):
                    penalty -= .2
            score = penalty+costs[right]
            if score<costs[left]:
                costs[left],choices[left] = score,right
    groups, cursor = [],0
    while cursor<count:
        end = choices.get(cursor,cursor+1)
        groups.append(words[cursor:end]); cursor=end
    return groups


def _canonical_events(segments, global_words, st, en, selected, reference, layout_for):
    events, segment_rows, diagnostics = [],[],[]
    globally_seen = set()
    def append(start,end,literal,sid,words,method,reason=None,fallback_ids=None):
        if min(en,end)<=max(st,start):
            return
        ids = [word["word_id"] for word in words] if words else list(fallback_ids or [])
        if globally_seen.intersection(ids):
            raise ValueError("Duplicate word IDs across caption events")
        globally_seen.update(ids)
        origins = sorted({word.get("alignment_origin") or "provided_word_timestamps" for word in words})
        events.append({"event_id": f"CAPTION_{len(events)+1:05d}", "start": max(st,start)-st,
            "end": min(en,end)-st, "source_start": start, "source_end": end, "segment_id": sid,
            "method": method, "literal_text": literal, "literal_prefix": "", "literal_suffix": "",
            "word_ids": ids, "words": deepcopy(words),
            "transcript_reference": deepcopy(reference),
            "alignment_origin": origins if words else ["provided_segment_timestamps"],
            "alignment_precision": {"unit": "seconds", "timestamps": "original_unrounded",
                "accuracy": "not_independently_calibrated", "timing_evidence_validated": bool(words) and not reason, "audio_verified": False},
            "review_status": "NEEDS_HUMAN_AUDIO_REVIEW", "clipped": start<st or end>en,
            "fallback_reason": reason})
    for index,original in enumerate(segments,1):
        segment = dict(original,start=float(original["start"]),end=float(original["end"]))
        literal = str(segment.get("text") or segment.get("literal_text") or "")
        if not literal.strip():
            continue
        sid = str(segment.get("segment_id") or segment.get("id") or f"segment_{index}")
        if any(row["segment_id"]==sid for row in segment_rows):
            raise ValueError("Duplicate source segment IDs")
        aligned,reason = _align_words(segment,global_words)
        visible = [word for word in aligned if word["source_end"]>st and word["source_start"]<en]
        clip_literal = literal[visible[0]["char_start"]:visible[-1]["char_end"]] if visible else literal
        clipped_words = [dict(word,start=max(st,word["source_start"])-st,end=min(en,word["source_end"])-st,
                              clipped=word["source_start"]<st or word["source_end"]>en) for word in visible]
        segment_rows.append({"segment_id": sid, "source_start": segment["start"], "source_end": segment["end"],
            "start": max(st,segment["start"])-st, "end": min(en,segment["end"])-st,
            "literal_text": literal, "clip_literal_text": clip_literal, "speaker": segment.get("speaker"),
            "alignment": "word" if aligned else "segment", "fallback_reason": reason,
            "clipped": st>segment["start"] or en<segment["end"], "words": clipped_words,
            "original_word_ids": [str(word.get("word_id") or word.get("id")) for word in _raw_words(segment,global_words)
                                  if isinstance(word,dict) and (word.get("word_id") or word.get("id"))]})
        if reason:
            diagnostics.append({"segment_id": sid,"code": reason,"fallback": "segment",
                                "needs_human_review": True,
                                **({"blocks_render":True} if selected["color_progression"]=="cumulative" else {})})
            if st>segment["start"] or en<segment["end"]:
                diagnostics.append({"segment_id": sid,"code": "clipped_segment_text_boundary_unresolved",
                                    "fallback": "literal_segment","needs_human_review": True})
            append(segment["start"],segment["end"],literal,sid,[],"segment",reason,
                   fallback_ids=segment_rows[-1]["original_word_ids"])
            continue
        previous_char_end = visible[0]["char_start"] if visible else 0
        for group in _block_groups(visible,literal,selected,layout_for):
            char_start,char_end = group[0]["char_start"],group[-1]["char_end"]
            phrase = literal[char_start:char_end]
            spans = [dict(word,char_start=word["char_start"]-char_start,char_end=word["char_end"]-char_start) for word in group]
            append(group[0]["source_start"],group[-1]["source_end"],phrase,sid,spans,"word")
            events[-1]["literal_prefix"] = literal[previous_char_end:char_start]
            if group[0] is visible[0] and char_start == aligned[0]["char_start"]:
                events[-1]["literal_prefix"] = literal[:char_start]
            if group[-1] is aligned[-1]:
                events[-1]["literal_suffix"] = literal[char_end:]
            previous_char_end = char_end
            if any(word["source_start"]<st or word["source_end"]>en for word in group):
                diagnostics.append({"segment_id": sid,"code": "clipped_word_boundary_requires_human_review",
                                    "word_ids": [word["word_id"] for word in group],"needs_human_review": True})
    events.sort(key=lambda event:(event["start"],event["end"]))
    for index,event in enumerate(events,1):
        event["event_id"] = f"CAPTION_{index:05d}"
    for previous,current in zip(events,events[1:]):
        if current["start"] < previous["end"]-1e-7:
            diagnostics.append({"code":"overlapping_caption_intervals","event_ids":[previous["event_id"],current["event_id"]],
                                "needs_human_review":True,"blocks_render":True})
    if not events:
        diagnostics.append({"code":"missing_caption_evidence","needs_human_review":True,"blocks_render":True})
    return events,segment_rows,diagnostics


def _validate_frozen_timeline(frozen,reference,selected,st,en,segments,global_words):
    if not isinstance(frozen,dict) or frozen.get("engine_version") not in {"5.2.2",ENGINE_VERSION}:
        raise ValueError("Frozen subtitle timeline engine version mismatch")
    if frozen.get("source_start")!=st or frozen.get("source_end")!=en:
        raise ValueError("Frozen subtitle timeline source range mismatch")
    if frozen.get("transcript_reference")!=reference or resolve_subtitle_preset(frozen.get("preset") or {})!=selected:
        raise ValueError("Frozen subtitle transcript or preset mismatch")
    events = frozen.get("events")
    if not isinstance(events,list) or canonical_timeline_hash(events)!=frozen.get("canonical_timeline_sha256"):
        raise ValueError("Frozen canonical subtitle timeline hash mismatch")
    by_segment={}
    expected=[]
    fallback_counts={}
    flattened=[]
    for index,original in enumerate(segments,1):
        segment=dict(original,start=float(original["start"]),end=float(original["end"]))
        sid=str(segment.get("segment_id") or segment.get("id") or f"segment_{index}")
        if not str(segment.get("text") or segment.get("literal_text") or "").strip():
            continue
        if sid in by_segment:
            raise ValueError("Duplicate source segment IDs")
        aligned,reason=_align_words(segment,global_words)
        visible=[word for word in aligned if word["source_end"]>st and word["source_start"]<en]
        raw_ids=[str(word.get("word_id") or word.get("id")) for word in _raw_words(segment,global_words)
                 if isinstance(word,dict) and (word.get("word_id") or word.get("id"))]
        by_segment[sid]=(segment,visible,reason,raw_ids)
        if reason:
            fallback_counts[sid]=0
        expected.extend(word["word_id"] for word in visible) if not reason else expected.extend(raw_ids)
    previous,seen = -1,set()
    for event in events:
        a,b = _finite(event.get("start"),"event.start"),_finite(event.get("end"),"event.end")
        sa,sb = _finite(event.get("source_start"),"event.source_start"),_finite(event.get("source_end"),"event.source_end")
        if not (0<=a<b<=en-st+1e-7 and sa<sb and a>=previous-1e-7 and
                abs(a-(max(st,sa)-st))<1e-7 and abs(b-(min(en,sb)-st))<1e-7):
            raise ValueError("Invalid frozen caption interval")
        ids = event.get("word_ids") or []
        if len(ids)!=len(set(ids)) or seen.intersection(ids):
            raise ValueError("Duplicate frozen caption word IDs")
        sid=event.get("segment_id")
        if sid not in by_segment:
            raise ValueError("Frozen caption references unknown segment")
        segment,visible,reason,raw_ids=by_segment[sid]
        literal=str(segment.get("text") or segment.get("literal_text") or "")
        if event.get("method")=="word":
            if reason or not ids:
                raise ValueError("Frozen caption lacks word timing evidence")
            source_map={word["word_id"]:word for word in visible}
            if any(wid not in source_map for wid in ids):
                raise ValueError("Frozen caption references unknown word")
            group=[source_map[wid] for wid in ids]
            positions=[visible.index(word) for word in group]
            if positions!=list(range(positions[0],positions[0]+len(group))):
                raise ValueError("Frozen caption word order mismatch")
            if selected["reveal_mode"]=="word" and len(group)!=1:
                raise ValueError("Frozen caption reveals unspoken words")
            phrase=literal[group[0]["char_start"]:group[-1]["char_end"]]
            if event.get("literal_text")!=phrase or sa!=group[0]["source_start"] or sb!=group[-1]["source_end"]:
                raise ValueError("Frozen caption text or timing differs from word evidence")
            first_offset,last_offset=group[0]["char_start"],group[-1]["char_end"]
            original_matches=list(re.finditer(r"\S+",literal))
            prefix_start=visible[positions[0]-1]["char_end"] if positions[0] else first_offset
            if positions[0]==0 and first_offset==original_matches[0].start():
                prefix_start=0
            prefix=literal[prefix_start:first_offset]
            suffix=literal[last_offset:] if last_offset==original_matches[-1].end() else ""
            if event.get("literal_prefix")!=prefix or event.get("literal_suffix")!=suffix:
                raise ValueError("Frozen caption literal whitespace differs from transcript")
            spans=event.get("words") or []
            if len(spans)!=len(group) or any(span.get("word_id")!=word["word_id"] or
                span.get("source_start")!=word["source_start"] or span.get("source_end")!=word["source_end"] or
                span.get("text")!=word["text"] or span.get("char_start")!=word["char_start"]-group[0]["char_start"] or
                span.get("char_end")!=word["char_end"]-group[0]["char_start"] for span,word in zip(spans,group)):
                raise ValueError("Frozen caption span evidence mismatch")
        elif event.get("method")=="segment":
            if sid in fallback_counts:
                fallback_counts[sid]+=1
            if not reason or event.get("literal_text")!=literal or ids!=raw_ids or sa!=segment["start"] or sb!=segment["end"]:
                raise ValueError("Frozen caption fallback differs from segment evidence")
        else:
            raise ValueError("Invalid frozen caption alignment")
        seen.update(ids);flattened.extend(ids);previous=a
    if any(count!=1 for count in fallback_counts.values()):
        raise ValueError("Frozen caption fallback segment coverage mismatch")
    if flattened!=expected or seen!=set(expected) or len(seen)!=len(expected):
        raise ValueError("Frozen caption word coverage mismatch")
    return [{key:deepcopy(event.get(key)) for key in _CANONICAL_FIELDS} for event in events]


def _timed_block_body(event,layout,preset,keywords,st):
    """ASS color changes follow measured word windows inside one shared SRT cue."""
    literal = event["literal_text"]
    if preset["color_progression"] == "cumulative":
        # The Dialogue starts on the ASS centisecond grid. Use that actual
        # origin so rounding cannot anticipate even the block's first word.
        h,m,s = _ass_time(event["start"]).split(":")
        serialized_start = st+int(h)*3600+int(m)*60+float(s)
        return measured_karaoke_body(literal,event["words"],serialized_start,
            break_offsets=layout["visual_break_char_offsets"],initial_color=preset["highlight_color"],
            spoken_color=preset["color"],uppercase=preset["uppercase"])
    if not preset["word_highlight"]:
        return _styled_body(literal,[],set(),layout,preset,keywords)
    if len(event["words"])<=1:
        return _styled_body(literal,event["words"],set(event["word_ids"]),layout,preset,keywords)
    breaks = set(layout["visual_break_char_offsets"])
    spans = event["words"]
    edges = sorted({0,len(literal),*breaks,*[span[key] for span in spans for key in ("char_start","char_end")]})
    fragments=[]
    for left,right in zip(edges,edges[1:]):
        if left in breaks:
            fragments.append("\\N")
        span = next((word for word in spans if word["char_start"]<=left<word["char_end"]),None)
        fragments.append("{\\c"+_ass_color(preset["color"])+"}")
        if span and (preset["name"]!="LDP_PALAVRA_CHAVE" or _token(span["text"]) in keywords):
            begin = max(0,int(round((span["source_start"]-st-event["start"])*1000)))
            end = min(int(round((event["end"]-event["start"])*1000)),int(round((span["source_end"]-st-event["start"])*1000)))
            highlight = _ass_color(preset["highlight_color"])
            normal = _ass_color(preset["color"])
            if begin==0:
                fragments.append("{\\c"+highlight+"}")
            else:
                fragments.append(f"{{\\t({begin},{begin},\\c{highlight})}}")
            fragments.append(f"{{\\t({end},{end},\\c{normal})}}")
        text=literal[left:right]
        fragments.append(esc_ass(text.upper() if preset["uppercase"] else text))
    return "".join(fragments)


def write_episode_subtitles(evidence, episode, directory, preset="LDP_KARAOKE_POP", overrides=None,
                            width=540, height=960, canonical_timeline=None):
    """Serialize ASS/SRT from one frozen, literal word-evidence timeline.

    The selected profile controls phrase or word reveal. Word IDs and original
    timestamps remain immutable in both modes. Unaligned text remains a clearly
    identified segment fallback; unsafe fallback layout blocks video rendering.
    """
    st,en = _finite(episode.get("source_start"),"source_start"),_finite(episode.get("source_end"),"source_end")
    if st<0 or en<=st:
        raise ValueError("Invalid episode interval")
    if not isinstance(width,int) or not isinstance(height,int) or width<=0 or height<=0 or width*16!=height*9:
        raise ValueError("Caption resolution must be 9:16")
    selected = resolve_subtitle_preset(preset,overrides)
    segments = _get(evidence,"segments") or _get(evidence,"captions")
    segments = sorted((segment for segment in segments if _overlaps(segment,st,en)),key=lambda s:(float(s["start"]),float(s["end"])))
    global_words = _get(evidence,"words")
    reference = _transcript_reference(segments,global_words,episode,evidence)
    font_path,font_info = _font_resolution(selected["font"],selected["bold"])
    layouts={}
    def layout_for(text):
        if text not in layouts:
            layouts[text] = _caption_layout(text,selected,width,height,font_path,episode,evidence)
        return layouts[text]
    if canonical_timeline is None:
        events,segment_rows,diagnostics = _canonical_events(segments,global_words,st,en,selected,reference,layout_for)
    else:
        events = _validate_frozen_timeline(canonical_timeline,reference,selected,st,en,segments,global_words)
        segment_rows=deepcopy(canonical_timeline.get("segments") or [])
        diagnostics=deepcopy(canonical_timeline.get("diagnostics") or [])
    alignments=[row["alignment"] for row in segment_rows]
    metadata={"schema":"LDP_SUBTITLE_SYNC_V5.2_WORD_ALIGNED","engine_version":ENGINE_VERSION,
        "episode_id":episode.get("episode_id"),"source_start":st,"source_end":en,"duration":en-st,
        "preset":selected,"transcript_reference":reference,"literal_transcript_unchanged":True,
        "visual_case_transform":"uppercase" if selected["uppercase"] else "none",
        "time_precision":{"srt_seconds":.001,"ass_seconds":.01,"canonical":"unrounded_original_seconds",
                          "maximum_ass_rounding_error_seconds":.005,"maximum_srt_rounding_error_seconds":.0005,
                          "karaoke_color_seconds":.001,"karaoke_color_rounding":"ceil_from_serialized_ass_start"},
        "enabled":selected.get("enabled",True),"segments":segment_rows,"events":[],"diagnostics":diagnostics,
        "alignment":"word" if alignments and all(a=="word" for a in alignments) else "mixed" if "word" in alignments else "segment" if alignments else "missing",
        "font_resolution":font_info,"audio_review_status":"NEEDS_HUMAN_AUDIO_REVIEW",
        "audiovisual_sync_homologated":False,"renderable":not any(row.get("blocks_render") for row in diagnostics),
        "no_word_anticipation":bool(events) and selected["reveal_mode"]=="word" and all(event["method"]=="word" for event in events),
        "no_color_anticipation":bool(events) and selected["color_progression"]=="cumulative" and all(event["method"]=="word" for event in events),
        "visual_behavior":"yellow_phrase_cumulative_white_at_measured_onset" if selected["color_progression"]=="cumulative" else "legacy_word_or_window",
        "canonical_timeline_sha256":canonical_timeline_hash(events),"frozen_timeline_reused":canonical_timeline is not None}
    ass=[_header(selected,width,height,font_info["resolved_family"])];srt=[]
    keywords={_token(word) for word in selected["highlight_words"]}
    for index,base_event in enumerate(events,1):
        event=deepcopy(base_event);layout=layout_for(event["literal_text"])
        a,b=event["start"],event["end"]
        ass_precision_ok=_ass_time(a)!=_ass_time(b)
        srt_precision_ok=srt_time(a)!=srt_time(b)
        enabled=metadata["enabled"]
        rendered=enabled and layout["fits_safe_box"] and ass_precision_ok and not any(row.get("blocks_render") for row in diagnostics)
        if enabled and (not layout["fits_safe_box"] or not ass_precision_ok or not srt_precision_ok):
            metadata["renderable"]=False
            diagnostics.append({"segment_id":event["segment_id"],"event_id":event["event_id"],
                "code":"caption_overflow_requires_human_review" if not layout["fits_safe_box"] else "caption_below_format_time_resolution",
                "needs_human_review":True,"word_ids":event["word_ids"]})
        if layout["readable_minimum_applied"] and not any(row.get("code")=="readable_font_minimum_applied" for row in diagnostics):
            diagnostics.append({"code":"readable_font_minimum_applied","requested_font_size":layout["requested_font_size"],"rendered_font_size":layout["font_size"]})
        if rendered:
            body=_timed_block_body(event,layout,selected,keywords,st)
            prefix=f"{{\\an2\\q2\\pos({layout['x']:.2f},{layout['y']:.2f})\\fs{layout['ass_font_size']:.2f}}}"
            # Fade-in would hide the beginning of a short measured word.
            if selected["animation"]=="fade" and selected["reveal_mode"]=="block" and selected["color_progression"]!="cumulative":
                prefix+="{\\fad(60,60)}"
            ass.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Sub,,0,0,0,,{prefix}{body}\n")
        srt.append(f"{index}\n{srt_time(a)} --> {srt_time(b)}\n{event['literal_text']}\n\n")
        event.update(layout=deepcopy(layout),ass_event_written=rendered,srt_event_written=srt_precision_ok,
                     active_word_ids=event["word_ids"] if selected["word_highlight"] and event["method"]=="word" and len(event["word_ids"])==1 else [])
        if selected["color_progression"]=="cumulative":
            h,m,s=_ass_time(a).split(":")
            ass_start=int(h)*3600+int(m)*60+float(s)
            event["color_transitions"]=[{
                "word_id":word["word_id"],"source_start":word["source_start"],
                "ass_offset_ms":max(0,math.ceil((word["source_start"]-st-ass_start)*1000-1e-7)),
                "from_color":selected["highlight_color"],"to_color":selected["color"],
                "persists_until_block_end":True} for word in event["words"]]
        metadata["events"].append(event)
    metadata["needs_human_review"]=any(row.get("needs_human_review") for row in diagnostics)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    paths={"ass":directory/"CAPTIONS.ass","srt":directory/"CAPTIONS.srt","sync_metadata":directory/"SUBTITLE_SYNC.json"}
    paths["ass"].write_text("".join(ass),encoding="utf-8-sig")
    paths["srt"].write_text("".join(srt),encoding="utf-8")
    paths["sync_metadata"].write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    return {**{key:str(path) for key,path in paths.items()},"sync":metadata,"preset":selected}
