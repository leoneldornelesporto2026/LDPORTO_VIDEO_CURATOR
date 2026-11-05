"""Read-only validation for Analyzer-native second-curation inbox deliveries.

Not the R57 editorial Studio importer. Never extracts media, creates projects,
modifies approvals or signals CURATOR_IMPORT_SUCCESS.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


MAX_ZIP_BYTES = 256 * 1024 * 1024
MAX_FILES = 5000
REQUIRED = {
    "SECOND_CURATION_MANIFEST.json",
    "CURATION_INDEX.json",
    "SECOND_CURATOR_BRIEF.json",
    "editorial/candidate_catalog.json",
    "source/metadata.json",
}


def _hash_file(path):
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and (
        "\\" not in name and ":" not in name and p.as_posix() == name
    )


def inspect_delivery(directory):
    """Validate original ZIP and its sidecar. Does not import or alter content."""
    root = Path(directory)
    receipt_path = root / "ANALYZER_TO_CURATOR_HANDOFF.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("curator_import_status") != "CURATOR_IMPORT_PENDING":
        raise ValueError("unexpected_curator_import_status")
    if receipt.get("human_approval") is not False or receipt.get("publication_ready") is not False:
        raise ValueError("unverified_approval_claim")
    zip_info = receipt.get("zip") or {}
    name = zip_info.get("name")
    if not isinstance(name, str) or Path(name).name != name or name in (".", "..") or not name.endswith(".zip"):
        raise ValueError("invalid_zip_name")
    package = root / name
    if package.is_symlink() or not package.is_file():
        raise ValueError("zip_missing_or_link")
    if package.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("zip_size_limit")
    if package.stat().st_size != zip_info.get("bytes"):
        raise ValueError("zip_bytes_mismatch")
    actual = _hash_file(package)
    if actual != zip_info.get("sha256"):
        raise ValueError("zip_sha256_mismatch")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > MAX_FILES or not all(_safe_member(n) for n in names):
            raise ValueError("unsafe_or_duplicate_zip_members")
        if sum(info.file_size for info in archive.infolist()) > MAX_ZIP_BYTES:
            raise ValueError("uncompressed_size_limit")
        if not REQUIRED <= set(names):
            raise ValueError("missing_analyzer_contract")
        if archive.testzip() is not None:
            raise ValueError("zip_crc_mismatch")
        manifest = json.loads(archive.read("SECOND_CURATION_MANIFEST.json"))
        index = json.loads(archive.read("CURATION_INDEX.json"))
        catalog = json.loads(archive.read("editorial/candidate_catalog.json"))
        metadata = json.loads(archive.read("source/metadata.json"))
        for member in manifest.get("files") or []:
            name = member.get("path")
            if not isinstance(name, str) or name not in names or name == "SECOND_CURATION_MANIFEST.json":
                raise ValueError("invalid_manifest_member")
            payload = archive.read(name)
            if len(payload) != member.get("bytes") or sha256(payload).hexdigest() != member.get("sha256"):
                raise ValueError("manifest_member_integrity_mismatch")
    if receipt.get("run_id") != manifest.get("run_id") or receipt.get("source_sha256") != metadata.get("sha256"):
        raise ValueError("receipt_identity_mismatch")
    if receipt.get("reel_candidate_count") != len(catalog.get("candidates") or []):
        raise ValueError("receipt_candidate_count_mismatch")
    if index.get("candidate_count") != len(catalog.get("candidates") or []):
        raise ValueError("index_candidate_count_mismatch")
    if manifest.get("preview_approved") is True or manifest.get("publication_ready") is True:
        raise ValueError("analyzer_package_must_not_claim_approval")
    evidence_ref = receipt.get("evidence_index")
    evidence_count = None
    evidence_index_path = None
    if evidence_ref is not None:
        if (not isinstance(evidence_ref, dict) or
            evidence_ref.get("name") != "VIDEO_EVIDENCE_INDEX.json"):
            raise ValueError("invalid_evidence_index_ref")
        evidence_file = root / "VIDEO_EVIDENCE_INDEX.json"
        if (evidence_file.is_symlink() or not evidence_file.is_file()
            or evidence_file.stat().st_size > 2 * 1024 * 1024
            or _hash_file(evidence_file) != evidence_ref.get("sha256")):
            raise ValueError("evidence_index_hash_mismatch")
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
        if (not isinstance(evidence, dict) or
            evidence.get("zip_sha256") != actual or
            evidence.get("run_id") != receipt.get("run_id") or
            evidence.get("source_sha256") != receipt.get("source_sha256") or
            evidence.get("curator_import_status") != "CURATOR_IMPORT_PENDING" or
            evidence.get("publication_ready") is not False or
            evidence.get("video_file_included") is not False):
            raise ValueError("evidence_index_identity_mismatch")
        artifacts = evidence.get("artifacts")
        if (not isinstance(artifacts, list) or
            len(artifacts) != len(names) or
            {row.get("path") for row in artifacts if isinstance(row, dict)} != set(names) or
            evidence.get("artifact_count") != len(names) or
            evidence_ref.get("artifact_count") != len(names)):
            raise ValueError("evidence_index_file_list_mismatch")
        evidence_count = len(names)
        evidence_index_path = str(evidence_file)
    return {
        "inspection_status": "VALID",
        "curator_import_status": "CURATOR_IMPORT_PENDING",
        "package_path": str(package),
        "zip_sha256": actual,
        "reel_candidate_count": len(catalog.get("candidates") or []),
        "evidence_file_count": evidence_count,
        "evidence_index_path": evidence_index_path,
        "human_approval": False,
        "publication_ready": False,
        "next_step": "Manual second curation with ChatGPT; R57 import is NOT yet supported.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect, never import, an Analyzer inbox package")
    parser.add_argument("--path", required=True, help="Directory input/analyzer/<video_id>/<run_id>")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_delivery(args.path), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"inspection_status": "BLOCKED", "reason": str(exc),
                          "curator_import_status": "CURATOR_IMPORT_PENDING"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
