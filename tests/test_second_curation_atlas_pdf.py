"""Regression: import verified static scene atlas PDFs without permitting arbitrary PDF uploads."""
import hashlib
import json
import zipfile

import pytest

from ldporto_curator.second_curation_import import read_package


def _package(path, *, atlas_name="VISUAL_SCENES_ATLAS_000_010_MIN.pdf", atlas_payload=b"%PDF-1.4\nstatic atlas\n"):
    source_sha = "a" * 64
    entries = {
        "source/metadata.json": json.dumps({"sha256": source_sha, "duration": 60,
            "source": {"id": "test-video"}}).encode(),
        "editorial/candidate_catalog.json": json.dumps({"candidates": [{
            "candidate_id": "C1", "start": 1, "end": 5, "segment_ids": ["S1"],
            "visual_refs": [], "file_refs": []}]}).encode(),
        "transcript/relevant_segments.jsonl": (
            json.dumps({"segment_id": "S1", "start": 1, "end": 5, "text": "teste"}) + "\n"
        ).encode(),
        atlas_name: atlas_payload,
    }
    manifest = {"source_hash": source_sha, "files": [
        {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in entries.items()
    ]}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        archive.writestr("SECOND_CURATION_MANIFEST.json", json.dumps(manifest))


def test_allows_manifest_verified_atlas_pdf(tmp_path):
    path = tmp_path / "valid.zip"
    _package(path)
    result = read_package(path)
    assert "VISUAL_SCENES_ATLAS_000_010_MIN.pdf" in result["files"]
    assert result["metadata"]["sha256"] == "a" * 64


@pytest.mark.parametrize("name", ["arbitrary.pdf", "subdir/VISUAL_SCENES_ATLAS_000_010_MIN.pdf"])
def test_rejects_unapproved_pdf_paths(tmp_path, name):
    path = tmp_path / "bad.zip"
    _package(path, atlas_name=name)
    with pytest.raises(ValueError, match="Tipo de arquivo"):
        read_package(path)


def test_rejects_oversized_atlas_pdf(tmp_path):
    path = tmp_path / "oversized.zip"
    _package(path, atlas_payload=b"%PDF-1.4\n" + b"A" * (12 * 1024 ** 2))
    with pytest.raises(ValueError, match="Tipo de arquivo"):
        read_package(path)
