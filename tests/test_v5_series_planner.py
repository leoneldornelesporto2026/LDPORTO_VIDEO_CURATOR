import copy
import json
from pathlib import Path

import pytest

from ldporto_curator.duration_presets import (DURATION_PRESETS, duration_metadata,
                                              get_preset, validate_window)
from ldporto_curator.series_planner import plan_series, reorder_episodes, update_episode


def evidence(segments=None, duration=120, **extra):
    return {"source": {"sha256": "fixture-hash", "duration": duration, "video_id": "fixture"},
            "segments": segments if segments is not None else [
                {"segment_id": "S1", "start": 0, "end": 40, "text": "O mapa mostra a rota."},
                {"segment_id": "S2", "start": 40, "end": 80, "text": "A explicação continua."},
                {"segment_id": "S3", "start": 80, "end": 120, "text": "Esta é a conclusão relatada."}],
            "words": [], "scenes": [], "timeline": [], "chapters": [], "qa": [],
            "candidates": [], "shortlist": [], "availability": {"segments": {"status": "available"}}, **extra}


def test_eight_presets_keep_exact_labels_and_order():
    assert [p.label for p in DURATION_PRESETS] == ["Auto (<90s)", "<30s", "30s~59s", "60s~89s",
                                                 "90s~3m", "3m~5m", "5m~10m", "10m~15m"]
    assert sum(p.max_inclusive for p in DURATION_PRESETS) == 1
    assert get_preset().key == "auto_under_90"


@pytest.mark.parametrize("key,inside,outside", [
    ("under_30", 29.999, 30.), ("from_30_to_59", 59.999, 60.),
    ("from_60_to_89", 89.999, 90.), ("from_90_to_180", 179.999, 180.),
    ("from_180_to_300", 299.999, 300.), ("from_300_to_600", 599.999, 600.),
    ("from_600_to_900", 899.999, 900.001), ("auto_under_90", 89.999, 90.),
])
def test_continuous_duration_boundaries(key, inside, outside):
    assert get_preset(key).contains(inside)
    assert not get_preset(key).contains(outside)


@pytest.mark.parametrize("key,minimum", [("from_30_to_59", 30), ("from_60_to_89", 60),
                                        ("from_90_to_180", 90), ("from_180_to_300", 180),
                                        ("from_300_to_600", 300), ("from_600_to_900", 600)])
def test_inclusive_minimum(key, minimum):
    assert get_preset(key).contains(minimum)
    assert not get_preset(key).contains(minimum - .001)


def test_900_seconds_is_inclusive_without_rounding():
    assert duration_metadata("from_600_to_900", 900)["duration_within_target"]
    assert not duration_metadata("from_600_to_900", 900.001)["duration_within_target"]
    assert validate_window(.001, 900.001, 1000) == 900


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "30", None])
def test_duration_values_must_be_finite_numbers(value):
    with pytest.raises(ValueError):
        get_preset().contains(value)
    with pytest.raises(ValueError):
        validate_window(0, value, 120)


@pytest.mark.parametrize("start,end,total", [(0, 0, 10), (2, 1, 10), (-1, 2, 10), (0, 11, 10)])
def test_invalid_windows_rejected(start, end, total):
    with pytest.raises(ValueError):
        validate_window(start, end, total)


@pytest.mark.parametrize("mode", ["SERIE_CRONOLOGICA", "MELHORES_MOMENTOS", "MOMENTOS_INDEPENDENTES", "COMBINADO"])
def test_zero_shortlist_still_produces_review_only_proposals(mode):
    plan = plan_series(evidence(), mode=mode)
    assert plan["episodes"] and plan["official_shortlist"] == []
    assert plan["official_decisions_modified"] is False
    assert all(e["status"] == "REVIEW_REQUIRED" and e["human_approval"] is None for e in plan["episodes"])
    assert all(e["candidate_ids"] == [] for e in plan["episodes"])
    assert all(e["episode_id"].startswith("PROP_") for e in plan["episodes"])


def test_short_source_auto_is_not_padded():
    plan = plan_series(evidence([{"segment_id": "S1", "start": .1, "end": 8.8,
                                "text": "Uma fala curta e completa."}], duration=9))
    assert len(plan["episodes"]) == 1
    assert plan["episodes"][0]["duration"] == pytest.approx(8.7)
    assert plan["episodes"][0]["duration_within_target"]
    assert plan["episodes"][0]["auto_duration_reason"]


