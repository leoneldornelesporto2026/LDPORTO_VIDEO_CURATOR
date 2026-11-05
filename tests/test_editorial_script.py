"""Scripts in Git; downloaded MP4s under ignored input/videos/; no media bytes in revisions."""
from __future__ import annotations
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from ldporto_studio.core import Project
from ldporto_studio.editorial_script import build_project_script,export_project_script
from ldporto_studio.youtube_download import videos_download_root, managed_download_path
from test_studio import DEMO

ROOT=Path(__file__).resolve().parents[1]

class CommitLayoutTest(unittest.TestCase):
    def test_gitignore_only_allows_scripts_in_input_and_output(self):
        original=(ROOT/'.gitignore').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='ldporto_git_scripts_') as folder:
            wd=Path(folder)
            (wd/'.gitignore').write_text(original,encoding='utf-8')
            subprocess.run(['git','init','-q'],cwd=wd,check=True)
            cases={
                'input/README.md':False,
                'output/README.md':False,
                'input/analyzer/id/run/package.zip':True,
                'input/curadorias/show/run/plano.zip':True,
                'input/videos/aUgESZsOGmY/run/source.mp4':True,
                'input/videos/aUgESZsOGmY/run/download_report.json':True,
                'output/projects/show/project.json':True,
                'output/projects/show/outputs/previews/REEL_01/a.mp4':True,
                'output/scripts/cbjr/REVISION_abc123.json':False,
                'input/scripts/show/SECOND_CURATION.md':False,
                'input/scripts/show/movie.mp4':True,
                'output/scripts/show/thumb.png':True,
                'output/scripts/show/export.zip':True,
                'output/scripts/show/.env':True,
            }
            for path,ignored in cases.items():
                result=subprocess.run(['git','check-ignore','--no-index','-q',path],
                                      cwd=wd,check=False)
                self.assertEqual(result.returncode,0 if ignored else 1,path)

    def test_script_is_text_only_with_stable_revision(self):
        with tempfile.TemporaryDirectory(prefix='ldporto_script_') as tmp:
            root=Path(tmp)
            project=Project.create(DEMO,root/'project')
            project.update('REEL_01',title='O SHOW INESQUECÍVEL',layout='solo_fit')
            built=build_project_script(project)
            self.assertEqual(built['counts'],{'reels':12,'stories':60})
            self.assertEqual(built['clips'][0]['framing']['mode'],'solo_fit')
            target=export_project_script(project,root/'output'/'scripts')
            first=target.read_bytes()
            self.assertEqual(export_project_script(project,root/'output'/'scripts'),target)
            self.assertEqual(first,target.read_bytes())
            text=first.decode('utf-8')
            self.assertNotIn(str(project.dir),text)
            self.assertNotIn('.mp4',text)
            self.assertFalse(json.loads(text)['source']['media_bytes_included'])
            project.update('REEL_01',title='OUTRA EDIÇÃO')
            revised=export_project_script(project,root/'output'/'scripts')
            self.assertNotEqual(revised,target)
            self.assertTrue(target.is_file())

    def test_legacy_downloads_and_new_input_videos_are_permitted(self):
        with tempfile.TemporaryDirectory(prefix='ldporto_media_path_') as tmp:
            root=Path(tmp)
            project=Project.create(DEMO,root/'project')
            legacy=project.dir/'downloads'/'attempts'/'abc'/'source.mp4'
            videos=root/'Videos'/'LDPORTO_VIDEO_CURATOR'
            repo_videos=root/'CuratorRepo'/'input'/'videos'
            modern=repo_videos/'aUgESZsOGmY'/project.package.digest[:12]/'abc'/'source.mp4'
            old_windows=videos/'aUgESZsOGmY'/project.package.digest[:12]/'abc'/'source.mp4'
            with patch('ldporto_studio.youtube_download.videos_download_root',
                       return_value=videos), patch(
                       'ldporto_studio.youtube_download.download_input_root',
                       return_value=repo_videos):
                self.assertTrue(managed_download_path(project,legacy,'aUgESZsOGmY'))
                self.assertTrue(managed_download_path(project,old_windows,'aUgESZsOGmY'))
                self.assertTrue(managed_download_path(project,modern,'aUgESZsOGmY'))
                self.assertFalse(managed_download_path(project,root/'elsewhere.mp4','aUgESZsOGmY'))


if __name__=='__main__':
    unittest.main()
