"""Small, traceable editorial drafts without a model or invented facts.

Short complete utterances keep every word. Longer utterances can supply neutral
topic headings, never shortened factual assertions. Their complete literal
support remains separate from the proposed cover wording.
"""
from __future__ import annotations

from copy import deepcopy
import re


DRAFT_STATUS = "DRAFT_REQUIRES_HUMAN_REVIEW"
_UNCERTAIN = re.compile(
    r"\b(não|nunca|jamais|nem|sem|supost[oa]s?|alegad[oa]s?|talvez|"
    r"poss[ií]vel|possivelmente|poderia|hip[oó]tese|se|apenas|somente|"
    r"segundo|exceto|por[eé]m|mas|ainda|quase|menos|mais|cerca)\b", re.I)
_TOPICS = (
    "ordem", "sequência", "revisão", "legendas", "prévia", "mapa", "história",
    "câmera", "episódios", "voo", "piloto", "rota", "motor", "tempestade",
    "decisão", "risco", "investigação", "segurança", "pergunta", "resposta",
    "carreira", "música", "artista", "caixas", "continuidade", "transcrição",
)
_TOPIC_RE = re.compile(
    r"\b(" + "|".join(_TOPICS) + r")(?:\s+(?:da|do|das|dos|de)\s+"
    r"[\wÀ-ÿ]+){0,2}\b", re.I)
_ROLE_NAMES = {
    "opening_context": {"opening_context", "opening", "context", "setup", "abertura", "contexto"},
    "development": {"development", "desenvolvimento"},
    "tension_question": {"tension_question", "tension", "question", "conflict", "tensão", "questão", "pergunta"},
    "response_consequence": {"response_consequence", "answer", "response", "consequence", "resposta", "consequência"},
    "closure": {"closure", "ending", "encerramento"},
    "possible_link": {"possible_link", "continuation", "bridge", "ligação", "continuação"},
}


def _normal(text):
    return " ".join(str(text or "").split())


def _inside(episode, row):
    try:
        return float(row["start"]) >= float(episode["source_start"]) and float(row["end"]) <= float(episode["source_end"])
    except (KeyError, TypeError, ValueError):
        return False


def _observed_scene(scene):
    # Scene presence alone does not prove that its description was observed.
    return (scene.get("description_method") == "authored_fixture_slide"
            or scene.get("visual_observation_status") in {"confirmed", "verified", "observed"}
            or scene.get("description_status") in {"confirmed", "verified"})


def build_editorial_copy(episode, segments, scenes=(), max_alternatives=3):
    """Return 0–3 distinct short drafts, each with complete source support.

    A whole short utterance can become an explicitly framed ``Relato`` or
    ``Pergunta``. Topic headings identify subjects, without claiming a truncated
    sentence happened. Negation, uncertainty, quantities and qualifications
    disable topic extraction. Overlong assertions remain in literal evidence.
    """
    if isinstance(max_alternatives, bool) or not isinstance(max_alternatives, int) or not 1 <= max_alternatives <= 3:
        raise ValueError("Quantidade de alternativas deve estar entre 1 e 3")
    selected = set(episode.get("segment_ids") or [])
    rows = [row for row in segments if isinstance(row, dict)
            and row.get("segment_id") in selected and _inside(episode, row)]
    scene_ids = set(episode.get("scene_ids") or [])
    alternatives, seen = [], set()

    def add(text, row, component, rationale, extra_risks=(), semantic_key=None):
        text = _normal(text).strip(" .!?")
        if not 2 <= len(text.split()) <= 7 or len(text) > 88:
            return
        key = (semantic_key or text).casefold()
        if key in seen or len(alternatives) >= max_alternatives:
            return
        seen.add(key)
        identifier = row.get("segment_id" if component == "segments" else "scene_id")
        literal = row.get("text") if component == "segments" else row.get("visual_description")
        risks = ["editorial_wording_not_original_quote", "context_requires_human_review", *extra_risks]
        if row.get("uncertain") or row.get("needs_review") or (
                isinstance(row.get("confidence"), (float, int)) and row["confidence"] < .5):
            risks.append("source_uncertainty")
        if row.get("synthetic") or row.get("description_method") == "authored_fixture_slide":
            risks.append("synthetic_fixture_not_real_homologation")
        refs = {"segment_ids": [identifier] if component == "segments" else [],
                "scene_ids": [identifier] if component == "scenes" else []}
        alternatives.append({
            "text": text, "publish_title_draft": text, "cover_text": text.upper(),
            "hook_overlay": text, "kind": "editorial_draft", "status": DRAFT_STATUS,
            "style": "documental" if component == "scenes" else "impacto" if literal.rstrip().endswith("?") else "minimalista",
            "rationale": rationale, "risks": list(dict.fromkeys(risks)), **refs,
            "evidence_refs": [{"component": component, "id": identifier}],
            "literal_support": [{"component": component, "id": identifier,
                                 "text": literal, "start": row.get("start"), "end": row.get("end"),
                                 "audio_verification": "not_measured" if component == "segments" else "not_applicable"}],
            "human_approved": False,
        })

    for row in rows:
        text = _normal(row.get("text"))
        count = len(text.split())
        complete = row.get("sentence_complete", row.get("is_sentence_end"))
        if complete is False or not re.search(r"[.!?][\"'”’)]*$", text) or text.endswith(("...", "…")):
            continue
        if 2 <= count <= 7:
            base = text.rstrip(".!?")
            prefix = "Pergunta: " if text.endswith("?") else "Relato: "
            proposed = prefix + base if count <= 6 else base
            add(proposed, row, "segments", "Enquadramento editorial de uma fala curta inteira; nenhuma palavra factual foi removida.", semantic_key=base)
    for row in rows:
        text = _normal(row.get("text"))
        # A short frame cannot safely omit a number, date, negation or qualifier.
        if _UNCERTAIN.search(text) or re.search(r"\d", text) or row.get("uncertain") or row.get("needs_review"):
            continue
        for match in _TOPIC_RE.finditer(text):
            phrase = match.group(0)
            # A topic already covered by a complete short draft adds no new angle.
            if any(phrase.casefold() in option["literal_support"][0]["text"].casefold()
                   and "whole_utterance" not in option["risks"]
                   and option["rationale"].startswith("Enquadramento") for option in alternatives):
                continue
            proposed = phrase if len(phrase.split()) >= 2 else "Em foco: " + phrase
            add(proposed, row, "segments", "Título temático extraído de palavras presentes; não afirma um acontecimento nem substitui a fala literal.",
                ("topic_heading_requires_context",), semantic_key=phrase)
    for row in scenes:
        if not isinstance(row, dict) or row.get("scene_id") not in scene_ids or not _inside(episode, row) or not _observed_scene(row):
            continue
        description = _normal(row.get("visual_description"))
        if 2 <= len(description.split()) <= 7:
            add(description, row, "scenes", "Proposta baseada na descrição visual com método de observação declarado; confira o frame antes de publicar.",
                ("visual_description_requires_frame_review",), semantic_key=description.rstrip(".!?"))
    insufficient = len(alternatives) < 3
    return {"schema_version": "5.2.0", "status": DRAFT_STATUS, "alternatives": alternatives,
            "requested_alternatives": 3, "available_alternatives": len(alternatives),
            "insufficient_evidence": insufficient,
            "insufficiency_reason": "Evidência insuficiente para três propostas curtas distintas; qualificações e falas longas foram preservadas."
            if insufficient else None,
            "literal_support_policy": "full_available_segment_or_observed_scene_separate_from_editorial_wording",
            "unavailable_segment_ids": sorted(selected - {row["segment_id"] for row in rows})}