def test_semantic_unit_above_target_is_not_truncated():
    segments = [{"segment_id": "S1", "start": 0, "end": 70, "text": "Uma explicação que continua"},
                {"segment_id": "S2", "start": 70, "end": 110, "text": "e termina somente aqui."}]
    episode = plan_series(evidence(segments, duration=110))["episodes"][0]
    assert episode["source_end"] == 110 and episode["segment_ids"] == ["S1", "S2"]
    assert not episode["duration_within_target"]
    assert episode["duration_alternatives"] and "duration_outside_target" in episode["risk_flags"]


def test_too_short_for_long_preset_is_honest():
    plan = plan_series(evidence([{"segment_id": "S1", "start": 0, "end": 40, "text": "Um capítulo completo."}], 40),
                       "from_180_to_300")
    assert plan["episodes"][0]["duration"] == 40
    assert not plan["episodes"][0]["duration_within_target"]
    assert "menor que o mínimo" in plan["episodes"][0]["duration_deviation_reason"]


def test_short_tail_is_balanced_only_at_complete_semantic_boundaries():
    segments = [{"segment_id": f"S{i}", "start": i * 20, "end": (i + 1) * 20,
                 "text": f"Frase completa {i}."} for i in range(6)]
    plan = plan_series(evidence(segments), "from_60_to_89")
    assert [e["duration"] for e in plan["episodes"]] == [60, 60]
    assert all(e["duration_within_target"] for e in plan["episodes"])


def test_two_hour_source_has_dynamic_episode_count_and_auditable_sum():
    segments = [{"segment_id": f"S{i}", "start": i * 60, "end": (i + 1) * 60,
                 "text": f"Parte literal {i}."} for i in range(120)]
    plan = plan_series(evidence(segments, duration=7200))
    assert len(plan["episodes"]) == 120 > 12
    assert [e["order"] for e in plan["episodes"]] == list(range(1, 121))
    assert plan["story_map"]["covered_time_seconds"] == 7200
    assert plan["story_map"]["series_episode_duration_sum"] == 7200


@pytest.mark.parametrize("preset,duration", [("under_30", 20), ("from_30_to_59", 40),
                                            ("from_60_to_89", 80), ("from_90_to_180", 120),
                                            ("from_180_to_300", 240), ("from_300_to_600", 480),
                                            ("from_600_to_900", 900), ("auto_under_90", 20)])
def test_every_preset_reaches_its_target_without_padding(preset, duration):
    plan = plan_series(evidence([{"segment_id": "S1", "start": 0, "end": duration,
                                "text": "Uma unidade comprovada e completa."}], duration), preset)
    assert plan["episodes"][0]["duration"] == duration
    assert plan["episodes"][0]["duration_within_target"]


def test_question_and_answer_remain_together_across_pause_and_chapter():
    segments = [{"segment_id": "Q", "start": 0, "end": 20, "text": "Por que o piloto decidiu voltar?"},
                {"segment_id": "A", "start": 30, "end": 120, "text": "A explicação está relatada aqui."}]
    plan = plan_series(evidence(segments, qa=[{"qa_id": "QA1", "start": 0, "end": 120}],
                                chapters=[{"chapter_id": "C1", "start": 0, "end": 30},
                                          {"chapter_id": "C2", "start": 30, "end": 120}]))
    assert len(plan["episodes"]) == 1
    assert plan["episodes"][0]["segment_ids"] == ["Q", "A"]
    assert plan["episodes"][0]["qa_ids"] == ["QA1"]
    assert not plan["episodes"][0]["duration_within_target"]


def test_source_timestamp_order_does_not_claim_historical_order():
    source = evidence()
    source["segments"].reverse()
    plan = plan_series(source)
    assert plan["episodes"][0]["source_start"] == 0
    assert plan["story_map"]["historical_event_order"] == "not_inferred"
    assert any("ordem" in w for w in plan["warnings"])


def test_verified_chapter_topic_change_prevents_unrelated_padding():
    plan = plan_series(evidence(chapters=[{"chapter_id": "C1", "start": 0, "end": 40},
                                         {"chapter_id": "C2", "start": 40, "end": 120}]))
    assert plan["episodes"][0]["source_end"] == 40
    assert plan["episodes"][0]["chapter_ids"] == ["C1"]


def test_payoff_and_facts_are_never_invented_from_candidate_title():
    source = evidence(candidates=[{"candidate_id": "C1", "start": 0, "end": 120,
                                  "title": "Acidente causou 200 mortes", "segment_ids": ["S1", "S2", "S3"]}])
    plan = plan_series(source)
    assert all(e["payoff"]["status"] == "unknown" for e in plan["episodes"])
    assert "200 mortes" not in json.dumps(plan["episodes"], ensure_ascii=False)
    for episode in plan["episodes"]:
        for title in episode["title_options"]:
            assert any(title["text"] in s["text"] for s in episode["original_excerpt_support"])


