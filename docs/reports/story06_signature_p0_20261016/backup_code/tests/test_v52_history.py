"""Persistent editor history and selective human-gate invalidation, without ASR."""
from copy import deepcopy
import json
import shutil

import pytest

from ldporto_curator.approval import file_hash
from ldporto_curator.episode_approval import record_episode_preview, episode_approval_matches
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.utils import run


def make_project(tmp_path, *, count=6, preset="under_30", gap=0, **extra):
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"immutable synthetic source, not a real reviewed video")
    evidence = {
        "source": {"sha256": file_hash(media), "duration": count * (10 + gap),
                   "video_id": "v52_history", "width": 640, "height": 360, "fps": 30},
        "segments": [{"segment_id": f"S{i}", "start": i * (10 + gap),
                      "end": i * (10 + gap) + 10, "text": f"Frase literal {i}.",
                      "sentence_complete": True} for i in range(count)],
        "words": [], "scenes": [], "timeline": [], "chapters": [], "qa": [],
        "candidates": [], "shortlist": [],
        "availability": {"segments": {"status": "partial", "count": count}}, **extra,
    }
    project = SeriesProject.create(evidence, tmp_path / "out", duration_preset=preset)
    return project, media


def approve_fixture(project, identifier):
    """Exercise the gate with explicit synthetic fixture action, not real review."""
    episode = project.episode(identifier)
    signature = project.signature(episode)
    folder = project.folder(episode) / signature[:16] / "preview"
    folder.mkdir(parents=True, exist_ok=True)
    preview = folder / "PREVIEW_FIXTURE.mp4"
    preview.write_bytes(b"fixture preview gate, not measured media")
    record_episode_preview(folder, preview, signature, {"status": "validated"})
    episode["preview"] = {"project_path": preview.relative_to(project.directory).as_posix(),
                          "review_folder": folder.relative_to(project.directory).as_posix(),
                          "plan_hash": signature, "sha256": file_hash(preview)}
    episode["state"] = episode["status"] = "PREVIEW_READY"
    project.save()
    project.approve(identifier, human_reviewed=True)
    return folder, signature


def no_active_gate(episode):
    assert episode["status"] in {"REVIEW_REQUIRED", "REJECTED"}
    assert episode.get("human_approval") is None
    assert not any(episode.get(key) for key in ("preview", "final", "approval"))


def test_multiple_changes_undo_redo_resume_preserve_literal_refs(tmp_path):
    project, _ = make_project(tmp_path)
    original = deepcopy(project.episodes()[0])
    key = original["episode_id"]
    changed = project.edit(key, source_start=1, title_text="Título editorial revisável")
    new_key = changed["episode_id"]
    changed = project.edit(new_key, subtitle_preset="LDP_CLEAN", thumbnail_selection="CAPA_02")
    changed = project.edit(new_key, camera_mode="SOURCE_PRESERVE", watermark={"enabled": False})
    assert project.history_status()["commands"] == 3
    nonce = changed["revision_nonce"]
    project.undo()
    assert project.can_redo and project.can_undo
    assert project.episode(new_key)["revision_nonce"] != nonce
    assert "watermark" not in project.episode(new_key)
    project = SeriesProject(project.directory, project.cfg)
    project.undo()
    assert project.episode(new_key)["subtitle_preset"] == original["subtitle_preset"]
    project.undo()
    restored = project.episode(key)
    assert restored["source_start"] == 0
    assert restored["segment_ids"] == original["segment_ids"]
    assert restored["original_excerpt_support"] == original["original_excerpt_support"]
    assert restored["title_text"] == original["title_text"]
    no_active_gate(restored)
    assert not project.can_undo and project.can_redo
    for _ in range(3):
        project.redo()
    assert project.episode(new_key)["subtitle_preset"] == "LDP_CLEAN"
    assert project.episode(new_key)["thumbnail_selection"] == "CAPA_02"
    assert project.episode(new_key)["watermark"] == {"enabled": False}
    no_active_gate(project.episode(new_key))
    assert project.plan["official_shortlist"] == []
    assert project.plan["official_decisions_modified"] is False


