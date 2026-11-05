"""Synthetic read-only tests for Analyzer inbox inspection; no rendering."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from ldporto_studio.analyzer_inbox import inspect_delivery


class AnalyzerInboxTests(unittest.TestCase):
    def make_delivery(self, root):
        members = {
            "source/metadata.json": json.dumps({"sha256": "a" * 64}).encode(),
            "CURATION_INDEX.json": json.dumps({"candidate_count": 1}).encode(),
            "SECOND_CURATOR_BRIEF.json": b"{}",
            "editorial/candidate_catalog.json": json.dumps({"candidates": [{"candidate_id": "X1"}]}).encode(),
        }
        manifest = {"run_id": "synthetic-run", "preview_approved": False, "publication_ready": False,
                    "files": [{"path": n, "bytes": len(raw),
                               "sha256": hashlib.sha256(raw).hexdigest()} for n, raw in members.items()]}
        with zipfile.ZipFile(root / "SYNTHETIC.zip", "x") as arc:
            for name, raw in members.items():
                arc.writestr(name, raw)
            arc.writestr("SECOND_CURATION_MANIFEST.json", json.dumps(manifest))
        package = root / "SYNTHETIC.zip"
        receipt = {"curator_import_status": "CURATOR_IMPORT_PENDING",
                   "human_approval": False, "publication_ready": False,
                   "run_id": "synthetic-run", "source_sha256": "a" * 64,
                   "reel_candidate_count": 1,
                   "zip": {"name": package.name, "bytes": package.stat().st_size,
                           "sha256": hashlib.sha256(package.read_bytes()).hexdigest()}}
        (root / "ANALYZER_TO_CURATOR_HANDOFF.json").write_text(json.dumps(receipt), encoding="utf-8")
        return package

    def test_inspects_valid_synthetic_package_without_creating_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_delivery(root)
            before = sorted(x.name for x in root.iterdir())
            result = inspect_delivery(root)
            self.assertEqual(result["inspection_status"], "VALID")
            self.assertEqual(result["curator_import_status"], "CURATOR_IMPORT_PENDING")
            self.assertEqual(sorted(x.name for x in root.iterdir()), before)

    def test_validates_full_evidence_index_when_provided(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = self.make_delivery(root)
            with zipfile.ZipFile(package) as archived:
                entries = [
                    {"path":info.filename,"bytes":info.file_size,
                     "sha256":hashlib.sha256(archived.read(info.filename)).hexdigest()}
                    for info in archived.infolist()
                ]
            receipt_path = root / "ANALYZER_TO_CURATOR_HANDOFF.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            evidence = {
                "schema_version":"1.0","video_id":"SYNTHETIC",
                "run_id":receipt["run_id"],
                "source_sha256":receipt["source_sha256"],
                "zip_sha256":receipt["zip"]["sha256"],
                "artifact_count":len(entries),"artifacts":entries,
                "curator_import_status":"CURATOR_IMPORT_PENDING",
                "video_file_included":False,"publication_ready":False,
            }
            evidence_file = root / "VIDEO_EVIDENCE_INDEX.json"
            evidence_file.write_text(json.dumps(evidence),encoding="utf-8")
            receipt["evidence_index"]={
                "name":evidence_file.name,"sha256":hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
                "artifact_count":len(entries),
            }
            receipt_path.write_text(json.dumps(receipt),encoding="utf-8")
            inspected=inspect_delivery(root)
            self.assertEqual(inspected["evidence_file_count"],len(entries))
            self.assertEqual(inspected["evidence_index_path"],str(evidence_file))
            # A corrupted sidecar blocks the handoff, without altering media or the original ZIP.
            evidence_file.write_text("{}",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"evidence_index_hash_mismatch"):
                inspect_delivery(root)
            self.assertTrue(package.is_file())

    def test_detects_altered_zip_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = self.make_delivery(root)
            package.write_bytes(package.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "zip_bytes_mismatch"):
                inspect_delivery(root)

    def test_rejects_false_approval_even_if_archive_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_delivery(root)
            path = root / "ANALYZER_TO_CURATOR_HANDOFF.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["human_approval"] = True
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unverified_approval_claim"):
                inspect_delivery(root)


if __name__ == "__main__":
    unittest.main()
