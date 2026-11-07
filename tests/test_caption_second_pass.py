"""Second curator must explicitly check SRT/ASS and listened audio before captions."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ldporto_studio.core import Project
from ldporto_studio.caption_second_pass import (
    inspect_caption_second_pass, save_caption_second_pass_report)
from ldporto_studio.__main__ import main


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "example" / "CURADORIA_R57.zip"


class CaptionSecondPassTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="second_caption_")
        self.addCleanup(t.cleanup)
        self.folder=Path(t.name)
        self.project=Project.create(DEMO,self.folder/"project")

    def test_structural_pass_does_not_approve_or_enable_subtitles(self):
        before=dict(self.project.settings("REEL_01"))
        report=inspect_caption_second_pass(self.project,"REEL_01")
        self.assertEqual(report["clip_id"],"REEL_01")
        self.assertGreaterEqual(report["cue_count"],1)
        self.assertEqual(report["status"],"SECOND_CURATOR_AUDIO_AND_TEXT_REVIEW_REQUIRED")
        self.assertFalse(report["second_listening_pass_completed"])
        self.assertFalse(report["human_approved"])
        self.assertFalse(report["captions_verified"])
        self.assertTrue(report["original_analyzer_asr_may_contain_errors"])
        self.assertEqual(before,self.project.settings("REEL_01"))
        self.assertFalse((self.project.dir/"exports"/"caption_second_pass").exists())

    def test_report_is_local_idempotent_no_original_zip_change(self):
        from ldporto_studio.core import sha256_file
        initial_sha=sha256_file(DEMO)
        first=save_caption_second_pass_report(self.project,"REEL_01")
        second=save_caption_second_pass_report(self.project,"REEL_01")
        self.assertEqual(first,second)
        report=json.loads(first.read_text(encoding="utf-8"))
        self.assertFalse(report["captions_verified"])
        self.assertEqual(sha256_file(DEMO),initial_sha)
        self.assertFalse(self.project.state["publication_ready"])

    def test_tampered_report_remains_untouched(self):
        path=save_caption_second_pass_report(self.project,"REEL_01")
        path.write_text("modified by reviewer",encoding="utf-8")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            save_caption_second_pass_report(self.project,"REEL_01")
        self.assertEqual(path.read_text(encoding="utf-8"),"modified by reviewer")

    def test_mismatched_ass_text_is_flagged_not_silently_corrected(self):
        wrong=(b"[Script Info]\n[Events]\n"
               b"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Not what was said\n")
        with patch.object(self.project,"caption_payload",return_value=wrong):
            result=inspect_caption_second_pass(self.project,"REEL_01")
        self.assertIn("TEXTO_SRT_ASS_DIFERENTE",result["flags"])
        self.assertFalse(result["structural_text_consistency"])
        self.assertFalse(result["captions_verified"])

    def test_no_dialogues_or_missing_cues_are_reported(self):
        with patch.object(self.project,"caption_payload",
                          return_value=b"[Script Info]\n[Events]\n"):
            report=inspect_caption_second_pass(self.project,"REEL_01")
        self.assertIn("SRT_ASS_QUANTIDADE_DIFERENTE",report["flags"])

    def test_cli_inspects_only_and_optional_save_does_not_approve(self):
        args=["captions-second-check","--workdir",str(self.project.dir),
              "--id","REEL_01"]
        output=StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args),0)
        report=json.loads(output.getvalue())
        self.assertIsNone(report["saved_report_path"])
        self.assertFalse(report["captions_verified"])
        self.assertFalse((self.project.dir/"exports"/"caption_second_pass").exists())
        output=StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args+["--save"]),0)
        saved=json.loads(output.getvalue())["saved_report_path"]
        self.assertTrue(Path(saved).is_file())

    def test_gui_exposes_second_check_and_does_not_overwrite_edited_srt(self):
        source=(ROOT/"ldporto_studio"/"gui.py").read_text(encoding="utf-8")
        self.assertIn("2ª CHECAGEM DE LEGENDAS (SRT/ASS)",source)
        self.assertIn("save_caption_second_pass_report",source)
        self.assertIn("if not p.exists():",source)
        self.assertIn("Conferi transcrição e áudio desta legenda",source)


if __name__=="__main__":
    unittest.main()
