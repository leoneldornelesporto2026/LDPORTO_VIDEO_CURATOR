"""Read-only R6 existing-media discovery tests (no network or real video files)."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ldporto_studio.__main__ import main
from ldporto_studio.r6_media_audit import audit_r6_media,MAX_HASH_FILES
from test_r6_review import make_valid_r6_delivery


class R6MediaAuditTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="r6_media_audit_")
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'RUN123'
        self.package=make_valid_r6_delivery(self.inbox)
        self.app=self.root/'app'
        self.projects=self.app/'output'/'projects'
        self.videos=self.root/'Windows Videos'/'LDPORTO_VIDEO_CURATOR'
        self.video_id='aUgESZsOGmY'
        self.filename=self.app/'input'/'videos'/self.video_id/'pkgsha'/'run'/'source.mp4'
        self.filename.parent.mkdir(parents=True)
        self.filename.write_bytes(b'not a real mp4: synthetic fixture')
        self.kwargs=dict(app_root=self.app,projects_root=self.projects,videos_root=self.videos)
        self.url_patcher=patch('ldporto_studio.youtube_download.parse_youtube_url',
                         return_value=(self.video_id,'https://www.youtube.com/watch?v='+self.video_id))
        self.url_patcher.start()
        self.addCleanup(self.url_patcher.stop)

    def audit(self,**kwargs):
        return audit_r6_media(self.inbox,**self.kwargs,**kwargs)

    def test_discovery_reports_mismatch_without_associating(self):
        source=self.package.read_bytes()
        video=self.filename.read_bytes()
        result=self.audit()
        self.assertEqual(result['status'],'ALTERNATE_MEDIA_ONLY_REVIEW_REQUIRED')
        self.assertEqual(result['hashed_media_count'],1)
        self.assertEqual(result['exact_matches_count'],0)
        self.assertFalse(result['media'][0]['matches_analyzer'])
        self.assertFalse(result['media'][0]['can_reuse_timestamps_without_reanalysis'])
        self.assertFalse(result['render_ready'])
        self.assertFalse(result['media_associated'])
        self.assertFalse(result['download_executed'])
        self.assertFalse(result['files_modified'])
        self.assertEqual(self.package.read_bytes(),source)
        self.assertEqual(self.filename.read_bytes(),video)

    def test_exact_sha_only_when_bytes_match_analyzer(self):
        with patch('ldporto_studio.r6_media_audit.sha256_file',return_value='a'*64):
            result=self.audit()
        self.assertEqual(result['status'],'EXACT_SOURCE_FOUND')
        self.assertEqual(result['exact_matches_count'],1)
        self.assertTrue(result['media'][0]['matches_analyzer'])
        self.assertTrue(result['media'][0]['can_reuse_timestamps_without_reanalysis'])
        self.assertFalse(result['render_ready'])
        self.assertFalse(result['human_approved'])

    def test_does_not_search_unrelated_video_id(self):
        self.filename.unlink()
        other=self.app/'input'/'videos'/'OTHER_VIDEO'/'attempt'/'source.mp4'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'alien video')
        result=self.audit()
        self.assertEqual(result['status'],'NO_MANAGED_MEDIA_FOUND')
        self.assertEqual(result['hashed_media_count'],0)
        self.assertTrue(other.is_file())

    def test_reads_legacy_projects_without_moving_media(self):
        self.filename.unlink()
        old=self.projects/'old_r57'/'downloads'/'attempts'/'run'/'source.mkv'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'legacy original')
        result=self.audit()
        self.assertEqual(result['hashed_media_count'],1)
        self.assertEqual(result['media'][0]['location_type'],'LEGACY_PROJECT_DOWNLOADS')
        self.assertTrue(old.is_file())

    def test_reads_old_windows_videos_folder(self):
        self.filename.unlink()
        old=self.videos/self.video_id/'digest'/'run'/'source.mp4'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'legacy original')
        result=self.audit()
        self.assertEqual(result['hashed_media_count'],1)
        self.assertEqual(result['media'][0]['location_type'],'LEGACY_WINDOWS_VIDEOS')

    def test_user_can_supply_explicit_file_without_searching_whole_disk(self):
        external=self.root/'manual'/'known_source.mp4'
        external.parent.mkdir()
        external.write_bytes(b'choose explicitly')
        result=self.audit(explicit_media=external)
        self.assertEqual(result['media'][0]['location_type'],'EXPLICIT_MEDIA')
        self.assertEqual(result['hashed_media_count'],2)

    def test_limit_is_bounded_and_explicit(self):
        for count in (0,-1,13,False,'3'):
            with self.assertRaises(ValueError):
                self.audit(max_files=count)
        self.assertEqual(MAX_HASH_FILES,12)
        result=self.audit(max_files=1)
        self.assertLessEqual(result['hashed_media_count'],1)

    def test_cli_runs_without_ids_draft_or_network(self):
        with patch('ldporto_studio.r6_media_audit.application_root',return_value=self.app),\
             patch('ldporto_studio.r6_media_audit.project_output_root',return_value=self.projects),\
             patch('ldporto_studio.r6_media_audit.videos_download_root',return_value=self.videos):
            stdout=StringIO()
            with redirect_stdout(stdout):
                code=main(['r6-media-audit','--inbox',str(self.inbox)])
        self.assertEqual(code,0)
        result=json.loads(stdout.getvalue())
        self.assertEqual(result['hashed_media_count'],1)
        self.assertEqual(result['status'],'ALTERNATE_MEDIA_ONLY_REVIEW_REQUIRED')
        self.assertFalse(result['render_ready'])


if __name__=="__main__":
    unittest.main()
