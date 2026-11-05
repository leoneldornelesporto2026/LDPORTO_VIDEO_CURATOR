"""Output is local-only, and old Studio work may be copied without data loss."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ldporto_studio.workspace import application_root, project_output_root, import_existing_project
from ldporto_studio.core import Project, sha256_file, atomic_write


class OutputPathsTest(unittest.TestCase):
    def test_output_is_inside_this_project(self):
        root = application_root()
        self.assertEqual(project_output_root(), root / 'output' / 'projects')

    def test_gitignore_tracks_only_editorial_scripts(self):
        lines=(application_root()/'.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('/output/*',lines)
        self.assertIn('!/output/scripts/',lines)
        self.assertIn('/input/*',lines)
        self.assertNotIn('/output/',lines)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg needed')
class AdoptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='curator_output_')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        from test_studio import make_fixture
        archive,video=make_fixture(self.root)
        self.legacy=Project.create(archive, self.root/'legacy'/'PROJECT')
        self.media=self.legacy.dir/'downloads'/'attempts'/'test'/'source.mp4'
        self.media.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(video,self.media)
        self.legacy.set_media(self.media)

    def test_adoption_preserves_media_and_original(self):
        destination=import_existing_project(self.legacy.dir,self.root/'output'/'projects')
        self.assertEqual(destination,self.root/'output'/'projects'/'PROJECT')
        restored=Project(destination)
        self.assertEqual(restored.verified_media(),destination/'downloads'/'attempts'/'test'/'source.mp4')
        self.assertEqual(sha256_file(restored.verified_media()),self.legacy.package.source_sha)
        self.assertTrue(self.legacy.verified_media().is_file())
        with self.assertRaises(FileExistsError):
            import_existing_project(self.legacy.dir,self.root/'output'/'projects')

    def test_adoption_preserves_alternate_review_receipts(self):
        other=self.root/'another.mp4'
        import subprocess
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(self.media),
            '-c:v','libx264','-crf','30','-c:a','copy','-y',str(other)],
            capture_output=True,check=True,timeout=90)
        shutil.copy2(other,self.media)
        digest=sha256_file(self.media)
        report={
            'status':'SOURCE_REVIEW_REQUIRED','path':str(self.media),
            'sha256':digest,'expected_sha256':self.legacy.package.source_sha,
            'video_id':'aUgESZsOGmY',
        }
        atomic_write(self.media.parent/'download_report.json',report)
        self.legacy.state['download_history']=[report]
        self.legacy.state['media_sha256']=digest
        self.legacy.state['media_mode']='ALTERNATE_REVIEW_SOURCE'
        self.legacy.state['source_association']={
            'status':'HUMAN_ACCEPTED_FOR_PREVIEWS_ONLY',
            'actual_media_sha256':digest,
            'analyzer_source_sha256':self.legacy.package.source_sha,
            'download_report':str(self.media.parent/'download_report.json')}
        self.legacy.save()
        destination=import_existing_project(self.legacy.dir,self.root/'output'/'projects')
        restored=Project(destination)
        self.assertEqual(restored.active_media_sha(),digest)
        self.assertEqual(sha256_file(restored.verified_media()),digest)
        self.assertEqual(restored.state['download_history'][0]['path'],
                         str(destination/'downloads'/'attempts'/'test'/'source.mp4'))
        self.assertEqual(json.loads((destination/'downloads'/'attempts'/'test'/'download_report.json').read_text())['path'],
                         str(destination/'downloads'/'attempts'/'test'/'source.mp4'))


if __name__ == '__main__':
    unittest.main()