def test_asr_uncertainty_and_partial_transcript_are_visible():
    source = evidence(availability={"segments": {"status": "partial"}})
    source["segments"][0]["confidence"] = .2
    plan = plan_series(source)
    assert "asr_uncertain" in plan["episodes"][0]["risk_flags"]
    assert any("Completude" in w for w in plan["warnings"])
    assert plan["story_map"]["coverage_denominator"] == "available_transcript_intervals_not_assumed_complete"


def test_story_map_partitions_entire_source_and_reports_gaps():
    source = evidence([{"segment_id": "S1", "start": 10, "end": 20, "text": "Primeira fala."},
                       {"segment_id": "S2", "start": 50, "end": 60, "text": "Segunda fala."}], duration=100)
    plan = plan_series(source)
    mapping = plan["story_map"]
    assert mapping["covered_time_seconds"] == 20
    assert mapping["coverage_pct_source"] == 20 and mapping["coverage_pct_speech"] == 100
    assert [(g["start"], g["end"]) for g in mapping["gaps"]] == [(0, 10), (20, 50), (60, 100)]
    assert sum(b["duration"] for b in mapping["blocks"]) == 100
    assert "silence_not_assumed" in mapping["gaps"][0]["reason"]


def test_commercial_excluded_even_when_partly_inside_utterance():
    source = evidence(timeline=[{"timeline_id": "AD", "start": 50, "end": 60,
                                 "content_type": "commercial_content"}])
    plan = plan_series(source)
    assert all("S2" not in e["segment_ids"] for e in plan["episodes"])
    assert any(x["reason"] == "utterance_intersects_exclusion" for x in plan["story_map"]["excluded_intervals"])
    assert plan["story_map"]["coverage_pct_speech"] == pytest.approx(100 * 80 / 120)


def test_short_commercial_gap_cannot_be_bridged_into_episode():
    source = evidence([{"segment_id": "S1", "start": 0, "end": 30, "text": "Primeira fala completa."},
                       {"segment_id": "S2", "start": 31, "end": 60, "text": "Segunda fala completa."}], duration=60,
                      excluded_intervals=[{"start": 30, "end": 31, "reason": "commercial_source_classification"}])
    plan = plan_series(source)
    assert len(plan["episodes"]) == 2
    assert all(not e["source_start"] < 30 < e["source_end"] for e in plan["episodes"])


@pytest.mark.parametrize("classification", [
    {"content_type": "sponsor_read"}, {"content_type": "merchandising"},
    {"content_type": "commercial_promotion"}, {"content_type": "event_promotion"},
    {"commercial_classification": {"eligibility": "excluded", "reason": "original_analyzer_rule"}},
])
def test_legacy_commercial_eligibility_contract_remains_excluded(classification):
    source = evidence(candidates=[{"candidate_id": "AD", "start": 40, "end": 80,
                                  "segment_ids": ["S2"], **classification}])
    plan = plan_series(source)
    assert all("S2" not in e["segment_ids"] and "AD" not in e["candidate_ids"] for e in plan["episodes"])
    assert plan["story_map"]["excluded_intervals"]


def test_stale_evidence_is_preserved_by_input_but_never_used_for_facts():
    source = evidence(availability={"segments": {"status": "stale"}})
    snapshot = copy.deepcopy(source)
    plan = plan_series(source)
    assert plan["episodes"] == [] and source == snapshot
    assert any("stale" in w for w in plan["warnings"])


def test_stale_qa_cannot_force_invented_continuity():
    source = evidence(qa=[{"qa_id": "WRONG", "start": 0, "end": 120}],
                      availability={"segments": {"status": "available"}, "qa": {"status": "stale"}})
    plan = plan_series(source)
    assert len(plan["episodes"]) == 2
    assert all(e["qa_ids"] == [] for e in plan["episodes"])


def test_zero_duration_word_alignment_is_omitted_without_fabricating_time():
    source = evidence(words=[{"word_id": "ZERO", "start": 1, "end": 1, "word": "O"}])
    plan = plan_series(source)
    assert "ZERO" not in plan["episodes"][0]["word_ids"]
    assert any("timestamp sem duração" in w for w in plan["warnings"])


def test_story_arc_change_uses_source_evidence_without_factual_title():
    plan = plan_series(evidence(story_arcs=[{"story_arc_id": "ARC1", "start": 0, "end": 40,
                                           "title": "Um fato que não foi comprovado"},
                                          {"story_arc_id": "ARC2", "start": 40, "end": 120}]))
    assert plan["episodes"][0]["source_end"] == 40
    assert plan["episodes"][0]["story_arc_ids"] == ["ARC1"]
    assert "não foi comprovado" not in plan["episodes"][0]["title_text"]


