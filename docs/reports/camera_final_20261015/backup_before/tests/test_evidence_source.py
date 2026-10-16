import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

import pytest

from ldporto_curator.evidence_source import load_evidence


def write_package(path, changes=None):
    documents = {
        "source/metadata.json": {"sha256": "SOURCE_HASH", "duration": 60, "analyzer_version": "test-inference", "source": {"id": "ZERO", "title": "Título observado"}},
        "editorial/candidate_catalog.json": {"candidates": [{"candidate_id": "C1", "start": 5, "end": 25, "segment_ids": ["S1"], "visual_refs": []}]},
        "editorial/default_shortlist.json": {"candidate_ids": []},
        "transcript/relevant_segments.jsonl": [{"segment_id": "S1", "start": 5, "end": 25, "text": "Uma pergunta e sua resposta."}],
        "editorial/review_queue.json": {"candidate_ids": ["C1"]},
    }
    documents.update(changes or {})
    files = {name: (("\n".join(json.dumps(row, ensure_ascii=False) for row in data) + "\n") if name.endswith(".jsonl") else json.dumps(data, ensure_ascii=False)).encode("utf-8") for name, data in documents.items()}
    manifest = {"source_hash": documents["source/metadata.json"]["sha256"], "build_mismatch": {"inference": "test-inference", "replay": "test-replay"},
        "files": [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in files.items()]}
    files["SECOND_CURATION_MANIFEST.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return path


def settled_dir(path, source_hash="SOURCE_HASH", status="completed"):
    path.mkdir()
    analysis = {"analysis_status": status, "metadata": {"sha256": source_hash, "duration": 60, "analyzer_version": "canonical", "source": {"id": "ZERO"}},
        "transcript_segments": [{"segment_id": "S0", "start": 0, "end": 4, "text": "Antes."}, {"segment_id": "S1", "start": 5, "end": 25, "text": "Uma pergunta e sua resposta."}, {"segment_id": "S2", "start": 30, "end": 60, "text": "Depois."}]}
    (path / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    return path


def test_zero_shortlist_is_preserved_and_partial_is_never_full(tmp_path):
    package = write_package(tmp_path / "SECOND_CURATION_PARTIAL_ZERO.zip")
    evidence = load_evidence(package)
    assert evidence["shortlist"] == [] and evidence["candidates"][0]["candidate_id"] == "C1"
    assert evidence["review_queue"] == ["C1"]
    assert evidence["availability"]["segments"]["status"] == "partial"
    assert evidence["availability"]["words"]["status"] == "missing"
    assert evidence["provenance"]["input_package_sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    assert evidence["provenance"]["build_mismatch"] == {"inference": "test-inference", "replay": "test-replay"}
    assert evidence["decisions"] == {}
    assert not any(row.get("approved") for row in evidence["candidates"])


def test_canonical_enrichment_requires_matching_hash_and_keeps_package_provenance(tmp_path):
    package = write_package(tmp_path / "package.zip")
    canonical = settled_dir(tmp_path / "canonical")
    before = {p.name: p.read_bytes() for p in canonical.iterdir()}
    evidence = load_evidence(package, canonical_dir=canonical)
    assert len(evidence["segments"]) == 3
    assert evidence["availability"]["segments"]["sources"] == ["canonical/analysis.json#transcript_segments"]
    assert evidence["provenance"]["input_package_sha256"]
    assert evidence["provenance"]["canonical_analyzer_version"] == "canonical"
    assert before == {p.name: p.read_bytes() for p in canonical.iterdir()}
    (canonical / "analysis.json").write_text((canonical / "analysis.json").read_text().replace("SOURCE_HASH", "DIFFERENT"))
    with pytest.raises(ValueError, match="Hash"):
        load_evidence(package, canonical_dir=canonical)


def test_partial_settled_snapshot_stays_partial(tmp_path):
    directory = settled_dir(tmp_path / "snapshot", status="partial")
    with pytest.raises(ValueError, match="conclusão"):
        load_evidence(directory)
    (directory / "completion.json").write_text('{"status":"completed","artifact_complete":true}')
    evidence = load_evidence(directory)
    assert evidence["provenance"]["analysis_status"] == "partial"
    assert evidence["availability"]["segments"]["status"] == "partial"
    (directory / "PROCESSING.flag").write_text("")
    with pytest.raises(ValueError, match="ativa"):
        load_evidence(directory)


@pytest.mark.parametrize("change", [
    {"transcript/relevant_segments.jsonl": [{"segment_id": "S1", "start": float("nan"), "end": 25, "text": "Inválido."}]},
    {"transcript/relevant_segments.jsonl": [{"segment_id": "S1", "start": 5, "end": 61, "text": "Inválido."}]},
    {"transcript/relevant_segments.jsonl": [{"segment_id": "S1", "start": 5, "end": 25, "text": "A."}, {"segment_id": "S1", "start": 26, "end": 30, "text": "B."}]},
    {"visual/scenes.json": [{"scene_id": "V1", "start": 1, "end": 2, "keyframe": "../../secret.jpg"}]},
    {"editorial/default_shortlist.json": {"candidate_ids": ["MISSING"]}},
])
def test_invalid_evidence_rows_are_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        load_evidence(write_package(tmp_path / "bad.zip", change))


@pytest.mark.parametrize("name", ["../escape.json", "C:/secret.json", "folder\\secret.json"])
def test_archive_paths_are_bounded_by_existing_reader(tmp_path, name):
    path = write_package(tmp_path / "bad.zip")
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(name, "{}")
    with pytest.raises(ValueError):
        load_evidence(path)
    assert not (tmp_path / "escape.json").exists()


def test_symlink_archive_payload_is_rejected(tmp_path):
    path = write_package(tmp_path / "bad.zip")
    with zipfile.ZipFile(path, "a") as archive:
        link = zipfile.ZipInfo("visual/link.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../secret.json")
    with pytest.raises(ValueError):
        load_evidence(path)


def test_historical_fixture_is_read_only_and_retains_observation_uncertainty(tmp_path):
    fixture = Path(__file__).parent / "fixture" / "video_87cfcb5f5347"
    snapshot = tmp_path / "fixture"
    snapshot.mkdir()
    names = ["analysis.json", "words.json", "scenes.json", "timeline.json", "video_analysis.json"]
    hashes = {name: hashlib.sha256((fixture / name).read_bytes()).hexdigest() for name in names}
    for name in names:
        shutil.copyfile(fixture / name, snapshot / name)
    (snapshot / "completion.json").write_text('{"status":"completed","artifact_complete":true}')
    evidence = load_evidence(snapshot)
    assert len(evidence["segments"]) == 242
    assert len(evidence["words"]) == 2991 and len(evidence["scenes"]) == 145
    assert evidence["timeline"][0]["active_person"] is None
    assert evidence["availability"]["speakers"]["status"] == "not_measured"
    assert evidence["availability"]["ocr"]["status"] == "not_measured"
    assert evidence["availability"]["segments"]["status"] == "partial"
    assert evidence["unresolved_references"]  # Thumbnail files are absent from fixture.
    assert hashes == {name: hashlib.sha256((fixture / name).read_bytes()).hexdigest() for name in names}


def test_component_source_mismatch_is_reported_stale(tmp_path):
    path = write_package(tmp_path / "package.zip", {"visual/scenes.json": {"source_sha256": "OTHER", "scenes": [{"scene_id": "X", "start": 0, "end": 1}]}})
    evidence = load_evidence(path)
    assert evidence["availability"]["scenes"]["status"] == "stale"


def test_empty_manifest_cannot_falsely_prove_snapshot_completion(tmp_path):
    directory = settled_dir(tmp_path / "unfinished", status="partial")
    (directory / "SECOND_CURATION_MANIFEST.json").write_text('{"source_hash":"SOURCE_HASH","files":[]}')
    with pytest.raises(ValueError, match="essenciais"):
        load_evidence(directory)


def test_duplicate_timeline_ids_are_rejected(tmp_path):
    package = write_package(tmp_path / "bad.zip", {"timeline.json": [{"timeline_id": "T1", "start": 0, "end": 1}, {"timeline_id": "T1", "start": 2, "end": 3}]})
    with pytest.raises(ValueError, match="IDs"):
        load_evidence(package)


def test_decision_document_requires_explicit_matching_source(tmp_path):
    directory = settled_dir(tmp_path / "analysis")
    (directory / "editorial").mkdir()
    (directory / "editorial/candidate_catalog.json").write_text(json.dumps({"candidates": [{"candidate_id": "C1", "start": 5, "end": 25, "segment_ids": ["S1"]}]}))
    decision = {"schema_version": "4.4.0", "source_sha256": "SOURCE_HASH", "provider": "manual_json", "actions": [{"decision_id": "D1", "action": "approve", "candidate_ids": ["C1"], "reason": "Revisão editorial."}]}
    document = tmp_path / "SECOND_CURATION_DECISIONS.json"
    document.write_text(json.dumps(decision))
    with pytest.raises(ValueError, match="canonical_dir"):
        load_evidence(document)
    evidence = load_evidence(document, canonical_dir=directory)
    assert evidence["decisions"]["actions"][0]["action"] == "approve"
    assert not evidence["candidates"][0].get("approved")
