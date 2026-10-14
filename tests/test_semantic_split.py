from copy import deepcopy

import pytest

from ldporto_curator.series_planner import plan_series, split_episode


def evidence():
    return {"source": {"sha256": "HASH", "duration": 160, "video_id": "split-fixture"},
            "segments": [{"segment_id": f"S{i}", "start": i * 20, "end": (i + 1) * 20,
                          "text": f"Esta é a frase completa {i}."} for i in range(8)],
            "shortlist": [], "availability": {"segments": {"status": "available"}}}


def project():
    source = evidence()
    source["chapters"] = [{"chapter_id": "BEGIN", "start": 0, "end": 20},
                          {"chapter_id": "MID", "start": 20, "end": 100},
                          {"chapter_id": "END", "start": 100, "end": 160}]
    return source, plan_series(source)


def approved(episode):
    episode["status"] = "PREVIEW_APPROVED"
    episode["human_approval"] = {"preview_approved_by_human": True, "sha256": "old-preview"}
    episode["preview"] = {"project_path": "prior-preview.mp4"}


def test_semantic_split_has_dynamic_parts_and_preserves_source_provenance():
    source, plan = project()
    original = plan["episodes"][1]
    revised = split_episode(plan, original["episode_id"], source, "under_30")
    assert len(revised["episodes"]) == 6
    assert [e["order"] for e in revised["episodes"]] == list(range(1, 7))
    parts = revised["episodes"][1:5]
    assert [(e["source_start"], e["source_end"]) for e in parts] == [(20, 40), (40, 60), (60, 80), (80, 100)]
    assert all(e["duration_within_target"] and e["revision_of"] == original["episode_id"] for e in parts)
    assert all(e["split_origin"]["source_sha256"] == "HASH" for e in parts)
    assert all(e["split_origin"]["story_order"] == original["story_order"] for e in parts)
    assert revised["story_map"]["covered_time_seconds"] == plan["story_map"]["covered_time_seconds"]


def test_split_only_invalidates_selected_and_changed_number_approvals_with_consent():
    source, plan = project()
    for episode in plan["episodes"]:
        approved(episode)
    snapshot = deepcopy(plan)
    revised = split_episode(plan, plan["episodes"][1]["episode_id"], source, "under_30", confirm_invalidation=True)
    assert revised["episodes"][0] == snapshot["episodes"][0]
    assert all(e["status"] == "REVIEW_REQUIRED" and e["human_approval"] is None for e in revised["episodes"][1:])
    assert revised["episodes"][-1]["approval_history"][-1]["status"] == "stale"
    assert revised["episodes"][-1]["artifact_history"][-1]["artifact"]["project_path"] == "prior-preview.mp4"
    assert plan == snapshot


def test_later_approved_episode_blocks_split_without_consent_and_input_is_unchanged():
    source, plan = project()
    approved(plan["episodes"][-1])
    snapshot = deepcopy(plan)
    with pytest.raises(ValueError, match="confirme"):
        split_episode(plan, plan["episodes"][1]["episode_id"], source, "under_30")
    assert plan == snapshot


def test_oversized_atomic_sentence_is_not_artificially_split():
    source = evidence()
    source["segments"] = [{"segment_id": "LONG", "start": 0, "end": 160,
                           "text": "Uma explicação inteira sem limite intermediário comprovado."}]
    plan = plan_series(source)
    revised = split_episode(plan, plan["episodes"][0]["episode_id"], source, "under_30")
    assert len(revised["episodes"]) == 1
    assert revised["episodes"][0]["duration"] == 160
    assert not revised["episodes"][0]["duration_within_target"]
    assert "semantic_split_unavailable" in revised["episodes"][0]["risk_flags"]
    assert revised["audit_trail"][-1]["actual_split"] is False


def test_split_preserves_known_question_answer_unit():
    source = evidence()
    source["qa"] = [{"qa_id": "QA", "start": 20, "end": 100}]
    plan = plan_series(source)
    target = next(e for e in plan["episodes"] if "QA" in e["qa_ids"])
    revised = split_episode(plan, target["episode_id"], source, "under_30")
    qa_parts = [e for e in revised["episodes"] if "QA" in e["qa_ids"]]
    assert len(qa_parts) == 1
    assert qa_parts[0]["source_start"] <= 20 and qa_parts[0]["source_end"] >= 100
    assert not qa_parts[0]["duration_within_target"]


def test_manually_clipped_sentence_refuses_split_without_mutation():
    source, plan = project()
    target = plan["episodes"][1]
    target["source_start"] = target["start"] = 21
    snapshot = deepcopy(plan)
    with pytest.raises(ValueError, match="limites semânticos"):
        split_episode(plan, target["episode_id"], source, "under_30")
    assert plan == snapshot


def test_split_does_not_change_official_shortlist_or_fabricate_candidate_ids():
    source, plan = project()
    source["candidates"] = [{"candidate_id": "REAL", "start": 20, "end": 100, "segment_ids": ["S1", "S2", "S3", "S4"]}]
    source["shortlist"] = ["REAL"]
    plan = plan_series(source)
    revised = split_episode(plan, plan["episodes"][1]["episode_id"], source, "under_30")
    assert revised["official_shortlist"] == ["REAL"]
    assert revised["official_decisions_modified"] is False
    assert all(set(e["candidate_ids"]) <= {"REAL"} for e in revised["episodes"])


def test_split_rejects_other_source_hash_and_preserves_old_artifact_history():
    source, plan = project()
    target = plan["episodes"][1]
    approved(target)
    target["artifact_history"] = [{"kind": "preview", "artifact": {"project_path": "older.mp4"}, "status": "stale"}]
    wrong = deepcopy(source)
    wrong["source"]["sha256"] = "WRONG"
    with pytest.raises(ValueError, match="fontes diferentes"):
        split_episode(plan, target["episode_id"], wrong, "under_30", confirm_invalidation=True)
    revised = split_episode(plan, target["episode_id"], source, "under_30", confirm_invalidation=True)
    assert revised["episodes"][1]["artifact_history"][0]["artifact"]["project_path"] == "older.mp4"
    assert revised["episodes"][1]["approval_history"][-1]["approval"]["sha256"] == "old-preview"