def build_narrative_roles(episode, chapters=(), story_arcs=(), qa=()):
    """Describe only narrative roles explicitly supplied by source evidence.

    Shared timestamps/chapters cannot prove a resolution or semantic continuity.
    Even a confirmed answer relation does not independently verify a payoff.
    """
    ids = set(episode.get("segment_ids") or [])
    result = {name: {"status": "unverified", "evidence": [], "needs_review": True}
              for name in _ROLE_NAMES}

    def add(role, row, component, refs, explicit_status=None, label=None):
        refs = list(dict.fromkeys(refs or []))
        present = sorted(ids & set(refs))
        if not present:
            return
        verified = (explicit_status or row.get("support_status") or row.get("status")) in {"supported", "confirmed", "verified"}
        supported = verified and set(refs) <= ids and not row.get("inference") and not row.get("needs_review")
        status = "supported" if supported else "partial"
        identifier = row.get({"chapters": "chapter_id", "story_arcs": "story_arc_id", "qa": "qa_id"}[component])
        entry = {"component": component, "id": identifier, "segment_ids": present,
                 "all_source_segment_ids": refs, "label": label,
                 "source_start": row.get("start"), "source_end": row.get("end"), "status": status}
        result[role]["evidence"].append(entry)
        result[role]["status"] = "supported" if any(e["status"] == "supported" for e in result[role]["evidence"]) else "partial"
        result[role]["needs_review"] = True

    for component, rows in (("chapters", chapters), ("story_arcs", story_arcs)):
        for row in rows:
            if not isinstance(row, dict):
                continue
            declared = row.get("narrative_roles") or {}
            if isinstance(declared, dict):
                for canonical, aliases in _ROLE_NAMES.items():
                    for alias in aliases:
                        value = declared.get(alias)
                        if not isinstance(value, dict):
                            continue
                        add(canonical, row, component, value.get("segment_ids") or value.get("evidence_segment_ids"), value.get("status"), value.get("text"))
            labels = row.get("roles") or [row.get("narrative_role") or row.get("role")]
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                for canonical, aliases in _ROLE_NAMES.items():
                    if label in aliases:
                        add(canonical, row, component, row.get("segment_ids") or row.get("evidence_segment_ids"), label=label)
    for row in qa:
        if not isinstance(row, dict):
            continue
        question = row.get("question") if isinstance(row.get("question"), dict) else {}
        answer = row.get("answer") if isinstance(row.get("answer"), dict) else {}
        add("tension_question", row, "qa", row.get("question_segment_ids") or question.get("segment_ids"), label="source_question_relation")
        add("response_consequence", row, "qa", row.get("answer_segment_ids") or answer.get("segment_ids"), label="source_answer_relation_not_payoff")
    result["response_consequence"]["payoff_independently_verified"] = False
    return deepcopy(result)


def confirmed_continuation(previous, following, story_arcs=()):
    """Accept an explicit confirmed source relation, never mere adjacency."""
    left, right = set(previous.get("segment_ids") or []), set(following.get("segment_ids") or [])
    if following["source_start"] < previous["source_end"]:
        return []
    evidence = []
    for arc in story_arcs:
        for pair in arc.get("continuation_pairs") or []:
            if (isinstance(pair, dict) and pair.get("status") in {"supported", "confirmed", "verified"}
                    and not pair.get("inference") and not pair.get("needs_review")
                    and pair.get("from_segment_id") in left and pair.get("to_segment_id") in right):
                evidence.append({"component": "story_arcs", "story_arc_id": arc.get("story_arc_id"),
                                 "from_segment_id": pair["from_segment_id"], "to_segment_id": pair["to_segment_id"],
                                 "status": "supported", "source_relation": deepcopy(pair)})
    return evidence
