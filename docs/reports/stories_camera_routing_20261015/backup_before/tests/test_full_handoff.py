from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from ldporto_curator.evidence_source import load_evidence
from ldporto_curator.full_handoff import export_handoff, validate_handoff
from test_evidence_source import write_package, settled_dir


def draft_plan():
    return {"source_sha256": "SOURCE_HASH", "status": "DRAFT", "story_map": {"gaps": []},
        "episodes": [{"episode_id": "HISTORIA_001", "source_start": 5, "source_end": 25, "status": "REVIEW_REQUIRED", "candidate_ids": ["C1"], "title_options": ["Uma pergunta e sua resposta."]}]}


def test_manifest_and_all_available_literal_transcript_not_only_clip_context(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"), canonical_dir=settled_dir(tmp_path / "canonical"))
    package = export_handoff(evidence, draft_plan(), tmp_path / "handoff")
    manifest = validate_handoff(package)
    assert manifest["source_sha256"] == "SOURCE_HASH"
    assert manifest["input_package_sha256"] == evidence["provenance"]["input_package_sha256"]
    with zipfile.ZipFile(package) as archive:
        literal = archive.read("transcript/transcript_full_available.txt").decode("utf-8")
        assert "Antes." in literal and "Depois." in literal and "Uma pergunta e sua resposta." in literal
        episode = json.loads(archive.read("episodes/001_HISTORIA_001/episode.json"))
        assert episode["status"] == "REVIEW_REQUIRED"
        assert episode["audio_review_status"] == "unverified"
        assert episode["publication_status"] == "needs_human_review"
        assert episode["context_before"][0]["text"] == "Antes."
        assert episode["context_after"][0]["text"] == "Depois."
        assert episode["scene_evidence"]["status"] == "unknown"
        assert "PUBLISH_READY" not in archive.read("series_index.json").decode("utf-8")
    original = package.read_bytes()
    assert export_handoff(evidence, draft_plan(), tmp_path / "handoff") == package
    assert original == package.read_bytes()


def test_zero_shortlist_dossier_requires_no_episodes_or_approval(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    package = export_handoff(evidence, {"status": "DRAFT", "episodes": []}, tmp_path / "handoff")
    with zipfile.ZipFile(package) as archive:
        assert json.loads(archive.read("evidence/shortlist.json")) == []
        assert json.loads(archive.read("transcript/transcript_status.json"))["availability"]["status"] == "partial"
        assert "Uma pergunta e sua resposta." in archive.read("transcript/transcript_full_available.txt").decode("utf-8")
    validate_handoff(package)


def test_sensitive_data_removed_and_portable_media_recorded(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    evidence["source"]["path"] = r"C:\Users\private\video.mp4"
    evidence["metadata"]["HF_TOKEN"] = "hf_12345678901234567890"
    evidence["provenance"]["cache"] = "/home/private/cache"
    plan = draft_plan()
    plan["episodes"][0]["preview_path"] = r"C:\Users\private\preview.mp4"
    media = tmp_path / "preview.mp4"
    media.write_bytes(b"explicitly supplied media")
    package = export_handoff(evidence, plan, tmp_path / "handoff", media_paths={"previews/001.mp4": media, "previews/missing.mp4": tmp_path / "missing.mp4"})
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if name.endswith((".json", ".jsonl", ".md", ".txt")):
                text = archive.read(name).decode("utf-8")
                assert "C:\\\\Users" not in text and "/home/private" not in text and "hf_12345678901234567890" not in text
        source = json.loads(archive.read("source_manifest.json"))
        assert source["redactions"] and "HF_TOKEN" not in source["source_metadata"]
        assert source["media"][0]["path"] == "media/previews/001.mp4"
        assert source["media"][1]["included"] is False
        assert archive.read("media/previews/001.mp4") == media.read_bytes()
    validate_handoff(package)


def test_manifest_detects_tampering(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    package = export_handoff(evidence, draft_plan(), tmp_path / "handoff")
    with zipfile.ZipFile(package) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["INDEX.md"] += b"tampered"
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="Checksum"):
        validate_handoff(package)
    with pytest.raises(ValueError):
        export_handoff(evidence, draft_plan(), tmp_path / "handoff")


@pytest.mark.parametrize("edit", [{"source_end": 61}, {"source_start": float("nan")}, {"source_start": 25}, {"episode_id": ""}])
def test_invalid_plan_is_rejected_without_generated_zip(tmp_path, edit):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    plan = draft_plan()
    plan["episodes"][0].update(edit)
    with pytest.raises(ValueError):
        export_handoff(evidence, plan, tmp_path / "handoff")
    assert not list((tmp_path / "handoff").glob("*.zip")) if (tmp_path / "handoff").exists() else True


def test_media_paths_cannot_escape_packet(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    with pytest.raises(ValueError, match="portátil"):
        export_handoff(evidence, draft_plan(), tmp_path / "handoff", media_paths={"../escape.mp4": tmp_path / "any.mp4"})


def test_historical_fixture_full_available_handoff_preserves_every_literal_segment(tmp_path):
    fixture = Path(__file__).parent / "fixture" / "video_87cfcb5f5347"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for name in ("analysis.json", "words.json", "scenes.json", "timeline.json", "video_analysis.json"):
        shutil.copyfile(fixture / name, snapshot / name)
    (snapshot / "completion.json").write_text('{"status":"completed","artifact_complete":true}')
    evidence = load_evidence(snapshot)
    package = export_handoff(evidence, {"status": "DRAFT", "episodes": []}, tmp_path / "handoff")
    manifest = validate_handoff(package)
    assert len(manifest["files"]) >= 32
    with zipfile.ZipFile(package) as archive:
        segments = [json.loads(row) for row in archive.read("transcript/segments.jsonl").decode("utf-8").splitlines()]
        assert len(segments) == len(evidence["segments"]) == 242
        assert [row["text"] for row in segments] == [row["text"] for row in evidence["segments"]]
        assert json.loads(archive.read("transcript/transcript_status.json"))["availability"]["status"] == "partial"
        scene_description = json.loads(archive.read("evidence/scene_descriptions.json"))
        assert scene_description["status"] == "unknown"
        assert len(scene_description["scene_boundaries"]) == 145
    assert package.stat().st_size < 5_000_000


def test_explicit_source_visuals_are_embedded_and_checksum_verified(tmp_path):
    directory = settled_dir(tmp_path / "canonical")
    (directory / "visual").mkdir()
    (directory / "visual/frame.jpg").write_bytes(b"fixture opaque visual bytes")
    evidence = load_evidence(directory)
    package = export_handoff(evidence, {"episodes": []}, tmp_path / "handoff")
    with zipfile.ZipFile(package) as archive:
        assert archive.read("source_visuals/visual/frame.jpg") == b"fixture opaque visual bytes"
    validate_handoff(package)


def test_combined_extras_and_external_render_hashes_remain_distinct(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip"))
    plan = draft_plan()
    plan["extras"] = [{"episode_id": "EXTRA_001", "source_start": 10, "source_end": 20, "status": "REVIEW_REQUIRED",
        "preview": {"project_path": "EXTRAS_MELHORES_MOMENTOS/001/PREVIEW.mp4", "sha256": "DECLARED_HASH", "rendered_duration": 10}}]
    package = export_handoff(evidence, plan, tmp_path / "handoff")
    with zipfile.ZipFile(package) as archive:
        assert "episodes/001_HISTORIA_001/episode.json" in archive.namelist()
        assert "EXTRAS_MELHORES_MOMENTOS/001_EXTRA_001/episode.json" in archive.namelist()
        media = json.loads(archive.read("source_manifest.json"))["media"]
        assert media[0]["sha256"] == "DECLARED_HASH" and media[0]["included"] is False
        assert media[0]["project_path"] == "EXTRAS_MELHORES_MOMENTOS/001/PREVIEW.mp4"
        assert not any(name.endswith(".mp4") for name in archive.namelist())
    validate_handoff(package)


def test_scene_model_description_is_an_interpretation_and_never_literal_fact(tmp_path):
    evidence = load_evidence(write_package(tmp_path / "partial.zip", {"visual/scenes.json": [{"scene_id": "V1", "start": 0, "end": 60, "description": "Um objeto possível.", "inference": True}]}))
    package = export_handoff(evidence, draft_plan(), tmp_path / "handoff")
    with zipfile.ZipFile(package) as archive:
        scenes = json.loads(archive.read("evidence/scene_descriptions.json"))
        assert scenes["source_observations"] == []
        assert scenes["source_model_interpretations"][0]["description"] == "Um objeto possível."