def test_divergent_change_discards_redo_but_retains_branch_and_snapshots(tmp_path):
    project, _ = make_project(tmp_path)
    key = project.episodes()[0]["episode_id"]
    project.edit(key, thumbnail_selection="CAPA_02")
    project.edit(key, thumbnail_selection="CAPA_03")
    obsolete = deepcopy(project.plan["editing_history"]["entries"][-1])
    project.undo()
    project.edit(key, subtitle_preset="LDP_CLEAN")
    assert not project.can_redo and project.can_undo
    with pytest.raises(ValueError, match="refazer"):
        project.redo()
    branch = project.plan["editing_history"]["abandoned_branches"][-1]
    assert branch["entries"][-1] == obsolete
    for name in ("before", "after"):
        path = project.directory / obsolete[name]["project_path"]
        assert file_hash(path) == obsolete[name]["sha256"]
    assert not SeriesProject(project.directory).can_redo


def test_undo_does_not_restore_approval_or_old_signature_and_keeps_other_approval(tmp_path):
    project, media = make_project(tmp_path)
    edited_key, untouched_key = [e["episode_id"] for e in project.episodes()[:2]]
    old_folder, old_signature = approve_fixture(project, edited_key)
    project.edit(edited_key, title_text="Mudança", confirm_invalidation=True)
    approve_fixture(project, untouched_key)
    untouched = deepcopy(project.episode(untouched_key))
    project.undo()
    restored = project.episode(edited_key)
    no_active_gate(restored)
    assert project.episode(untouched_key) == untouched
    assert project.signature(restored) != old_signature
    assert not episode_approval_matches(old_folder, project.signature(restored))
    assert (old_folder / "PREVIEW_APPROVED_V5.json").is_file()
    assert restored["approval_history"] and restored["artifact_history"]
    with pytest.raises(ValueError, match="aprovação humana"):
        project.render(edited_key, media, preview=False)
    resumed = SeriesProject(project.directory, project.cfg)
    with pytest.raises(ValueError, match="aprovação humana"):
        resumed.render(edited_key, media, preview=False)
    current_nonce = restored["revision_nonce"]
    resumed.redo()
    assert resumed.episode(edited_key)["revision_nonce"] != current_nonce
    no_active_gate(resumed.episode(edited_key))
    assert resumed.episode(untouched_key) == untouched


def test_rejection_undo_needs_fresh_preview_and_retains_old_files(tmp_path):
    project, _ = make_project(tmp_path)
    key = project.episodes()[0]["episode_id"]
    folder, old_signature = approve_fixture(project, key)
    project.reject(key)
    assert project.episode(key)["status"] == "REJECTED"
    no_active_gate(project.episode(key))
    project.undo()
    assert project.episode(key)["status"] == "REVIEW_REQUIRED"
    no_active_gate(project.episode(key))
    assert project.signature(project.episode(key)) != old_signature
    assert (folder / "PREVIEW_FIXTURE.mp4").exists()
    project.redo()
    assert project.episode(key)["status"] == "REJECTED"


def test_reorder_invalidates_only_changed_numbered_covers(tmp_path):
    project, _ = make_project(tmp_path, count=8)
    keys = [e["episode_id"] for e in project.episodes()]
    approve_fixture(project, keys[-1])
    untouched = deepcopy(project.episode(keys[-1]))
    project.reorder([keys[1], keys[0], *keys[2:]])
    assert project.episode(keys[-1]) == untouched
    no_active_gate(project.episode(keys[0]))
    no_active_gate(project.episode(keys[1]))
    assert project.episode(keys[0])["source_start"] == 0
    project.undo()
    assert [e["episode_id"] for e in project.episodes()] == keys
    assert project.episode(keys[-1]) == untouched
    project.redo()
    assert [e["episode_id"] for e in project.episodes()] == [keys[1], keys[0], *keys[2:]]
    assert project.episode(keys[-1]) == untouched


