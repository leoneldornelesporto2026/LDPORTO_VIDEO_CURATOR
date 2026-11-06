"""Show catalog tests: only real processed input and existing local Studio projects."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from ldporto_studio.catalog import catalog_label, discover_catalog, inspect_project, inspect_zip
from ldporto_studio.core import Project
from ldporto_studio.__main__ import main

DEMO = Path(__file__).resolve().parents[1] / 'example' / 'CURADORIA_R57.zip'


class ShowCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='ldporto_catalog_')
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)
        self.inbox=self.home/'input'
        self.projects=self.home/'output'/'projects'

    def analyzer_zip(self, name='CPM22_SEGUNDA_CURADORIA.zip'):
        path=self.inbox/'analyzer'/'cpm22'/'run_001'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            z.writestr('SECOND_CURATION_MANIFEST.json',json.dumps({
                'run_id':'run_001', 'source_hash':'a'*64,
                'workflow':{'review_state':'PARTIAL','review_ready':False}}))
            z.writestr('CURATION_INDEX.json',json.dumps({
                'source':{'title':'CPM 22 ao vivo','url':'https://www.youtube.com/watch?v=abcdefghijk'},
                'candidate_count':17,'run_id':'run_001'}))
        return path

    def test_empty_input_created_without_dummy_shows(self):
        self.assertEqual(discover_catalog(self.inbox,self.projects),[])
        self.assertTrue(self.inbox.is_dir())
        self.assertFalse(self.projects.exists())

    def test_original_editorial_zip_lists_current_12_reels_60_stories(self):
        row=inspect_zip(DEMO)
        self.assertEqual(row['kind'],'curator_zip')
        self.assertEqual(row['reels'],12)
        self.assertEqual(row['stories'],60)
        self.assertEqual(row['title'],'Charlie Brown Jr. — Planeta Atlântida 2012')
        self.assertIn('CURADORIA PRONTA',catalog_label(row))

    def test_analyzer_cpm22_displayed_without_fabricated_executable_plan(self):
        path=self.analyzer_zip()
        row=inspect_zip(path)
        self.assertEqual(row['kind'],'analyzer_zip')
        self.assertEqual(row['title'],'CPM 22 ao vivo')
        self.assertEqual(row['candidates'],17)
        self.assertIn('AGUARDANDO SEGUNDA CURADORIA',row['status'])
        items=discover_catalog(self.inbox,self.projects)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['run_id'],'run_001')

    def test_unanalyzed_mp4_and_unrelated_zip_do_not_become_shows(self):
        self.inbox.mkdir(parents=True,exist_ok=True)
        (self.inbox/'video_sem_analise.mp4').write_bytes(b'no analysis')
        with ZipFile(self.inbox/'unrelated.zip','w') as z:
            z.writestr('hello.txt','not an Analyzer or Curator package')
        self.assertEqual(discover_catalog(self.inbox,self.projects),[])

    def test_existing_project_preserved_and_listed_before_input_handoff(self):
        path=self.projects/'CURADORIA_R57_CBJR'
        project=Project.create(DEMO,path)
        self.analyzer_zip()
        rows=discover_catalog(self.inbox,self.projects)
        self.assertEqual([r['kind'] for r in rows],['project','analyzer_zip'])
        self.assertEqual(rows[0]['reels'],12)
        self.assertEqual(rows[0]['stories'],60)
        self.assertFalse(rows[0]['media_linked'])
        self.assertEqual(rows[1]['title'],'CPM 22 ao vivo')
        self.assertIsNone(project.state.get('media_path'))
        self.assertTrue((path/'project.json').exists())

    def test_cli_lists_without_modifying_projects(self):
        self.analyzer_zip()
        buffer=StringIO()
        with redirect_stdout(buffer):
            return_code=main(['catalog','--input',str(self.inbox),'--projects',str(self.projects)])
        data=json.loads(buffer.getvalue())
        self.assertEqual(return_code,0)
        self.assertEqual(data['count'],1)
        self.assertEqual(data['items'][0]['kind'],'analyzer_zip')

    def test_downloads_subtree_is_not_scanned_as_analyzer_inbox(self):
        self.inbox.mkdir(parents=True,exist_ok=True)
        source=self.inbox/'videos'/'aUgESZsOGmY'/'run01'
        source.mkdir(parents=True)
        # This file would be classified as a show outside of input/videos.
        with ZipFile(source/'accidental_edition.zip','w') as z:
            z.writestr('SECOND_CURATION_MANIFEST.json',json.dumps({
                'run_id':'run01','source_hash':'a'*64}))
            z.writestr('CURATION_INDEX.json',json.dumps({
                'source':{'title':'Do not list media staging'},'candidate_count':1}))
        self.assertEqual(discover_catalog(self.inbox,self.projects),[])

    def test_corrupted_zip_is_not_r57_ready(self):
        self.inbox.mkdir(parents=True,exist_ok=True)
        broken=self.inbox/'broken.zip'
        broken.write_bytes(b'not a zip')
        row=inspect_zip(broken)
        self.assertEqual(row['kind'],'invalid_zip')
        self.assertNotEqual(row['status'],'CURADORIA PRONTA PARA IMPORTAR')


    def test_reviewable_filter_hides_synthetic_and_zero_candidate_entries_only(self):
        from ldporto_studio.catalog import reviewable_catalog
        real_sha='0123456789abcdef' * 4
        rows=[
            {'kind':'project','id':'project','source_sha256':'','candidates':0},
            {'kind':'curator_zip','id':'r57','source_sha256':'','candidates':0},
            {'kind':'analyzer_zip','id':'live','source_sha256':real_sha,'candidates':4},
            {'kind':'analyzer_zip','id':'local','source_sha256':real_sha,'candidates':69,
             'source_url':''},
            {'kind':'analyzer_zip','id':'fixture','source_sha256':'a'*64,'candidates':1},
            {'kind':'analyzer_zip','id':'no_candidates','source_sha256':real_sha,'candidates':0},
            {'kind':'analyzer_zip','id':'missing_source','source_sha256':'','candidates':2},
            {'kind':'invalid_zip','id':'broken','source_sha256':'','candidates':0},
        ]
        before=json.dumps(rows,sort_keys=True)
        selected=reviewable_catalog(rows)
        self.assertEqual([row['id'] for row in selected],['project','r57','live','local'])
        self.assertEqual(json.dumps(rows,sort_keys=True),before)
        self.assertEqual(len(rows),8)

    def test_cli_reviewable_is_opt_in_and_does_not_hide_source_from_full_catalog(self):
        from ldporto_studio.catalog import reviewable_catalog
        self.analyzer_zip()
        default_capture=StringIO()
        with redirect_stdout(default_capture):
            code=main(['catalog','--input',str(self.inbox),'--projects',str(self.projects)])
        self.assertEqual(code,0)
        full=json.loads(default_capture.getvalue())
        self.assertEqual(full['count'],1)
        self.assertEqual(full['view'],'ALL')
        filtered_capture=StringIO()
        with redirect_stdout(filtered_capture):
            code=main(['catalog','--input',str(self.inbox),
                       '--projects',str(self.projects),'--reviewable'])
        self.assertEqual(code,0)
        filtered=json.loads(filtered_capture.getvalue())
        self.assertEqual(filtered['count'],0)  # Synthetic sha=aaaaaaaa...
        self.assertEqual(filtered['hidden_from_view'],1)
        self.assertFalse(filtered['files_modified'])
        self.assertTrue((self.inbox/'analyzer'/'cpm22'/'run_001'/
                         'CPM22_SEGUNDA_CURADORIA.zip').is_file())

    def test_gui_provides_reversible_show_all_switch(self):
        source=(Path(__file__).resolve().parents[1] /
                'ldporto_studio'/'gui.py').read_text(encoding='utf-8')
        self.assertIn('Mostrar todos (inclui testes)',source)
        self.assertIn('all_entries if include_all else reviewable_catalog(all_entries)',source)
        self.assertIn('Nenhum arquivo foi modificado.',source)


if __name__=='__main__':
    unittest.main()
