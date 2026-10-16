"""Evidence-only V5.1 proposals, independent of official V4.4 decisions.

This deterministic planner conservatively preserves transcript sentences and
question/answer windows. It does not claim to understand an unverified payoff,
speaker identity, historical chronology, or visual interpretation.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
import hashlib
import json
import re

from .duration_presets import (DEFAULT_DURATION_PRESET, duration_metadata,
                               finite_seconds, get_preset, validate_window)
from .editorial_copy import (build_editorial_copy, build_narrative_roles,
                             confirmed_continuation)

SCHEMA_VERSION = "5.1.0"
METHODOLOGY = "evidence_semantic_boundaries_v1"
MODES = ("MOMENTOS_INDEPENDENTES", "SERIE_CRONOLOGICA", "MELHORES_MOMENTOS",
         "COMBINADO", "DOSSIER_ONLY")
_APPROVED_STATES = {"PREVIEW_APPROVED", "FINAL_RENDERED", "PUBLISH_READY"}
_COMMERCIAL = {"commercial", "advertisement", "advertising", "ad", "sponsor",
               "sponsored", "self_promotion", "autopromo", "publicidade",
               "commercial_content", "commercial_blocked", "advertisement_content",
               "sponsor_read", "merchandising", "commercial_promotion", "event_promotion"}


def _hash(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "segments", "candidates", "chapters", "questions_answers"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _interval(row):
    start = row.get("start", row.get("source_start", row.get("question_start")))
    end = row.get("end", row.get("source_end", row.get("answer_end")))
    if start is None or end is None:
        return None
    return finite_seconds(start, "start"), finite_seconds(end, "end")


def _overlaps(start, end, row):
    window = _interval(row)
    return window is not None and window[0] < end and window[1] > start


def _merged(windows):
    out = []
    for start, end in sorted(windows):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def _union(windows):
    return sum(end - start for start, end in _merged(windows))


def _intersection(left, right):
    a, b, i, j, out = _merged(left), _merged(right), 0, 0, []
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            out.append((start, end))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _is_commercial(row):
    if row.get("commercial_blocked") is True or row.get("is_commercial") is True:
        return True
    classification = row.get("commercial_classification") or {}
    if isinstance(classification, dict) and classification.get("eligibility") == "excluded":
        return True
    for key in ("content_type", "classification", "commercial_classification", "type"):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("classification") or value.get("label") or value.get("status")
        if isinstance(value, str) and value.lower() in _COMMERCIAL:
            return True
    return False


def _sentence_end(row):
    explicit = row.get("sentence_complete", row.get("is_sentence_end"))
    if explicit is not None:
        return explicit is True
    text = row.get("text", "").rstrip().rstrip('"\'”’)]}')
    return bool(re.search(r"[.!?]$", text)) and not text.endswith(("...", "…"))


def _prepare(evidence):
    source = deepcopy(evidence.get("source") or {})
    source_hash = source.get("sha256") or (evidence.get("provenance") or {}).get("source_sha256")
    if not isinstance(source_hash, str) or not source_hash.strip():
        raise ValueError("Hash de origem obrigatório para propostas rastreáveis")
    source["sha256"] = source_hash
    total = finite_seconds(source.get("duration"), "source.duration")
    if total <= 0:
        raise ValueError("A fonte deve ter duração positiva")
    normalized = {"source": source, "total": total, "warnings": []}
    availability = evidence.get("availability") or {}
    for component, id_key in (("segments", "segment_id"), ("words", "word_id"),
                              ("scenes", "scene_id"), ("timeline", "timeline_id"),
                              ("chapters", "chapter_id"), ("qa", "qa_id"),
                              ("candidates", "candidate_id"), ("story_arcs", "story_arc_id")):
        rows, seen = [], set()
        declaration = availability.get(component) or {}
        status = declaration.get("status") if isinstance(declaration, dict) else declaration
        if status in {"stale", "missing", "not_measured"}:
            normalized["warnings"].append(f"{component}: {status}; conteúdo preservado no inventário, sem uso factual")
            normalized[component] = []
            continue
        for item in _rows(evidence.get(component)):
            if not isinstance(item, dict):
                raise ValueError(f"Registro inválido em {component}")
            row = deepcopy(item)
            bounds = _interval(row)
            if bounds is None:
                if component in {"segments", "words", "candidates"}:
                    raise ValueError(f"Intervalo ausente em {component}")
                normalized["warnings"].append(f"{component}: registro sem intervalo verificável")
                continue
            if bounds[0] == bounds[1] and component in {"words", "timeline"}:
                if not 0 <= bounds[0] <= total:
                    raise ValueError(f"Evento pontual fora da fonte em {component}")
                normalized["warnings"].append(f"{component}: timestamp sem duração omitido dos limites semânticos")
                continue
            validate_window(*bounds, total)
            row["start"], row["end"] = bounds
            identifier = row.get(id_key)
            if identifier is None and component == "candidates":
                raise ValueError("Candidato sem candidate_id original")
            if identifier is None:
                identifier = "EVID_" + _hash(source_hash, component, row)[:20]
                row[id_key] = identifier
                row["id_origin"] = "derived_evidence_reference"
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError(f"IDs inválidos/duplicados em {component}")
            seen.add(identifier)
            rows.append(row)
        if rows != sorted(rows, key=lambda r: (r["start"], r["end"])):
            normalized["warnings"].append(f"{component}: ordem da fonte restabelecida pelos timestamps")
        normalized[component] = sorted(rows, key=lambda r: (r["start"], r["end"]))
    segment_ids = {s.get("segment_id") for s in _rows(evidence.get("segments")) if isinstance(s, dict)}
    for candidate in normalized["candidates"]:
        if not set(candidate.get("segment_ids", [])) <= segment_ids:
            raise ValueError("Candidato referencia segmentos não disponíveis")
    exclusions = []
    for component in ("excluded_intervals", "silences", "program_sections"):
        declaration = availability.get(component) or {}
        status = declaration.get("status") if isinstance(declaration, dict) else declaration
        if status in {"stale", "missing", "not_measured"}:
            continue
        for item in _rows(evidence.get(component)):
            if component == "program_sections" and not _is_commercial(item):
                continue
            bounds = _interval(item)
            if bounds is None:
                continue
            validate_window(*bounds, total)
            exclusions.append({**item, "start": bounds[0], "end": bounds[1],
                               "reason": item.get("reason") or ("silence_observed" if component == "silences"
                                                                 else "commercial_source_classification")})
    for component in ("segments", "timeline", "chapters", "candidates"):
        for row in normalized[component]:
            if _is_commercial(row):
                exclusions.append({"start": row["start"], "end": row["end"],
                                   "reason": "commercial_source_classification",
                                   "evidence_component": component,
                                   "evidence_id": row.get(component[:-1] + "_id")})
    normalized["exclusions"] = exclusions
    return normalized


def _units(data):
    """Make atomic units; no clock boundary cuts a sentence or known Q&A."""
    eligible, excluded = [], list(data["exclusions"])
    for segment in data["segments"]:
        if not isinstance(segment.get("text"), str) or not segment["text"].strip():
            continue
        conflicts = [r for r in data["exclusions"] if _overlaps(segment["start"], segment["end"], r)]
        if conflicts:
            # Never trim a partially blocked utterance into a publishable sentence.
            excluded.append({"start": segment["start"], "end": segment["end"],
                             "reason": "utterance_intersects_exclusion",
                             "segment_ids": [segment["segment_id"]]})
        else:
            eligible.append(segment)
    data["exclusions"] = excluded
    protected = [(q["start"], q["end"], q["qa_id"], False) for q in data["qa"]]
    # Adjacent questions are protected conservatively, without claiming an answer identity.
    for index, row in enumerate(eligible[:-1]):
        if row["text"].rstrip().endswith("?") and eligible[index + 1]["start"] - row["end"] <= 3:
            answer = eligible[index + 1]
            protected.append((row["start"], answer["end"], None, True))
    units, current = [], []
    for index, row in enumerate(eligible):
        if current:
            previous = current[-1]
            exclusion_between = any(r["start"] < row["start"] and r["end"] > previous["end"]
                                    for r in excluded)
            gap = row["start"] - previous["end"]
            protected_gap = any(a <= previous["end"] and b >= row["end"] for a, b, _, _ in protected)
            if exclusion_between or (gap > 3 and not protected_gap):
                units.append(_make_unit(current, protected, forced_gap=True))
                current = []
        current.append(row)
        next_start = eligible[index + 1]["start"] if index + 1 < len(eligible) else data["total"]
        # Overlapping speech and a protected Q&A crossing this boundary remain atomic.
        crosses = any(a <= row["end"] < b and b > next_start for a, b, _, _ in protected)
        overlap = next_start < max(s["end"] for s in current)
        if _sentence_end(row) and not crosses and not overlap:
            units.append(_make_unit(current, protected))
            current = []
    if current:
        units.append(_make_unit(current, protected))
    for index, unit in enumerate(units):
        unit["chapter_ids"] = [c["chapter_id"] for c in data["chapters"]
                               if _overlaps(unit["start"], unit["end"], c)]
        unit["topic_ids"] = list(dict.fromkeys(s["topic_id"] for s in unit["segments"]
                                              if s.get("topic_id")))
        unit["story_arc_ids"] = [a["story_arc_id"] for a in data["story_arcs"]
                                  if _overlaps(unit["start"], unit["end"], a)]
        previous_end = units[index - 1]["end"] if index else unit["start"]
        unit["barrier_before"] = any(r["start"] < unit["start"] and r["end"] > previous_end
                                      for r in excluded) if index else False
    return units


def _make_unit(segments, protected, forced_gap=False):
    start, end = min(s["start"] for s in segments), max(s["end"] for s in segments)
    qa = [p for p in protected if p[0] < end and p[1] > start]
    return {"start": start, "end": end, "segments": segments,
            "boundary_quality": "sentence_or_qa" if _sentence_end(segments[-1]) else "uncertain_asr_boundary",
            "forced_gap": forced_gap,
            "qa_ids": [p[2] for p in qa if p[2]],
            "qa_inferred": any(p[3] for p in qa),
            "qa_incomplete": any(p[0] < start or p[1] > end for p in qa)}


def _groups(units, preset):
    groups, current = [], []
    for unit in units:
        if current:
            previous = current[-1]
            chapter_change = (previous["chapter_ids"] != unit["chapter_ids"]
                              and bool(previous["chapter_ids"] or unit["chapter_ids"]))
            topic_change = (previous["topic_ids"] != unit["topic_ids"]
                            and bool(previous["topic_ids"] and unit["topic_ids"]))
            arc_change = (previous["story_arc_ids"] != unit["story_arc_ids"]
                          and bool(previous["story_arc_ids"] or unit["story_arc_ids"]))
            gap = unit["start"] - previous["end"] > 3
            duration = unit["end"] - current[0]["start"]
            exceeds = duration > preset.max_seconds if preset.max_inclusive else duration >= preset.max_seconds
            if chapter_change or topic_change or arc_change or gap or exceeds or unit["barrier_before"]:
                groups.append(current)
                current = []
        current.append(unit)
    if current:
        groups.append(current)
    # Balance a short tail using whole semantic units only. This avoids an
    # unnecessary 80s + 40s result when two complete 60s episodes are possible.
    for index in range(1, len(groups)):
        previous, current = groups[index - 1], groups[index]
        while len(previous) > 1 and current[-1]["end"] - current[0]["start"] < preset.min_seconds:
            transfer = previous[-1]
            same_chapter = transfer["chapter_ids"] == current[0]["chapter_ids"]
            same_topic = transfer["topic_ids"] == current[0]["topic_ids"]
            same_arc = transfer["story_arc_ids"] == current[0]["story_arc_ids"]
            duration_previous = previous[-2]["end"] - previous[0]["start"]
            duration_current = current[-1]["end"] - transfer["start"]
            if (not same_chapter or not same_topic or not same_arc or current[0]["barrier_before"]
                    or current[0]["start"] - transfer["end"] > 3
                    or not preset.contains(duration_previous) or not preset.contains(duration_current)):
                break
            current.insert(0, previous.pop())
    return groups


def _literal(row, maximum=95):
    text = row["text"].strip()
    if len(text) > maximum:
        stop = text.rfind(" ", 0, maximum + 1)
        text = text[:stop if stop > 0 else maximum]
    return {"text": text, "kind": "transcript_excerpt", "segment_ids": [row["segment_id"]],
            "source_start": row["start"], "source_end": row["end"],
            "support_status": "supported_by_transcript", "audio_verification": "not_measured"}


def _episode(group, data, preset, order, series_id):
    segments = list(dict((s["segment_id"], s) for unit in group for s in unit["segments"]).values())
    start, end = group[0]["start"], max(u["end"] for u in group)
    duration = validate_window(start, end, data["total"])
    support = [{"segment_id": s["segment_id"], "text": s["text"], "start": s["start"],
                "end": s["end"], "kind": "literal_transcript", "audio_verification": "not_measured"}
               for s in segments]
    titles, seen = [], set()
    choices = [segments[0], segments[-1], segments[len(segments) // 2]] + segments
    for row in choices:
        option = _literal(row)
        if option["text"] and option["text"] not in seen:
            titles.append(option)
            seen.add(option["text"])
        if len(titles) >= 5:
            break
    candidate_ids = [c["candidate_id"] for c in data["candidates"] if _overlaps(start, end, c)
                     and not _is_commercial(c)]
    word_ids = [w["word_id"] for w in data["words"] if start <= w["start"] and w["end"] <= end]
    scene_ids = [s["scene_id"] for s in data["scenes"] if _overlaps(start, end, s)]
    risk = ["payoff_unverified", "audio_not_homologated"]
    if any(u["boundary_quality"] == "uncertain_asr_boundary" for u in group):
        risk.append("uncertain_asr_boundary")
    if any(u["qa_inferred"] for u in group):
        risk.append("question_answer_link_inferred")
    if any(u["qa_incomplete"] for u in group):
        risk.append("question_answer_evidence_incomplete")
    if any(s.get("needs_review") or s.get("uncertain") or
           (isinstance(s.get("confidence"), (int, float)) and s["confidence"] < .5) for s in segments):
        risk.append("asr_uncertain")
    metadata = duration_metadata(preset.key, duration)
    if not metadata["duration_within_target"]:
        risk.append("duration_outside_target")
    reasons = "Limites de frases/Q&A comprovados; capítulos/tópicos disponíveis e ordem temporal da fonte."
    episode = {
        "episode_id": "PROP_" + _hash(data["source"]["sha256"], start, end, SCHEMA_VERSION, METHODOLOGY, series_id)[:24],
        "episode_id_origin": "derived_proposal_not_analyzer_candidate", "series_id": series_id,
        "internal_title": f"HISTORIA_{order:03d}" if series_id == "SERIE_01" else f"EXTRA_{order:03d}",
        "order": order, "story_order": order, "rank": order,
        "source_start": start, "source_end": end, "start": start, "end": end, "duration": duration,
        "segment_ids": [s["segment_id"] for s in segments], "word_ids": word_ids,
        "scene_ids": scene_ids, "candidate_ids": candidate_ids,
        "chapter_ids": list(dict.fromkeys(c for u in group for c in u["chapter_ids"])),
        "story_arc_ids": list(dict.fromkeys(a for u in group for a in u["story_arc_ids"])),
        "qa_ids": list(dict.fromkeys(q for u in group for q in u["qa_ids"])),
        "status": "REVIEW_REQUIRED", "needs_review": True, "human_approval": None,
        "official_render_decision": None, "title_text": titles[0]["text"] if titles else "",
        "title_options": titles, "title_kind": "transcript_excerpt", "cover_title": None,
        "publication_title": None, "hook_options": titles[:2], "hook": titles[0] if titles else None,
        "story_premise": {"status": "literal_excerpt_only", "evidence": support[:1]},
        "setup": {"status": "literal_excerpt_only", "evidence": support[:1]},
        "development": {"status": "literal_excerpt_only", "evidence": support[1:-1]},
        "payoff": {"status": "unknown", "evidence": [], "needs_human_review": True},
        "conflict": {"status": "unknown", "evidence": []},
        "open_loop": {"status": "unknown", "evidence": []},
        "bridge_from_previous": None, "teaser_next": None, "next_episode_teaser": None,
        "continuation_required": False, "carry_over_context": [],
        "original_excerpt_support": support, "transcript_literal": " ".join(s["text"] for s in segments),
        "editorial_rationale": reasons, "semantic_split_reason": reasons,
        "auto_duration_reason": reasons if preset.key == "auto_under_90" else None,
        "preferred_cut_boundaries": [{"time": start, "kind": "segment_start", "segment_id": segments[0]["segment_id"]},
                                    {"time": end, "kind": group[-1]["boundary_quality"], "segment_id": segments[-1]["segment_id"]}],
        "boundary_quality": group[-1]["boundary_quality"],
        "claims_to_verify": [{"claim": "Desfecho e contexto narrativo completo", "status": "unknown"}],
        "uncertainties": ["A ordem segue o relato na fonte; cronologia histórica não foi inferida.",
                          "Frase concluída não comprova desfecho narrativo."],
        "risk_flags": risk, "spoiler_risk": "not_measured",
        "viral_potential": {"status": "not_measured", "kind": "editorial_hypothesis", "score": None},
        "duration_alternatives": [{"action": a, "requires_human_review": True} for a in
                                  ("split_at_next_semantic_boundary", "change_duration_preset",
                                   "keep_outside_target_pending_human_decision", "discard")]
                                  if not metadata["duration_within_target"] else [],
        "camera_mode": "SOURCE_PRESERVE", "subtitle_preset": "LDP_KARAOKE_VERDE", **metadata,
    }
    copy = build_editorial_copy(episode, segments, data["scenes"])
    chosen = copy["alternatives"][0] if copy["alternatives"] else None
    episode.update({"editorial_copy": copy, "title_internal": episode["internal_title"],
                    "publish_title_draft": chosen["publish_title_draft"] if chosen else None,
                    "cover_text": chosen["cover_text"] if chosen else f"PARTE {order:02d}",
                    "hook_overlay": chosen["hook_overlay"] if chosen else None,
                    "episode_part_label": f"Parte {order:02d}",
                    "narrative_roles": build_narrative_roles(episode, data["chapters"], data["story_arcs"], data["qa"]),
                    "continuation_status": "unverified", "ending_label": "ending_unverified"})
    episode["thumbnail_title"] = episode["cover_text"]
    if copy["insufficient_evidence"]:
        episode["uncertainties"].append(copy["insufficiency_reason"])
    return episode


def _continuity(episodes, data=None):
    for previous, following in zip(episodes, episodes[1:]):
        related = bool(set(previous["chapter_ids"]) & set(following["chapter_ids"]))
        near = following["source_start"] - previous["source_end"] <= 3
        previous["continuation_required"] = related or near
        confirmed = confirmed_continuation(previous, following, (data or {}).get("story_arcs", []))
        if confirmed:
            previous["continuation_status"] = "supported"
            previous["ending_label"] = "continues_next"
            previous["continuation_evidence"] = confirmed
        else:
            previous["continuation_status"] = "partial" if related or near else "unverified"
            previous["ending_label"] = "continuity_needs_review" if related or near else "ending_unverified"
            previous["continuation_evidence"] = []
        if related or near:
            support = previous["original_excerpt_support"][-1:]
            following["carry_over_context"] = support
            following["bridge_from_previous"] = {"kind": "source_adjacency", "episode_id": previous["episode_id"],
                                                 "evidence": support, "semantic_relation": "needs_human_review"}
            previous["teaser_next"] = following["hook"]
            previous["next_episode_teaser"] = following["hook"]


def _independent(units, data, preset):
    groups = []
    if data["candidates"]:
        for candidate in data["candidates"]:
            if _is_commercial(candidate):
                continue
            selected = [u for u in units if _overlaps(u["start"], u["end"], candidate)]
            # A candidate window does not override semantic/exclusion boundaries.
            groups.extend(_groups(selected, preset))
    else:
        groups = _groups(units, preset)
    unique = {(g[0]["start"], max(u["end"] for u in g)): g for g in groups if g}
    episodes = [_episode(group, data, preset, index + 1, "EXTRAS_MELHORES_MOMENTOS")
                for index, group in enumerate(unique.values())]
    # Imported scores are evidence of an Analyzer ranking, never approval or a new score.
    by_id = {c["candidate_id"]: c for c in data["candidates"]}
    def rank(episode):
        scores = [by_id[c].get("editorial_score", by_id[c].get("score")) for c in episode["candidate_ids"]]
        scores = [s for s in scores if isinstance(s, (int, float)) and not isinstance(s, bool)]
        return (-max(scores) if scores else 0, episode["source_start"])
    episodes.sort(key=rank)
    for index, episode in enumerate(episodes):
        episode["order"] = episode["rank"] = index + 1
        episode["internal_title"] = f"EXTRA_{index + 1:03d}"
        episode["title_internal"] = episode["internal_title"]
        episode["episode_part_label"] = f"Parte {index + 1:02d}"
    return episodes


def _coverage(data, episodes):
    total = data["total"]
    speech = [(s["start"], s["end"]) for s in data["segments"] if s.get("text", "").strip()]
    used = [(e["source_start"], e["source_end"]) for e in episodes]
    covered = _union(used)
    covered_speech = _union(_intersection(speech, used))
    speech_total = _union(speech)
    points = {0., total}
    for rows in (data["segments"], data["exclusions"], episodes):
        for row in rows:
            points.update(_interval(row))
    points = sorted(points)
    blocks, gaps = [], []
    # Sweep indexes avoid rescanning the whole long transcript for every interval.
    starts = [s["start"] for s in data["segments"]]
    prefix_ends, max_end = [], 0.
    for segment in data["segments"]:
        max_end = max(max_end, segment["end"])
        prefix_ends.append(max_end)
    for start, end in zip(points, points[1:]):
        if end <= start:
            continue
        lo, hi = bisect_right(prefix_ends, start), bisect_left(starts, end)
        segments = [s for s in data["segments"][lo:hi] if s["end"] > start and s.get("text", "").strip()]
        exclusions = [r for r in data["exclusions"] if _overlaps(start, end, r)]
        covering = [e["episode_id"] for e in episodes if _overlaps(start, end, e)]
        kind = "excluded" if exclusions else "speech_evidence" if segments else "evidence_gap"
        reasons = list(dict.fromkeys(r["reason"] for r in exclusions))
        if not segments and not exclusions:
            reasons = ["no_transcript_evidence_silence_not_assumed"]
        elif segments and not covering and not exclusions:
            reasons = ["speech_not_selected"]
        block = {"start": start, "end": end, "duration": end - start, "kind": kind,
                 "segment_ids": [s["segment_id"] for s in segments], "episode_ids": covering,
                 "reasons": reasons,
                 "chapter_ids": [c["chapter_id"] for c in data["chapters"] if _overlaps(start, end, c)],
                 "qa_ids": [q["qa_id"] for q in data["qa"] if _overlaps(start, end, q)],
                 "story_arc_ids": [a["story_arc_id"] for a in data["story_arcs"] if _overlaps(start, end, a)],
                 "source_event_type": "question" if any(s["text"].rstrip().endswith("?") for s in segments) else kind}
        blocks.append(block)
        if not covering:
            gap = {"start": start, "end": end, "reason": reasons[0] if reasons else "not_selected", "kind": kind}
            if gaps and gaps[-1]["end"] == start and gaps[-1]["reason"] == gap["reason"]:
                gaps[-1]["end"] = end
            else:
                gaps.append(gap)
    return {"total_source_duration": total, "source_order": "narration_timestamps",
            "historical_event_order": "not_inferred", "blocks": blocks,
            "covered_time_seconds": covered, "covered_speech_seconds": covered_speech,
            "available_speech_seconds": speech_total,
            "coverage_pct_speech": min(100., 100 * covered_speech / speech_total) if speech_total else 0.,
            "coverage_pct_source": min(100., 100 * covered / total),
            "gaps": gaps, "excluded_intervals": data["exclusions"],
            "coverage_denominator": "available_transcript_intervals_not_assumed_complete",
            "series_episode_duration_sum": sum(e["duration"] for e in episodes)}


def plan_series(evidence, duration_preset=DEFAULT_DURATION_PRESET, mode="SERIE_CRONOLOGICA") -> dict:
    if mode not in MODES:
        raise ValueError(f"Modo de curadoria desconhecido: {mode}")
    preset, data = get_preset(duration_preset), _prepare(evidence)
    units = _units(data)
    primary = ([_episode(group, data, preset, index + 1, "SERIE_01")
                for index, group in enumerate(_groups(units, preset))]
               if mode in {"SERIE_CRONOLOGICA", "COMBINADO"} else [])
    _continuity(primary, data)
    extras = _independent(units, data, preset) if mode == "COMBINADO" else []
    if mode in {"MELHORES_MOMENTOS", "MOMENTOS_INDEPENDENTES"}:
        primary = _independent(units, data, preset)
    availability = deepcopy(evidence.get("availability") or {})
    transcript_availability = availability.get("segments") or availability.get("transcript_segments") or {}
    transcript_status = (transcript_availability.get("status", "unknown")
                         if isinstance(transcript_availability, dict) else transcript_availability)
    if transcript_status != "available":
        data["warnings"].append("Completude da transcrição não confirmada; cobertura usa apenas evidências disponíveis.")
    if not units:
        data["warnings"].append("Sem fala literal elegível: nenhum episódio foi inventado.")
    coverage = _coverage(data, primary)
    return {"schema_version": SCHEMA_VERSION, "methodology": METHODOLOGY,
            "plan_id": "PLAN_" + _hash(data["source"]["sha256"], preset.key, mode, [e["episode_id"] for e in primary])[:24],
            "source": data["source"], "source_sha256": data["source"]["sha256"],
            "provenance": deepcopy(evidence.get("provenance") or {}), "availability": availability,
            "mode": mode, "duration_preset": preset.key, "duration_label": preset.label,
            "status": "DRAFT" if mode == "DOSSIER_ONLY" else "REVIEW_REQUIRED",
            "episodes": primary, "extras": extras, "story_map": coverage, "coverage": deepcopy(coverage),
            "warnings": list(dict.fromkeys(data["warnings"])),
            "official_shortlist": deepcopy(evidence.get("shortlist") or []),
            "official_decisions_modified": False, "human_approval": None,
            "approval_required": True, "audit_trail": []}


def update_episode(plan, episode_id, evidence, *, confirm_invalidation=False, **changes):
    """Return a revised plan; approved episodes require explicit invalidation consent.

    Bounds remain exact manual choices with warnings if they cut words or Q&A.
    Revision always clears approval and rendered/preview measurements.
    """
    aliases = {"title_internal": "internal_title", "publish_title_draft": "publication_title",
               "cover_text": "thumbnail_title", "hook_overlay": "title_text"}
    changes = deepcopy(changes)
    for alias, legacy in aliases.items():
        if alias in changes:
            if legacy in changes and changes[alias] != changes[legacy]:
                raise ValueError(f"Campos {alias}/{legacy} devem conter o mesmo valor")
            changes[legacy] = changes.pop(alias)
    allowed = {"source_start", "source_end", "duration_preset", "title_text", "internal_title", "camera_mode",
               "subtitle_preset", "subtitle_style", "cover_title", "publication_title", "thumbnail_selection",
               "thumbnail_text", "thumbnail_title", "thumbnail_overrides", "camera_keyframes", "subtitle_overrides",
               "order", "layout", "watermark", "audio", "zoom", "title_enabled"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("Campos de edição desconhecidos: " + ", ".join(sorted(unknown)))
    revised = deepcopy(plan)
    collection = next((key for key in ("episodes", "extras")
                       if any(e["episode_id"] == episode_id for e in revised.get(key, []))), None)
    if collection is None:
        raise ValueError("Episódio não encontrado")
    index = next(i for i, e in enumerate(revised[collection]) if e["episode_id"] == episode_id)
    old = revised[collection][index]
    if (old.get("status") in _APPROVED_STATES or old.get("human_approval")) and not confirm_invalidation:
        raise ValueError("Alteração invalida aprovação; confirme explicitamente a invalidação")
    data = _prepare(evidence)
    if data["source"]["sha256"] != plan["source_sha256"]:
        raise ValueError("Plano e evidências pertencem a fontes diferentes")
    start = finite_seconds(changes.get("source_start", old["source_start"]), "source_start")
    end = finite_seconds(changes.get("source_end", old["source_end"]), "source_end")
    validate_window(start, end, data["total"])
    preset = get_preset(changes.get("duration_preset", old["duration_preset"]))
    units = [u for u in _units(data) if _overlaps(start, end, u)]
    if not units:
        raise ValueError("Intervalo sem transcrição literal elegível")
    if any(_overlaps(start, end, e) for e in data["exclusions"]):
        raise ValueError("Intervalo cruza conteúdo excluído/comercial")
    units = deepcopy(units)
    for unit in units:
        unit["segments"] = [s for s in unit["segments"] if _overlaps(start, end, s)]
        unit["start"] = min(s["start"] for s in unit["segments"])
        unit["end"] = max(s["end"] for s in unit["segments"])
    episode = _episode(units, data, preset, old["order"], old["series_id"])
    if episode["source_start"] != start or episode["source_end"] != end:
        episode["risk_flags"].append("manual_boundary_needs_review")
    episode.update({"source_start": float(start), "start": float(start), "source_end": float(end), "end": float(end),
                    "duration": end - start, **duration_metadata(preset.key, end - start)})
    for support in episode["original_excerpt_support"]:
        if support["start"] < start or support["end"] > end:
            support["excerpt_status"] = "partially_outside_manual_window"
            episode["risk_flags"].append("manual_boundary_cuts_transcript_segment")
    episode["episode_id"] = "PROP_" + _hash(plan["source_sha256"], start, end, SCHEMA_VERSION, METHODOLOGY, old["series_id"])[:24]
    crossing_words = [w["word_id"] for w in data["words"] if w["start"] < start < w["end"] or w["start"] < end < w["end"]]
    crossing_qa = [q["qa_id"] for q in data["qa"] if q["start"] < start < q["end"] or q["start"] < end < q["end"]]
    if crossing_words:
        episode["risk_flags"].append("manual_boundary_cuts_word")
        episode["uncertainties"].append("Limite manual cruza palavras: " + ", ".join(crossing_words))
    if crossing_qa:
        episode["risk_flags"].append("manual_boundary_cuts_question_answer")
    for key in allowed - {"source_start", "source_end", "duration_preset"}:
        if key in changes:
            episode[key] = deepcopy(changes[key])
        elif key in old:
            episode[key] = deepcopy(old[key])
    episode["title_internal"] = episode["internal_title"]
    if episode.get("publication_title"):
        episode["publish_title_draft"] = episode["publication_title"]
    episode["cover_text"] = episode.get("thumbnail_title") or episode["cover_text"]
    if "title_text" in changes:
        episode["hook_overlay"] = episode["title_text"]
    elif old.get("hook_overlay"):
        episode["hook_overlay"] = old["hook_overlay"]
    for key in ("split_origin", "merged_episode_ids", "merge_origin", "source_editor_settings", "source_camera_settings"):
        if key in old:
            episode[key] = deepcopy(old[key])
    title = episode.get("title_text", "")
    if not isinstance(title, str) or not any(title in s["text"] for s in episode["original_excerpt_support"]):
        episode["risk_flags"].append("title_unverified")
        episode["claims_to_verify"].append({"claim": title, "status": "unverified", "origin": "manual_edit"})
        episode["title_kind"] = "manual_unverified"
    episode["revision_of"] = episode_id
    episode["duration_override"] = True if "duration_preset" in changes else old.get("duration_override", False)
    episode["approval_history"] = deepcopy(old.get("approval_history", []))
    if old.get("human_approval"):
        episode["approval_history"].append({"approval": deepcopy(old["human_approval"]),
                                            "status": "stale", "reason": "episode_editorial_or_visual_change"})
    episode["artifact_history"] = deepcopy(old.get("artifact_history", []))
    for kind in ("preview", "final"):
        if old.get(kind):
            episode["artifact_history"].append({"kind": kind, "artifact": deepcopy(old[kind]),
                                                "status": "stale", "reason": "episode_editorial_or_visual_change"})
    episode["story_order"] = old["story_order"]
    episode["human_approval"] = None
    episode["status"] = "REVIEW_REQUIRED"
    episode["approval_invalidated"] = True
    episode["invalidation_reason"] = "episode_editorial_or_visual_change"
    revised[collection][index] = episode
    if "order" in changes:
        order = changes["order"]
        if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= len(revised[collection]):
            raise ValueError("Ordem deve corresponder à posição de um episódio")
        moved = revised[collection].pop(index)
        revised[collection].insert(order - 1, moved)
        for position, item in enumerate(revised[collection], 1):
            item["order"] = position
        revised["audit_trail"].append({"action": "manual_reorder", "episode_id": episode["episode_id"],
                                        "previous_order": index + 1, "requested_order": order,
                                        "source_timestamps_preserved": True})
        moved_approvals = [item for item in revised[collection]
                          if item["episode_id"] != episode["episode_id"]
                          and item.get("order") != next(previous["order"] for previous in plan[collection]
                                                       if previous["episode_id"] == item["episode_id"])
                          and (item.get("status") in _APPROVED_STATES or item.get("human_approval"))]
        if moved_approvals and not confirm_invalidation:
            raise ValueError("Reordenação invalida aprovações afetadas; confirme explicitamente a invalidação")
    _continuity(revised["episodes"], data)
    revised["story_map"] = _coverage(data, revised["episodes"])
    revised["coverage"] = deepcopy(revised["story_map"])
    revised["status"], revised["human_approval"] = "REVIEW_REQUIRED", None
    revised.setdefault("audit_trail", []).append({"action": "episode_revision", "episode_id_before": episode_id,
                                                  "episode_id_after": episode["episode_id"], "changes": deepcopy(changes),
                                                  "approval_invalidated": True})
    return revised


def reorder_episodes(plan, episode_ids, *, confirm_invalidation=False):
    """Manual editorial order retains timestamps and original story_order."""
    current = plan.get("episodes", [])
    ids = [e["episode_id"] for e in current]
    if len(episode_ids) != len(ids) or set(episode_ids) != set(ids):
        raise ValueError("Reordenação deve conter cada episódio exatamente uma vez")
    affected = [e for position, identifier in enumerate(episode_ids, 1)
                for e in current if e["episode_id"] == identifier and e["order"] != position]
    if any(e.get("status") in _APPROVED_STATES or e.get("human_approval") for e in affected) and not confirm_invalidation:
        raise ValueError("Reordenação invalida aprovações; confirme explicitamente a invalidação")
    revised, by_id = deepcopy(plan), {e["episode_id"]: deepcopy(e) for e in current}
    revised["episodes"] = [by_id[cid] for cid in episode_ids]
    for order, episode in enumerate(revised["episodes"], 1):
        if episode["order"] == order:
            continue
        episode["order"] = order
        if "title_internal" in episode:
            episode["title_internal"] = episode["internal_title"]
            episode["episode_part_label"] = f"Parte {order:02d}"
        if episode.get("human_approval"):
            episode.setdefault("approval_history", []).append({"approval": deepcopy(episode["human_approval"]),
                                                               "status": "stale", "reason": "manual_reorder"})
        original = next(e for e in current if e["episode_id"] == episode["episode_id"])
        _mark_split_stale(episode, original, "manual_reorder")
        episode["risk_flags"] = list(dict.fromkeys(episode["risk_flags"] + ["manual_reordering_needs_context_review"]))
    revised["status"], revised["human_approval"] = "REVIEW_REQUIRED", None
    revised.setdefault("audit_trail", []).append({"action": "manual_reorder", "source_order": ids,
                                                  "editorial_order": list(episode_ids), "approval_invalidated": True})
    return revised


def merge_episodes(plan, episode_ids, evidence, duration_preset=None, *, confirm_invalidation=False):
    """Merge adjacent proposals without silently adding excluded or absent time.

    Original proposal IDs and their evidence remain in the merge provenance.
    Later numbered covers are invalidated; earlier episodes remain untouched.
    """
    ids = list(episode_ids)
    if len(ids) < 2 or len(set(ids)) != len(ids):
        raise ValueError("Mescla requer ao menos dois episódios distintos")
    collection = next((key for key in ("episodes", "extras")
                       if set(ids) <= {e["episode_id"] for e in plan.get(key, [])}), None)
    if collection is None:
        raise ValueError("Mescla requer episódios do mesmo conjunto/série")
    rows = plan[collection]
    positions = sorted(i for i, episode in enumerate(rows) if episode["episode_id"] in ids)
    if positions != list(range(positions[0], positions[-1] + 1)):
        raise ValueError("Mescla requer episódios consecutivos; lacunas não podem ser ocultadas")
    selected = [rows[position] for position in positions]
    if len({e["series_id"] for e in selected}) != 1:
        raise ValueError("Mescla requer a mesma série")
    if any(e.get("status") == "REJECTED" or e.get("state") == "REJECTED" for e in selected):
        raise ValueError("Episódio rejeitado requer revisão antes de mesclar")
    for left, right in zip(selected, selected[1:]):
        if abs(right["source_start"] - left["source_end"]) > 0.000001:
            raise ValueError("Mescla exige intervalos contíguos na fonte, sem lacuna, sobreposição ou ordem invertida")
    data = _prepare(evidence)
    if data["source"]["sha256"] != plan["source_sha256"]:
        raise ValueError("Plano e evidências pertencem a fontes diferentes")
    start, end = selected[0]["source_start"], selected[-1]["source_end"]
    duration = validate_window(start, end, data["total"])
    if duration > 900:
        raise ValueError("Mescla excede o limite inclusivo de 900 segundos; mantenha partes separadas")
    units = [unit for unit in _units(data) if _overlaps(start, end, unit)]
    if not units or any(unit["start"] < start or unit["end"] > end for unit in units):
        raise ValueError("Mescla corta uma frase/Q&A; revise os limites semânticos")
    if any(_overlaps(start, end, row) for row in data["exclusions"]):
        raise ValueError("Mescla cruza intervalo excluído/comercial; original preservado")
    preset = get_preset(duration_preset or selected[0].get("duration_preset", plan["duration_preset"]))
    affected = rows[positions[0]:]
    if any(e.get("status") in _APPROVED_STATES or e.get("state") in _APPROVED_STATES
           or e.get("human_approval") or e.get("approval") for e in affected) and not confirm_invalidation:
        raise ValueError("Mescla/renumeração invalida aprovações afetadas; confirme explicitamente a invalidação")
    merged = _episode(units, data, preset, positions[0] + 1, selected[0]["series_id"])
    merged.update({"source_start": start, "start": start, "source_end": end, "end": end, "duration": duration,
                   **duration_metadata(preset.key, duration)})
    merged["episode_id"] = "PROP_" + _hash(plan["source_sha256"], start, end, SCHEMA_VERSION,
                                          METHODOLOGY, selected[0]["series_id"])[:24]
    if any(e["episode_id"] == merged["episode_id"] for e in rows if e["episode_id"] not in ids):
        raise ValueError("Mescla produziria uma proposta duplicada já existente")
    merged["merged_episode_ids"] = [e["episode_id"] for e in selected]
    merged["merge_origin"] = [{"episode_id": e["episode_id"], "source_start": e["source_start"],
                               "source_end": e["source_end"], "segment_ids": deepcopy(e["segment_ids"])}
                              for e in selected]
    merged["story_order"] = selected[0]["story_order"]
    merged["duration_override"] = duration_preset is not None or selected[0].get("duration_override", False)
    merged["source_editor_settings"] = []
    for original in selected:
        settings = {key: deepcopy(original[key]) for key in (
            "camera_mode", "camera_keyframes", "subtitle_preset", "subtitle_overrides", "thumbnail_overrides",
            "watermark", "audio", "title_enabled", "title_text", "thumbnail_title", "thumbnail_selection")
                    if key in original}
        merged["source_editor_settings"].append({"episode_id": original["episode_id"], "settings": settings})
    first_settings = merged["source_editor_settings"][0]["settings"]
    for key, value in first_settings.items():
        if key not in {"camera_keyframes", "thumbnail_selection", "title_text", "thumbnail_title"}:
            merged[key] = deepcopy(value)
    if any(e.get("camera_mode") == "MANUAL_KEYFRAMES" for e in selected):
        merged["camera_mode"], merged["camera_keyframes"] = "SOURCE_PRESERVE", []
        merged["risk_flags"].append("manual_camera_keyframes_require_remapping")
    if any(item["settings"] != first_settings for item in merged["source_editor_settings"][1:]):
        merged["risk_flags"].append("merged_editor_settings_need_review")
        merged["uncertainties"].append("Configurações diferentes nas partes originais; revise estilo e câmera da mescla.")
    _mark_split_stale(merged, selected[0], "episode_merge")
    for original in selected[1:]:
        approval = original.get("human_approval") or original.get("approval")
        if approval:
            merged["approval_history"].append({"approval": deepcopy(approval), "status": "stale", "reason": "episode_merge"})
        for kind in ("preview", "final"):
            if original.get(kind):
                merged["artifact_history"].append({"kind": kind, "artifact": deepcopy(original[kind]),
                                                   "status": "stale", "reason": "episode_merge"})
    revised = deepcopy(plan)
    revised[collection][positions[0]:positions[-1] + 1] = [merged]
    renumbered = []
    for position, episode in enumerate(revised[collection], 1):
        if episode["order"] != position:
            original = deepcopy(episode)
            episode["order"] = episode["rank"] = position
            prefix = "HISTORIA" if episode["series_id"] == "SERIE_01" else "EXTRA"
            episode["internal_title"] = f"{prefix}_{position:03d}"
            if "title_internal" in episode:
                episode["title_internal"] = episode["internal_title"]
                episode["episode_part_label"] = f"Parte {position:02d}"
            _mark_split_stale(episode, original, "episode_merge_renumbered_cover")
            renumbered.append(episode["episode_id"])
    _continuity(revised["episodes"], data)
    revised["story_map"] = _coverage(data, revised["episodes"])
    revised["coverage"] = deepcopy(revised["story_map"])
    revised["status"], revised["human_approval"] = "REVIEW_REQUIRED", None
    revised.setdefault("audit_trail", []).append({"action": "episode_merge", "episode_ids_before": ids,
                                                  "episode_id_after": merged["episode_id"],
                                                  "renumbered_episode_ids": renumbered,
                                                  "source_timestamps_preserved": True, "approval_invalidated": True,
                                                  "official_decisions_modified": False})
    return revised


def _mark_split_stale(episode, original, reason):
    """Keep old approval/artifact records without carrying an active render gate."""
    episode["approval_history"] = deepcopy(original.get("approval_history", []))
    approval = original.get("human_approval") or original.get("approval")
    if approval:
        episode["approval_history"].append({"approval": deepcopy(approval), "status": "stale", "reason": reason})
    episode["artifact_history"] = deepcopy(original.get("artifact_history", []))
    for kind in ("preview", "final"):
        if original.get(kind):
            episode["artifact_history"].append({"kind": kind, "artifact": deepcopy(original[kind]),
                                                "status": "stale", "reason": reason})
        episode.pop(kind, None)
    episode.pop("approval", None)
    episode["human_approval"] = None
    episode["status"] = episode["state"] = "REVIEW_REQUIRED"
    episode["needs_review"] = True
    episode["approval_invalidated"] = True
    episode["invalidation_reason"] = reason
    episode["preview_duration"] = episode["rendered_duration"] = None
    episode["duration_verified_by_ffprobe"] = False


def split_episode(plan, episode_id, evidence, duration_preset=None, *, confirm_invalidation=False):
    """Split one proposed interval at complete evidence-derived semantic units.

    This returns a new plan. Renumbered later episodes need new numbered covers;
    their approval is invalidated, while earlier/unaffected episodes stay intact.
    A unit exceeding the requested target remains whole with an explicit warning.
    """
    collection = next((key for key in ("episodes", "extras")
                       if any(e["episode_id"] == episode_id for e in plan.get(key, []))), None)
    if collection is None:
        raise ValueError("Episódio não encontrado")
    index = next(i for i, episode in enumerate(plan[collection]) if episode["episode_id"] == episode_id)
    original = plan[collection][index]
    data = _prepare(evidence)
    if data["source"]["sha256"] != plan["source_sha256"]:
        raise ValueError("Plano e evidências pertencem a fontes diferentes")
    start, end = original["source_start"], original["source_end"]
    validate_window(start, end, data["total"])
    preset = get_preset(duration_preset or original.get("duration_preset", plan["duration_preset"]))
    units = [u for u in _units(data) if _overlaps(start, end, u)]
    if not units:
        raise ValueError("Intervalo sem transcrição literal elegível para divisão")
    if any(u["start"] < start or u["end"] > end for u in units):
        raise ValueError("Limites atuais cortam uma frase/Q&A; ajuste aos limites semânticos antes de dividir")
    if any(_overlaps(start, end, row) for row in data["exclusions"]):
        raise ValueError("Intervalo cruza conteúdo excluído/comercial; revise os limites antes de dividir")
    if any(u["boundary_quality"] == "uncertain_asr_boundary" for u in units[:-1]):
        raise ValueError("Limite intermediário sem frase completa comprovada; revisão de ASR necessária")
    groups = _groups(units, preset)
    parts = [_episode(group, data, preset, index + offset + 1, original["series_id"])
             for offset, group in enumerate(groups)]
    # Retain optional silence margins already present in the reviewed source window.
    parts[0]["source_start"] = parts[0]["start"] = start
    parts[-1]["source_end"] = parts[-1]["end"] = end
    for part in parts:
        part["duration"] = validate_window(part["source_start"], part["source_end"], data["total"])
        part.update(duration_metadata(preset.key, part["duration"]))
        part["episode_id"] = "PROP_" + _hash(plan["source_sha256"], part["source_start"], part["source_end"],
                                            SCHEMA_VERSION, METHODOLOGY, original["series_id"])[:24]
    existing_ids = {e["episode_id"] for e in plan[collection] if e["episode_id"] != episode_id}
    if any(part["episode_id"] in existing_ids for part in parts):
        raise ValueError("A divisão produziria uma proposta duplicada já presente neste conjunto")
    affected = [original]
    if len(parts) > 1:
        affected.extend(plan[collection][index + 1:])
    if any(e.get("status") in _APPROVED_STATES or e.get("state") in _APPROVED_STATES
           or e.get("human_approval") or e.get("approval") for e in affected) and not confirm_invalidation:
        raise ValueError("Divisão/renumeração invalida aprovações afetadas; confirme explicitamente a invalidação")
    revised = deepcopy(plan)
    for offset, part in enumerate(parts, 1):
        part["revision_of"] = episode_id
        part["split_origin"] = {"episode_id": episode_id, "source_sha256": plan["source_sha256"],
                                "source_start": start, "source_end": end,
                                "story_order": original["story_order"], "part": offset, "parts": len(parts)}
        part["story_order"] = original["story_order"]
        part["duration_override"] = duration_preset is not None or original.get("duration_override", False)
        for key in ("camera_mode", "camera_keyframes", "subtitle_preset", "subtitle_overrides",
                    "thumbnail_overrides", "watermark", "audio", "title_enabled"):
            if key in original:
                part[key] = deepcopy(original[key])
        if len(parts) > 1 and original.get("camera_mode") == "MANUAL_KEYFRAMES":
            part["source_camera_settings"] = {"camera_mode": "MANUAL_KEYFRAMES",
                                              "camera_keyframes": deepcopy(original.get("camera_keyframes", [])),
                                              "source_start": start, "source_end": end,
                                              "status": "requires_remapping_for_split_window"}
            part["camera_mode"], part["camera_keyframes"] = "SOURCE_PRESERVE", []
            part["risk_flags"].append("manual_camera_keyframes_require_remapping")
            part["uncertainties"].append("Keyframes relativos à janela anterior precisam de revisão em cada parte; enquadramento original preservado.")
        _mark_split_stale(part, original, "semantic_split")
        if not part["duration_within_target"]:
            part["risk_flags"] = list(dict.fromkeys(part["risk_flags"] + ["duration_outside_target"]))
        if len(parts) == 1:
            part["risk_flags"].append("semantic_split_unavailable")
            part["uncertainties"].append("Nenhum limite semântico adicional permite a divisão; a unidade foi preservada integralmente.")
    _continuity(parts, data)
    parts[0]["bridge_from_previous"] = deepcopy(original.get("bridge_from_previous"))
    parts[0]["carry_over_context"] = deepcopy(original.get("carry_over_context", []))
    parts[-1]["teaser_next"] = deepcopy(original.get("teaser_next"))
    parts[-1]["next_episode_teaser"] = deepcopy(original.get("next_episode_teaser"))
    parts[-1]["continuation_required"] = original.get("continuation_required", False)
    revised[collection][index:index + 1] = parts
    renumbered = []
    for position, episode in enumerate(revised[collection], 1):
        if episode["order"] != position:
            previous = deepcopy(episode)
            episode["order"] = position
            episode["rank"] = position
            prefix = "HISTORIA" if episode["series_id"] == "SERIE_01" else "EXTRA"
            episode["internal_title"] = f"{prefix}_{position:03d}"
            if "title_internal" in episode:
                episode["title_internal"] = episode["internal_title"]
                episode["episode_part_label"] = f"Parte {position:02d}"
            _mark_split_stale(episode, previous, "semantic_split_renumbered_cover")
            renumbered.append(episode["episode_id"])
    revised["status"], revised["human_approval"] = "REVIEW_REQUIRED", None
    revised["story_map"] = _coverage(data, revised["episodes"])
    revised["coverage"] = deepcopy(revised["story_map"])
    if len(parts) == 1:
        revised.setdefault("warnings", []).append("Divisão não realizada: nenhum limite semântico adicional seguro; proposta integral mantida para revisão.")
    revised.setdefault("audit_trail", []).append({"action": "semantic_split", "episode_id_before": episode_id,
                                                  "episode_ids_after": [e["episode_id"] for e in parts],
                                                  "actual_split": len(parts) > 1, "requested_duration_preset": preset.key,
                                                  "source_sha256": plan["source_sha256"], "original_window": {"start": start, "end": end},
                                                  "renumbered_episode_ids": renumbered,
                                                  "approval_invalidated": True, "official_decisions_modified": False})
    return revised