def test_split_merge_history_restores_ids_and_requires_camera_review(tmp_path):
    project, _ = make_project(tmp_path, preset="auto_under_90")
    original = deepcopy(project.episodes()[0])
    key = original["episode_id"]
    project.edit(key, camera_mode="MANUAL_KEYFRAMES", camera_keyframes=[
        {"time": 0, "cx": 320, "cy": 180, "zoom": 1},
        {"time": 60, "cx": 320, "cy": 180, "zoom": 1},
    ])
    project.split(key, "under_30")
    keys = [e["episode_id"] for e in project.episodes()]
    assert len(keys) == 3 and all(e["camera_mode"] == "SOURCE_PRESERVE" for e in project.episodes())
    assert all(e["split_origin"]["episode_id"] == key for e in project.episodes())
    project.merge(keys[:2], confirm_invalidation=True)
    merged = project.episodes()[0]
    assert merged["merged_episode_ids"] == keys[:2]
    assert merged["source_start"] == 0 and merged["source_end"] == 40
    no_active_gate(merged)
    project.undo()
    assert [e["episode_id"] for e in project.episodes()] == keys
    project.undo()
    assert [e["episode_id"] for e in project.episodes()] == [key]
    assert project.episode(key)["camera_mode"] == "MANUAL_KEYFRAMES"
    project.redo()
    project.redo()
    assert project.episodes()[0]["merged_episode_ids"] == keys[:2]
    assert project.plan["story_map"]["covered_time_seconds"] == 60
    merged_key = project.episodes()[0]["episode_id"]
    project.edit(merged_key, subtitle_preset="LDP_CLEAN")
    assert project.episodes()[0]["merged_episode_ids"] == keys[:2]
    assert project.episodes()[0]["merge_origin"]


@pytest.mark.parametrize("kind", ["missing", "tampered", "external"])
def test_invalid_snapshot_does_not_change_cursor_or_plan(tmp_path, kind):
    project, _ = make_project(tmp_path)
    key = project.episodes()[0]["episode_id"]
    project.edit(key, title_text="Mudança")
    ref = project.plan["editing_history"]["entries"][-1]["before"]
    path = project.directory / ref["project_path"]
    if kind == "missing":
        path.rename(path.with_suffix(".missing.json"))
    elif kind == "tampered":
        path.write_text("{}", encoding="utf-8")
    else:
        ref["project_path"] = (tmp_path / "external.json").as_posix()
        (tmp_path / "external.json").write_text("{}", encoding="utf-8")
    before, persisted = deepcopy(project.plan), (project.directory / "series_index.json").read_bytes()
    with pytest.raises(ValueError, match="Snapshot|snapshot|SHA256"):
        project.undo()
    assert project.plan == before
    assert (project.directory / "series_index.json").read_bytes() == persisted


def test_save_failure_does_not_commit_command_or_memory(tmp_path, monkeypatch):
    project, _ = make_project(tmp_path)
    key = project.episodes()[0]["episode_id"]
    before, persisted = deepcopy(project.plan), (project.directory / "series_index.json").read_bytes()
    def fail_playlist():
        raise OSError("simulated disk failure before atomic index replace")
    monkeypatch.setattr(project, "_playlist", fail_playlist)
    with pytest.raises(OSError, match="simulated"):
        project.edit(key, title_text="Mudança")
    assert project.plan == before
    assert (project.directory / "series_index.json").read_bytes() == persisted
    assert not SeriesProject(project.directory).can_undo


@pytest.mark.parametrize("selection", ["one", "duplicate", "nonconsecutive", "mixed"])
def test_invalid_merge_is_atomic(tmp_path, selection):
    project, _ = make_project(tmp_path, count=8)
    keys = [e["episode_id"] for e in project.episodes()]
    ids = {"one": keys[:1], "duplicate": [keys[0], keys[0]],
           "nonconsecutive": [keys[0], keys[2]], "mixed": [keys[0], "missing"]}[selection]
    before = deepcopy(project.plan)
    with pytest.raises(ValueError):
        project.merge(ids)
    assert project.plan == before and not project.can_undo


