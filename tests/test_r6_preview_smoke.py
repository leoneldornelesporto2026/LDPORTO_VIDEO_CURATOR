"""R6 technical preview smoke: exact-source, read-only, never final or approved."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ldporto_studio.__main__ import main
from ldporto_studio.r6_preview_smoke import render_r6_technical_preview
from ldporto_studio.core import sha256_file
from ldporto_studio.r6_review import read_analyzer_review
from test_r6_review import make_valid_r6_delivery


class PreviewGateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='ldporto_r6_prev_gate_')
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.inbox=self.root/'input'/'analyzer'/'video'/'run'
        make_valid_r6_delivery(self.inbox)
        self.source=self.root/'source.mp4'
        self.source.write_bytes(b'not video: must stop before FFmpeg')
    def test_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError,'confirm-preview-test'):
            render_r6_technical_preview(self.inbox,self.source)
    def test_rejects_sha_mismatch_before_looking_at_decoding(self):
        with self.assertRaisesRegex(ValueError,'SHA256'):
            render_r6_technical_preview(self.inbox,self.source,confirm=True)
    def test_rejects_missing_or_invalid_source(self):
        with self.assertRaises((FileNotFoundError,ValueError)):
            render_r6_technical_preview(self.inbox,self.root/'absent.mp4',confirm=True)
        with self.assertRaises(ValueError):
            render_r6_technical_preview(self.inbox,self.source,confirm=True,seconds=30)
    def test_no_draft_selection_or_approval_can_be_accepted(self):
        from ldporto_studio.r6_preview_smoke import MAX_PREVIEW_SECONDS
        self.assertEqual(MAX_PREVIEW_SECONDS,8)
        # The candidate is picked from immutable Analyzer R6, not any edited
        # local SMOKE_R6 or R57 project state.
        self.assertEqual(read_analyzer_review(self.inbox)['candidate_count'],2)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg/FFprobe required for real preview test')
class PreviewRealFFmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_studio import make_fixture
        cls.tmp=tempfile.TemporaryDirectory(prefix='ldporto_prev_real_')
        cls.root=Path(cls.tmp.name)
        _,cls.media=make_fixture(cls.root)
        cls.inbox=cls.root/'input'/'analyzer'/'video'/'run'
        make_valid_r6_delivery(cls.inbox)
        cls.review=read_analyzer_review(cls.inbox)
        cls.review['source']['source_sha256']=sha256_file(cls.media)
        cls.review['source']['duration_seconds']=4.0
        cls.review['candidates'][0]['start']=0.5
        cls.review['candidates'][0]['end']=2.7
        cls.review['candidates'][0]['duration_seconds']=2.2
        cls.review['candidates'][1]['start']=3.1
        cls.review['candidates'][1]['end']=3.8
        cls.review['candidates'][1]['duration_seconds']=0.7
        cls.root_out=cls.root/'output'/'r6_preview_smoke'
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def test_real_technical_preview_and_idempotence(self):
        with patch('ldporto_studio.r6_preview_smoke.read_analyzer_review',return_value=self.review):
            first=render_r6_technical_preview(self.inbox,self.media,
                 confirm=True,output_root=self.root_out,seconds=1.5)
            again=render_r6_technical_preview(self.inbox,self.media,
                 confirm=True,output_root=self.root_out,seconds=1.5)
        self.assertEqual(first['status'],'TECHNICAL_PREVIEW_REVIEW_REQUIRED')
        self.assertFalse(first['publication_ready'])
        self.assertFalse(first['render_ready'])
        self.assertFalse(first['human_approved'])
        self.assertFalse(first['is_complete_reel'])
        self.assertTrue(first['has_audio'])
        self.assertEqual(first['output_width'],360)
        self.assertEqual(first['output_height'],640)
        self.assertTrue(Path(first['file_path']).is_file())
        self.assertTrue(again['reused_existing'])
        self.assertEqual(first['preview_sha256'],again['preview_sha256'])
        self.assertFalse((self.root/'output'/'projects').exists())
    def test_rejects_tampered_existing_preview_without_overwriting(self):
        with patch('ldporto_studio.r6_preview_smoke.read_analyzer_review',return_value=self.review):
            first=render_r6_technical_preview(self.inbox,self.media,
                confirm=True,output_root=self.root_out,seconds=1.5)
            p=Path(first['file_path'])
            p.write_bytes(p.read_bytes()+b'tampered')
            with self.assertRaisesRegex(ValueError,'divergiu'):
                render_r6_technical_preview(self.inbox,self.media,
                    confirm=True,output_root=self.root_out,seconds=1.5)


if __name__=='__main__':
    unittest.main()