def test_no_transcript_produces_dossier_gaps_without_episodes():
    plan = plan_series(evidence([], duration=100))
    assert plan["episodes"] == []
    assert plan["story_map"]["covered_time_seconds"] == 0
    assert plan["story_map"]["gaps"][0]["end"] == 100
    dossier = plan_series(evidence(), mode="DOSSIER_ONLY")
    assert dossier["episodes"] == [] and dossier["extras"] == [] and dossier["status"] == "DRAFT"


def test_combined_extras_are_distinct_from_chronological_series():
    plan = plan_series(evidence(), mode="COMBINADO")
    assert plan["episodes"] and plan["extras"]
    assert all(e["series_id"] == "SERIE_01" for e in plan["episodes"])
    assert all(e["series_id"] == "EXTRAS_MELHORES_MOMENTOS" for e in plan["extras"])
    assert not set(e["episode_id"] for e in plan["episodes"]) & set(e["episode_id"] for e in plan["extras"])


def test_proposal_identity_is_deterministic_and_not_candidate_identity():
    first, second = plan_series(evidence()), plan_series(evidence())
    assert first == second
    changed = evidence()
    changed["source"]["sha256"] = "other-hash"
    assert first["episodes"][0]["episode_id"] != plan_series(changed)["episodes"][0]["episode_id"]


def test_duplicate_segment_ids_and_unresolved_candidates_rejected():
    source = evidence()
    source["segments"][1]["segment_id"] = "S1"
    with pytest.raises(ValueError):
        plan_series(source)
    with pytest.raises(ValueError):
        plan_series(evidence(candidates=[{"candidate_id": "C1", "start": 0, "end": 40, "segment_ids": ["ABSENT"]}]))


def test_changed_preset_requires_approval_invalidation_and_keeps_stale_record():
    source, plan = evidence(), plan_series(evidence())
    episode = plan["episodes"][0]
    episode["status"], episode["human_approval"] = "PREVIEW_APPROVED", {"hash": "old-preview"}
    with pytest.raises(ValueError, match="confirme"):
        update_episode(plan, episode["episode_id"], source, duration_preset="from_180_to_300")
    changed = update_episode(plan, episode["episode_id"], source, confirm_invalidation=True,
                             duration_preset="from_180_to_300")
    updated = changed["episodes"][0]
    assert updated["status"] == "REVIEW_REQUIRED" and updated["human_approval"] is None
    assert updated["approval_history"][-1]["approval"]["hash"] == "old-preview"
    assert updated["approval_history"][-1]["status"] == "stale"
    assert not updated["duration_within_target"]
    assert plan["episodes"][0]["status"] == "PREVIEW_APPROVED"


def test_manual_bounds_warn_about_words_and_title_support():
    source = evidence(words=[{"word_id": "W1", "start": 0, "end": 2, "word": "O"}])
    plan = plan_series(source)
    changed = update_episode(plan, plan["episodes"][0]["episode_id"], source,
                             source_start=1, title_text="Conclusão técnica inventada")
    episode = changed["episodes"][0]
    assert episode["source_start"] == 1 and "manual_boundary_cuts_word" in episode["risk_flags"]
    assert "title_unverified" in episode["risk_flags"]
    assert episode["status"] == "REVIEW_REQUIRED"
    assert episode["claims_to_verify"][-1]["status"] == "unverified"


def test_manual_order_preserves_source_timestamps_and_original_story_order():
    plan = plan_series(evidence())
    ids = [e["episode_id"] for e in plan["episodes"]]
    revised = reorder_episodes(plan, list(reversed(ids)))
    assert revised["episodes"][0]["source_start"] == plan["episodes"][-1]["source_start"]
    assert revised["episodes"][0]["story_order"] == 2
    assert revised["audit_trail"][-1]["source_order"] == ids
    assert revised["episodes"][0]["status"] == "REVIEW_REQUIRED"


def test_fixture_plan_can_serialize_finite_json_and_additive_schema():
    from ldporto_curator.analysis_loader import load_bundle
    root = Path(__file__).resolve().parents[1]
    bundle = load_bundle(root / "tests" / "fixture" / "video_87cfcb5f5347")
    source = {**bundle.analysis["metadata"], "video_id": bundle.video_id}
    plan = plan_series(evidence(bundle.segments, source["duration"], source=source,
                                words=bundle.words, scenes=bundle.scenes, timeline=bundle.timeline))
    json.dumps(plan, ensure_ascii=False, allow_nan=False)
    assert plan["story_map"]["total_source_duration"] == source["duration"]
    schema = json.loads((root / "schemas" / "series_plan_v5.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "5.1.0"
    assert plan["schema_version"] == "5.1.0"
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(schema).validate(plan)
