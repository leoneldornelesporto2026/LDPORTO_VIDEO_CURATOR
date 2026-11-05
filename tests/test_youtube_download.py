"""YouTube download safety and source verification — offline, no network calls."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from ldporto_studio.core import Project, read_json
from ldporto_studio.youtube_download import (
    download_from_youtube, parse_youtube_url, source_video_id, suggested_youtube_url,
)
from test_studio import make_fixture, DEMO

VIDEO = 'aUgESZsOGmY'


class URLSecurityTests(unittest.TestCase):
    def test_supported_video_link_formats(self):
        for url in (f'https://www.youtube.com/watch?v={VIDEO}',
                    f'https://youtu.be/{VIDEO}', f'https://m.youtube.com/shorts/{VIDEO}',
                    f'https://youtube.com/live/{VIDEO}'):
            self.assertEqual(parse_youtube_url(url), (VIDEO, f'https://www.youtube.com/watch?v={VIDEO}'))

    def test_reject_links_or_network_targets_outside_youtube(self):
        for url in ('https://www.youtube.com.evil.com/watch?v='+VIDEO,
                    'http://www.youtube.com/watch?v='+VIDEO,
                    'https://localhost/watch?v='+VIDEO,
                    'file:///etc/passwd',
                    'https://www.youtube.com/playlist?list=PLXXX',
                    'https://www.youtube.com/watch?v='+VIDEO+'&list=playlist',
                    'https://www.youtube.com/watch?v=BAD',
                    'https://user:pass@youtube.com/watch?v='+VIDEO,
                    'https://youtube.com:444/watch?v='+VIDEO,
                    'https://www.youtube.com/watch?v='+VIDEO+'&v=ooooooooooo',
                    'https://youtu.be/'+VIDEO+'/extra'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_youtube_url(url)

    def test_r57_source_url_is_explicitly_pinned(self):
        from ldporto_studio.core import CuradoriaPackage
        p=CuradoriaPackage(DEMO)
        self.assertEqual(source_video_id(p), VIDEO)
        self.assertEqual(suggested_youtube_url(p), f'https://www.youtube.com/watch?v={VIDEO}')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe needed')
class FakeDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ldporto_youtube_offline_')
        cls.root = Path(cls.temp.name)
        cls.archive, cls.media = make_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def project(self):
        import uuid
        return Project.create(self.archive, self.root / uuid.uuid4().hex)

    def fake_api(self, media, id=VIDEO):
        class YDL:
            def __init__(self, opts):self.opts=opts
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def extract_info(self,url,download):
                assert download and url==f'https://www.youtube.com/watch?v={VIDEO}'
                name=Path(self.opts['outtmpl']['default'].replace('%(ext)s','mp4'))
                shutil.copy2(media,name)
                self.opts['progress_hooks'][0]({
                    'status':'downloading','downloaded_bytes':20,'total_bytes':20,
                })
                self.opts['progress_hooks'][0]({'status':'finished'})
                self.opts['postprocessor_hooks'][0]({'status':'finished'})
                return {'id':id}
        return types.SimpleNamespace(YoutubeDL=YDL)

    def test_download_matching_source_attaches_to_project(self):
        project=self.project()
        seen=[]
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(self.media)}):
            row=download_from_youtube(project,f'https://youtu.be/{VIDEO}',progress=seen.append)
        self.assertTrue(row['linked'])
        self.assertEqual(row['status'],'VERIFIED_AND_LINKED')
        self.assertEqual(row['sha256'],hashlib.sha256(self.media.read_bytes()).hexdigest())
        self.assertTrue(Path(row['path']).is_file())
        self.assertEqual(project.verified_media(),Path(row['path']))
        self.assertEqual(read_json(Path(row['path']).parent/'download_report.json')['status'],'VERIFIED_AND_LINKED')
        self.assertEqual(project.state['youtube_url'],f'https://www.youtube.com/watch?v={VIDEO}')
        self.assertTrue(any(item['phase']=='concluído' for item in seen))

    def test_second_download_reuses_existing_media_without_network(self):
        project=self.project()
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(self.media)}):
            first=download_from_youtube(project,f'https://youtu.be/{VIDEO}')
        before=len(project.state['download_history'])
        with patch.dict(sys.modules,{'yt_dlp':None}):
            again=download_from_youtube(project,f'https://www.youtube.com/watch?v={VIDEO}')
        self.assertTrue(again['reused_existing'])
        self.assertEqual(first['path'],again['path'])
        self.assertEqual(len(project.state['download_history']),before)
        self.assertEqual(len(list((project.dir/'downloads'/'attempts').iterdir())),1)

    def test_second_download_does_not_reuse_changed_media(self):
        project=self.project()
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(self.media)}):
            first=download_from_youtube(project,f'https://youtu.be/{VIDEO}')
        Path(first['path']).write_bytes(b'alterado')
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(self.media)}):
            second=download_from_youtube(project,f'https://youtu.be/{VIDEO}')
        self.assertNotEqual(first['path'],second['path'])
        self.assertFalse(second.get('reused_existing',False))

    def test_different_valid_video_saved_but_never_attached(self):
        project=self.project()
        other=self.root/'other_video.mp4'
        import subprocess
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(self.media),
            '-c:v','libx264','-crf','30','-c:a','copy','-y',str(other)],
            capture_output=True,check=True,timeout=60)
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(other)}):
            row=download_from_youtube(project,f'https://www.youtube.com/watch?v={VIDEO}')
        self.assertFalse(row['linked'])
        self.assertEqual(row['status'],'SOURCE_REVIEW_REQUIRED')
        self.assertTrue(Path(row['path']).is_file())
        self.assertIsNone(project.state['media_path'])
        with self.assertRaisesRegex(ValueError,'não selecionada'):
            project.verified_media()
        self.assertEqual(read_json(Path(row['path']).parent/'download_report.json')['linked'],False)

    def test_downloaded_recode_requires_explicit_review_and_final_approval(self):
        from ldporto_studio.rendering import render_item
        import subprocess
        project=self.project()
        other=self.root/'different_encoding_for_review.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(self.media),
            '-c:v','libx264','-crf','30','-c:a','copy','-y',str(other)],
            capture_output=True,check=True,timeout=60)
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(other)}):
            download_from_youtube(project,f'https://youtu.be/{VIDEO}')
        with self.assertRaisesRegex(ValueError,'Revisão explícita'):
            project.review_download_for_previews()
        row=project.review_download_for_previews(confirm_timeline=True)
        self.assertEqual(row['status'],'ALTERNATE_REVIEW_SOURCE')
        self.assertNotEqual(project.active_media_sha(),project.package.source_sha)
        self.assertTrue(project.verified_media().is_file())
        preview,report=render_item(project,'REEL_01',preview=True)
        self.assertTrue(preview.is_file())
        self.assertEqual(report['render_media_sha256'],row['actual_sha256'])
        self.assertFalse(project.approval_matches('REEL_01'))
        with self.assertRaisesRegex(ValueError,'Final bloqueado'):
            render_item(project,'REEL_01',preview=False)
        project.update('REEL_01',audio_reviewed=True,camera_reviewed=True)
        approval=project.approve('REEL_01',human_reviewed=True,verified_audio=True,verified_camera=True)
        self.assertEqual(approval['media_sha256'],row['actual_sha256'])
        self.assertTrue(project.approval_matches('REEL_01'))
        final,report=render_item(project,'REEL_01',preview=False)
        self.assertTrue(final.is_file())
        self.assertEqual(report['time_alignment'],'NOT_AUTOMATICALLY_VERIFIED')
        # A second Project instance must preserve the media binding safely.
        reloaded=Project(project.dir)
        self.assertEqual(reloaded.active_media_sha(),row['actual_sha256'])
        self.assertTrue(reloaded.verified_media().is_file())
        Path(row['path']).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'SHA256'):
            project.verified_media()

    def test_wrong_video_id_in_extractor_is_rejected(self):

        project=self.project()
        with patch.dict(sys.modules,{'yt_dlp':self.fake_api(self.media,id='ooooooooooo')}):
            with self.assertRaisesRegex(ValueError,'identidade diferente'):
                download_from_youtube(project,f'https://www.youtube.com/watch?v={VIDEO}')
        self.assertIsNone(project.state['media_path'])

    def test_source_pinned_r57_rejects_wrong_link_before_any_download(self):
        project=Project.create(DEMO,self.root/'project_r57')
        with self.assertRaisesRegex(ValueError,'não pertence ao vídeo'):
            download_from_youtube(project,'https://www.youtube.com/watch?v=ooooooooooo')


if __name__=='__main__':unittest.main()
