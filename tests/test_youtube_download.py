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
