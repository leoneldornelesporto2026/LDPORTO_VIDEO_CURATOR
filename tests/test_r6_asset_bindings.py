"""R6 asset binding preflight: pure synthetic, no media generation or render."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_story_timeline import export_story_proposal
from ldporto_studio.r6_asset_bindings import asset_template, save_asset_template, audit_asset_bindings
from test_r6_review import make_valid_r6_delivery


class R6AssetBindingsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='ldporto_r6_assets_')
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.inbox=self.base/'input'/'analyzer'/'SYNTHETIC'/'RUN'
        self.archive=make_valid_r6_delivery(self.inbox)
        self.draft=export_editorial_draft(
            read_analyzer_review(self.inbox), ['CAND_001'],
            destination_root=self.base/'output'/'scripts')
        self.proposal=export_story_proposal(
            self.inbox, self.draft, destination_root=self.base/'output'/'r6_bridge')
        self.assets=self.base/'assets'
        self.assets.mkdir()

    def _bindings(self, complete=False):
        data=asset_template(self.inbox,self.draft,self.proposal)
        if complete:
            for row in data['clips']:
                dest=self.assets/row['kind']/row['id']
                dest.mkdir(parents=True)
                with Image.new('RGB',(32,32),'white') as im:
                    im.save(dest/'cover.png')
                (dest/'captions.ass').write_text(
                    '[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Teste\n',
                    encoding='utf-8')
                (dest/'captions.srt').write_text(
                    '1\n00:00:00,000 --> 00:00:01,000\nTeste\n', encoding='utf-8')
                row['assets'] = {key:f"{row['kind']}/{row['id']}/{filename}"
                                 for key,filename in [('thumbnail','cover.png'),
                                     ('caption_ass','captions.ass'),('caption_srt','captions.srt')]}
        target=self.base/'bindings.json'
        target.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        return target,data

    def test_template_reels_and_story_slots_no_automatic_assets(self):
        plan=asset_template(self.inbox,self.draft,self.proposal)
        self.assertEqual(plan['clip_count'],3)
        self.assertEqual([r['id'] for r in plan['clips']],['REEL_01','STORY_01','STORY_02'])
        self.assertTrue(all(not any(r['assets'].values()) for r in plan['clips']))
        self.assertFalse(plan['r57_import_ready'])

    def test_idempotence_and_original_zip_untouched(self):
        original=self.archive.read_bytes()
        dest=self.base/'output'/'r6_bridge'
        a=save_asset_template(self.inbox,self.draft,self.proposal,destination_root=dest)
        b=save_asset_template(self.inbox,self.draft,self.proposal,destination_root=dest)
        self.assertEqual(a,b)
        self.assertEqual(self.archive.read_bytes(),original)
        self.assertFalse(list(dest.rglob('*.zip')))

    def test_missing_assets_report_is_explicit_not_approval(self):
        file,_=self._bindings()
        result=audit_asset_bindings(self.inbox,self.draft,self.proposal,file,self.assets)
        self.assertEqual(result['assets_verified'],0)
        self.assertEqual(len(result['missing_assets']),9)
        self.assertFalse(result['publication_ready'])

    def test_existing_png_ass_srt_pass_structure_only(self):
        file,_=self._bindings(True)
        result=audit_asset_bindings(self.inbox,self.draft,self.proposal,file,self.assets)
        self.assertEqual(result['assets_verified'],9)
        self.assertFalse(result['r57_import_ready'])
        self.assertFalse(result['caption_alignment_verified'])
        self.assertEqual(len(result['clips'][0]['assets']['thumbnail']['sha256']),64)

    def test_traversal_or_unknown_extension_rejected(self):
        for attack in ('../escape.png','C:/Windows/escape.png',
                       'reels/REEL_01/evil.exe','reels\\REEL_01\\cover.png'):
            path,doc=self._bindings()
            doc['clips'][0]['assets']['thumbnail']=attack
            path.write_text(json.dumps(doc),encoding='utf-8')
            with self.assertRaises(ValueError):
                audit_asset_bindings(self.inbox,self.draft,self.proposal,path,self.assets)

    def test_forged_approval_and_other_clip_refused(self):
        for change in ('approval','source','clip'):
            path,doc=self._bindings()
            if change=='approval': doc['human_approved']=True
            elif change=='source': doc['provenance']['source_zip_sha256']='f'*64
            else: doc['clips'][0]['id']='REEL_99'
            path.write_text(json.dumps(doc),encoding='utf-8')
            with self.assertRaises(ValueError):
                audit_asset_bindings(self.inbox,self.draft,self.proposal,path,self.assets)

    def test_invalid_image_and_legends_rejected(self):
        path,doc=self._bindings(True)
        image=self.assets/doc['clips'][0]['assets']['thumbnail']
        image.write_bytes(b'invalid png')
        with self.assertRaises(ValueError):
            audit_asset_bindings(self.inbox,self.draft,self.proposal,path,self.assets)
        with Image.new('RGB',(32,32),'white') as im: im.save(image)
        ass=self.assets/doc['clips'][0]['assets']['caption_ass']
        ass.write_text('fake ass',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ASS'):
            audit_asset_bindings(self.inbox,self.draft,self.proposal,path,self.assets)


    def test_cli_reports_required_files_without_writing(self):
        from ldporto_studio.__main__ import main
        import io
        from contextlib import redirect_stdout
        buffer=io.StringIO()
        with redirect_stdout(buffer):
            result=main(['r6-assets','--inbox',str(self.inbox),
                         '--draft',str(self.draft),
                         '--story-proposal',str(self.proposal)])
        self.assertEqual(result,0)
        record=json.loads(buffer.getvalue())
        self.assertEqual(record['required_files'],9)
        self.assertIsNone(record['template_path'])
        self.assertFalse(record['r57_import_ready'])

    def test_gui_button_requires_an_explicit_story_proposal(self):
        file=Path(__file__).resolve().parents[1]/'ldporto_studio'/'r6_review_gui.py'
        content=file.read_text(encoding='utf-8')
        self.assertIn('CHECKLIST ASSETS R57',content)
        self.assertIn('self.last_story_proposal_path is None',content)
        self.assertIn('save_asset_template(',content)

if __name__=='__main__':
    unittest.main()