def test_merge_blocks_small_excluded_gap_and_plain_evidence_gap(tmp_path):
    project, _ = make_project(tmp_path, count=4, gap=1,
                              excluded_intervals=[{"start": 10, "end": 11, "reason": "commercial"}])
    keys = [e["episode_id"] for e in project.episodes()]
    before = deepcopy(project.plan)
    with pytest.raises(ValueError, match="contíguos|excluído"):
        project.merge(keys[:2])
    assert project.plan == before


def test_no_action_undo_redo_and_stale_selection_have_clear_errors(tmp_path):
    project, _ = make_project(tmp_path)
    for action in (project.undo, project.redo):
        with pytest.raises(ValueError, match="Nenhuma ação"):
            action()
    with pytest.raises(ValueError, match="atualize a seleção"):
        project.edit("absent", title_text="Mudança")


def test_duplicate_window_proposal_does_not_mutate_history(tmp_path):
    project, _ = make_project(tmp_path)
    first, second = project.episodes()[:2]
    before = deepcopy(project.plan)
    with pytest.raises(ValueError, match="duplicada"):
        project.edit(first["episode_id"], source_start=second["source_start"], source_end=second["source_end"])
    assert project.plan == before and not project.can_undo


def test_order_edit_confirms_affected_other_approval(tmp_path):
    project, _ = make_project(tmp_path)
    first, second = project.episodes()[:2]
    approve_fixture(project, second["episode_id"])
    before = deepcopy(project.plan)
    with pytest.raises(ValueError, match="confirme"):
        project.edit(first["episode_id"], order=2)
    assert project.plan == before
    project.edit(first["episode_id"], order=2, confirm_invalidation=True)
    no_active_gate(project.episode(second["episode_id"]))


@pytest.mark.parametrize("duration,accepted", [(900, True), (910, False)])
def test_merge_900_seconds_inclusive_maximum(tmp_path, duration, accepted):
    project, _ = make_project(tmp_path, count=duration // 10, preset="from_300_to_600")
    keys = [e["episode_id"] for e in project.episodes()]
    if accepted:
        project.merge(keys, "from_600_to_900")
        assert project.episodes()[0]["duration"] == 900
        assert project.episodes()[0]["duration_within_target"]
    else:
        before = deepcopy(project.plan)
        with pytest.raises(ValueError, match="900 segundos"):
            project.merge(keys, "from_600_to_900")
        assert project.plan == before


def test_real_render_after_undo_uses_fresh_generation_and_fresh_human_gate(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe não instalado")
    media = tmp_path / "actual_synthetic_source.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(media)])
    evidence = {"source": {"sha256": file_hash(media), "video_id": "v52_fresh_generation",
                            "duration": 2., "width": 640, "height": 360, "fps": 30},
                "segments": [{"segment_id": "S0", "start": 0., "end": 2.,
                              "text": "Evidência sintética, sem revisão editorial real."}],
                "words": [], "scenes": [], "timeline": [], "candidates": [], "shortlist": [],
                "availability": {"segments": {"status": "partial", "count": 1}}}
    project = SeriesProject.create(evidence, tmp_path / "out", {"render": {"prefer_nvenc": False}})
    key = project.episodes()[0]["episode_id"]
    old_preview = project.render(key, media)
    old_hash = file_hash(old_preview)
    # Explicit test gate, not a claim of human/editorial homologation.
    project.approve(key, human_reviewed=True)
    project.edit(key, title_text="Edição temporária", confirm_invalidation=True)
    project.undo()
    with pytest.raises(ValueError, match="aprovação humana"):
        project.render(key, media, preview=False)
    project = SeriesProject(project.directory, project.cfg)
    fresh_preview = project.render(key, media)
    assert fresh_preview != old_preview
    assert file_hash(old_preview) == old_hash
    assert not (fresh_preview.parent / "PREVIEW_APPROVED_V5.json").exists()
    with pytest.raises(ValueError, match="aprovação humana"):
        project.render(key, media, preview=False)
    project.approve(key, human_reviewed=True)
    final = project.render(key, media, preview=False)
    assert final.is_file() and final.parent.parent == fresh_preview.parent.parent
    assert project.episode(key)["human_approval"]["publication_approved"] is False
