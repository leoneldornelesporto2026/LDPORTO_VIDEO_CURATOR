"""Existing R6 visual/transcript evidence reuse: never generate or approve."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image

from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_evidence_reuse import inspect_r6_evidence, export_r6_evidence
from test_r6_review import make_valid_r6_delivery


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


class R6EvidenceReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ldporto_r6_evidence_')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.inbox = self.base / 'input' / 'analyzer' / 'VIDEO123' / 'R6'
        self.zip = make_valid_r6_delivery(self.inbox)
        self.out = self.base / 'output' / 'r6_bridge'

    def _add_real_evidence(self):
        with ZipFile(self.zip) as archive:
            records = {name: archive.read(name) for name in archive.namelist()}
        catalog = json.loads(records['editorial/candidate_catalog.json'])
        catalog['candidates'][0]['visual_refs'] = [
            'visuals/CAND_001/contact_sheet.jpg']
        records['editorial/candidate_catalog.json'] = _json(catalog)
        picture = BytesIO()
        with Image.new('RGB', (32, 32), '#345678') as image:
            image.save(picture, format='JPEG')
        records['visuals/CAND_001/contact_sheet.jpg'] = picture.getvalue()
        records['transcript/transcript.srt'] = (
            '1\n00:00:12,000 --> 00:00:13,000\nTexto original ASR\n').encode('utf-8')
        records['transcript/relevant_segments.jsonl'] = (
            '{"segment_id":"S1","text":"Texto original ASR"}\n').encode('utf-8')
        manifest = json.loads(records['SECOND_CURATION_MANIFEST.json'])
        manifest['files'] = [
            {'path':name,'bytes':len(data),'sha256':sha256(data).hexdigest()}
            for name,data in records.items() if name != 'SECOND_CURATION_MANIFEST.json']
        records['SECOND_CURATION_MANIFEST.json'] = _json(manifest)
        with ZipFile(self.zip, 'w', ZIP_DEFLATED) as archive:
            for name,data in records.items():
                archive.writestr(name,data)
        receipt_file = self.inbox / 'ANALYZER_TO_CURATOR_HANDOFF.json'
        receipt = json.loads(receipt_file.read_text(encoding='utf-8'))
        receipt['zip']['bytes'] = self.zip.stat().st_size
        receipt['zip']['sha256'] = sha256(self.zip.read_bytes()).hexdigest()
        receipt_file.write_bytes(_json(receipt))

    def _draft(self):
        return export_editorial_draft(
            read_analyzer_review(self.inbox), ['CAND_001'],
            destination_root=self.base/'scripts')

    def test_inventory_reports_missing_without_creating_assets(self):
        draft=self._draft()
        result=inspect_r6_evidence(self.inbox,draft)
        self.assertEqual(result['reused_visual_count'],0)
        self.assertEqual(result['missing_visual_count'],1)
        self.assertEqual(result['files'],[])
        self.assertFalse(result['human_approved'])
        self.assertFalse(self.out.exists())

    def test_existing_contact_sheet_and_transcript_extracted_byte_identically(self):
        self._add_real_evidence()
        draft=self._draft()
        before = self.zip.read_bytes()
        report = inspect_r6_evidence(self.inbox,draft)
        self.assertEqual(report['reused_visual_count'],1)
        self.assertEqual(report['existing_transcript_count'],2)
        path=export_r6_evidence(self.inbox,draft,destination_root=self.out)
        self.assertEqual(len(report['files']),3)
        for row in report['files']:
            with ZipFile(self.zip) as archive:
                original=archive.read(row['zip_member'])
            self.assertEqual((path/row['output_relative_path']).read_bytes(),original)
        self.assertEqual(path,export_r6_evidence(self.inbox,draft,destination_root=self.out))
        self.assertEqual(self.zip.read_bytes(),before)
        self.assertFalse(list(self.out.rglob('*.mp4')))
        self.assertFalse(list(self.out.rglob('*.ass')))
        self.assertFalse(list(self.out.rglob('*.png')))
        self.assertFalse((self.base/'output'/'projects').exists())

    def test_empty_evidence_inventory_does_not_create_empty_export(self):
        draft=self._draft()
        report=inspect_r6_evidence(self.inbox,draft)
        self.assertEqual(report['status'],'NO_REUSABLE_EVIDENCE_IN_R6')
        with self.assertRaisesRegex(ValueError,'Nenhuma evidência'):
            export_r6_evidence(self.inbox,draft,destination_root=self.out)
        self.assertFalse(self.out.exists())

    def test_original_source_zip_mutated_is_blocked(self):
        self._add_real_evidence()
        draft=self._draft()
        self.zip.write_bytes(self.zip.read_bytes()+b'tamper')
        with self.assertRaises(ValueError):
            export_r6_evidence(self.inbox,draft,destination_root=self.out)
        self.assertFalse(self.out.exists())

    def test_manifest_cannot_be_misrepresented_by_untrusted_visual_ref(self):
        self._add_real_evidence()
        draft=self._draft()
        self.assertEqual(inspect_r6_evidence(self.inbox,draft)['reused_visual_count'],1)
        # Remove visual reference from validated manifest: contact sheet is not
        # attributed to the selected candidate anymore.
        with ZipFile(self.zip) as archive:
            records={name:archive.read(name) for name in archive.namelist()}
        cat=json.loads(records['editorial/candidate_catalog.json'])
        cat['candidates'][0]['visual_refs']=[]
        records['editorial/candidate_catalog.json']=_json(cat)
        manifest=json.loads(records['SECOND_CURATION_MANIFEST.json'])
        manifest['files']=[
            {'path':name,'bytes':len(data),'sha256':sha256(data).hexdigest()}
            for name,data in records.items() if name!='SECOND_CURATION_MANIFEST.json']
        records['SECOND_CURATION_MANIFEST.json']=_json(manifest)
        with ZipFile(self.zip,'w',ZIP_DEFLATED) as archive:
            for name,data in records.items():
                archive.writestr(name,data)
        receipt_file=self.inbox/'ANALYZER_TO_CURATOR_HANDOFF.json'
        receipt=json.loads(receipt_file.read_text(encoding='utf-8'))
        receipt['zip']['bytes']=self.zip.stat().st_size
        receipt['zip']['sha256']=sha256(self.zip.read_bytes()).hexdigest()
        receipt_file.write_bytes(_json(receipt))
        # Existing draft is tied to old ZIP, so even though new package is
        # internally consistent, extraction must fail closed.
        with self.assertRaises(ValueError):
            export_r6_evidence(self.inbox,draft,destination_root=self.out)

    def test_tampered_export_destination_not_replaced(self):
        self._add_real_evidence()
        draft=self._draft()
        path=export_r6_evidence(self.inbox,draft,destination_root=self.out)
        image=path/'reels'/'REEL_01'/'contact_sheet_original.jpg'
        image.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            export_r6_evidence(self.inbox,draft,destination_root=self.out)
        self.assertEqual(image.read_bytes(),b'changed')

    def test_cli_read_only_and_explicit_copy(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from ldporto_studio.__main__ import main
        self._add_real_evidence()
        draft=self._draft()
        args=['r6-evidence','--inbox',str(self.inbox),'--draft',str(draft)]
        stdout=StringIO()
        with redirect_stdout(stdout):
            status=main(args)
        self.assertEqual(status,0)
        output=json.loads(stdout.getvalue())
        self.assertEqual(output['reused_visual_count'],1)
        self.assertIsNone(output['saved_evidence_dir'])
        self.assertFalse(self.out.exists())
        with redirect_stdout(StringIO()) as capture:
            status=main(args+['--save'])
        self.assertEqual(status,0)
        saved=json.loads(capture.getvalue())['saved_evidence_dir']
        self.assertTrue(Path(saved,'EVIDENCE_REUSE_MANIFEST.json').is_file())

    def test_gui_button_requires_explicit_reel_selection(self):
        source=(Path(__file__).resolve().parents[1] /
                'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn("text='EVIDÊNCIAS R6'",source)
        self.assertIn('self.last_exported_path is None:',source)
        self.assertIn('export_r6_evidence(',source)

    def test_full_inventory_no_draft_preserves_everything(self):
        from ldporto_studio.r6_evidence_reuse import inspect_r6_inventory
        before=self.zip.read_bytes()
        result=inspect_r6_inventory(self.inbox)
        self.assertEqual(result['candidate_count'],2)
        self.assertEqual(result['available_contact_sheets'],0)
        self.assertEqual(result['available_transcript_files'],0)
        self.assertTrue(result['requires_explicit_editorial_selection'])
        self.assertTrue(all(not x['selected_for_reel'] for x in result['candidates']))
        self.assertEqual(self.zip.read_bytes(),before)
        self.assertFalse(self.out.exists())

    def test_full_inventory_real_evidence_is_reference_only(self):
        from ldporto_studio.r6_evidence_reuse import inspect_r6_inventory
        self._add_real_evidence()
        result=inspect_r6_inventory(self.inbox)
        self.assertEqual(result['available_contact_sheets'],1)
        self.assertEqual(result['unavailable_contact_sheets'],1)
        self.assertEqual(result['available_transcript_files'],2)
        self.assertEqual(result['candidates'][0]['contact_sheet_ref'],
                         'visuals/CAND_001/contact_sheet.jpg')
        self.assertEqual(len(result['candidates'][0]['contact_sheet_sha256']),64)
        self.assertFalse(result['candidates'][0]['thumbnail_ready'])
        self.assertFalse(result['transcripts']['transcript/transcript.srt']['content_reviewed'])
        self.assertFalse(result['r57_import_ready'])

    def test_inventory_refuses_modified_source_zip(self):
        from ldporto_studio.r6_evidence_reuse import inspect_r6_inventory
        self.zip.write_bytes(self.zip.read_bytes()+b'modification after receipt')
        with self.assertRaises(ValueError):
            inspect_r6_inventory(self.inbox)

    def test_cli_all_evidence_without_draft_is_safe_and_save_requires_draft(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from ldporto_studio.__main__ import main
        args=['r6-evidence','--inbox',str(self.inbox)]
        output=StringIO()
        with redirect_stdout(output):
            code=main(args)
        self.assertEqual(code,0)
        data=json.loads(output.getvalue())
        self.assertEqual(data['candidate_count'],2)
        self.assertIsNone(data['saved_evidence_dir'])
        self.assertTrue(data['requires_explicit_editorial_selection'])
        with self.assertRaisesRegex(ValueError,'informe --draft'):
            main(args+['--save'])
        self.assertFalse(self.out.exists())

    def test_gui_inventory_requires_no_selection_or_export(self):
        source=(Path(__file__).resolve().parents[1]/
                'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('INVENTÁRIO R6 (SEM SELEÇÃO)',source)
        # Inspect the AST node, not the text between two method names.
        # The GUI may add methods between inventory and evidence export.
        import ast
        tree=ast.parse(source)
        owner=next(node for node in tree.body
                   if isinstance(node, ast.ClassDef)
                   and node.name=='AnalyzerR6ReviewDialog')
        method=next(node for node in owner.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name=='_inspect_r6_inventory')
        handler=ast.get_source_segment(source, method)
        self.assertNotIn('last_exported_path',handler)
        self.assertIn('inspect_r6_inventory(self.review',handler)

    def test_rejects_export_into_original_inbox(self):
        # Even if the R6 has no extractable evidence, an unsafe destination
        # must be refused before the empty-inventory check.
        draft=self._draft()
        with self.assertRaisesRegex(ValueError,'sobrepõe'):
            export_r6_evidence(self.inbox,draft,destination_root=self.inbox)
        self.assertFalse((self.inbox/'EVIDENCE_REUSE_MANIFEST.json').exists())

    def test_rejects_export_inside_inbox_with_real_evidence(self):
        self._add_real_evidence()
        draft=self._draft()
        before=self.zip.read_bytes()
        unsafe=self.inbox/'should_never_be_created'
        with self.assertRaisesRegex(ValueError,'sobrepõe'):
            export_r6_evidence(self.inbox,draft,destination_root=unsafe)
        self.assertFalse(unsafe.exists())
        self.assertEqual(self.zip.read_bytes(),before)
