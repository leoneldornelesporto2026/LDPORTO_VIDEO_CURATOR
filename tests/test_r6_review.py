"""Verified R6 second-curation selection tests. No video, inference or Tk display."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from ldporto_studio.r6_review import read_analyzer_review, make_editorial_draft, export_editorial_draft
from ldporto_studio.__main__ import main


def _raw(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True).encode('utf-8')


def make_valid_r6_delivery(root):
    """Minimal true-format envelope accepted by the independent Curator inspector."""
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    sha='a'*64
    candidates=[
        {
            'candidate_id':'CAND_001','rank':1,'start':12.0,'end':28.0,
            'transcript_literal':'Trecho original da análise para revisão.',
            'generated_copy':{'title_idea':'GANCHO ORIGINAL DO ANALYZER', 'hook_idea':'HOOK ORIGINAL'},
            'camera_feasibility':'source_preserving_only','editorial_score_final':0.61,
            'clean_opening':True,'clean_ending':None,'context_requirement':'required',
            'candidate_state':'EDITORIAL_CANDIDATE','content_type':'editorial_content',
            'default_shortlist_eligible':True,'publication_eligible':None,
            'caption_preflight':{'status':'needs_review','reason_codes':['asr_uncertain']},
            'camera_handoff_ref':'camera/candidate_camera_plans.json',
        },
        {
            'candidate_id':'CAND_002','rank':2,'start':31.4,'end':50.3,
            'transcript_literal':'Outro trecho para revisão.',
            'candidate_state':'PROVISIONAL_UPSTREAM_INCOMPLETE',
            'content_type':'commercial_promotion',
            'default_shortlist_eligible':False,'publication_eligible':False,
            'caption_preflight':{'status':'blocked','reason_codes':['commercial']},
        },
    ]
    payloads={
        'source/metadata.json':_raw({'sha256':sha,'duration':120.0}),
        'CURATION_INDEX.json':_raw({
            'source':{'title':'Banda sintética ao vivo','url':'https://example.org/video'},
            'candidate_count':2,'run_id':'R6_SYNTHETIC'}),
        'SECOND_CURATOR_BRIEF.json':_raw({
            'task':'second_editorial_curation','candidate_count':2}),
        'editorial/candidate_catalog.json':_raw({'candidates':candidates}),
        'editorial/default_shortlist.json':_raw({'candidate_ids':['CAND_001']}),
        'social/stories_manifest.json':_raw({'stories':[]}),
        'camera/candidate_camera_plans.json':_raw({'candidates':[]}),
    }
    manifest={
        'run_id':'R6_SYNTHETIC','source_hash':sha,
        'analysis_status':'partial','preview_approved':False,
        'publication_ready':False,
        'files':[{'path':name,'bytes':len(data),'sha256':sha256(data).hexdigest()}
                 for name,data in payloads.items()],
    }
    package=root/'SECOND_CURATION_PARTIAL_SYNTHETIC.zip'
    with ZipFile(package,'w',ZIP_DEFLATED) as archive:
        for name,data in payloads.items():
            archive.writestr(name,data)
        archive.writestr('SECOND_CURATION_MANIFEST.json',_raw(manifest))
    package_sha=sha256(package.read_bytes()).hexdigest()
    receipt={
        'curator_import_status':'CURATOR_IMPORT_PENDING',
        'human_approval':False,'publication_ready':False,
        'run_id':manifest['run_id'],'source_sha256':sha,
        'reel_candidate_count':len(candidates),
        'zip':{'name':package.name,'bytes':package.stat().st_size,'sha256':package_sha},
    }
    (root/'ANALYZER_TO_CURATOR_HANDOFF.json').write_bytes(_raw(receipt))
    return package


class R6ReviewAdapterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='ldporto_r6_test_')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.inbox=self.root/'input'/'analyzer'/'synthetic'/'R6_SYNTHETIC'
        self.package=make_valid_r6_delivery(self.inbox)

    def test_valid_r6_has_real_candidates_and_zero_stories(self):
        review=read_analyzer_review(self.inbox)
        self.assertEqual(review['candidate_count'],2)
        self.assertEqual(review['story_candidate_count'],0)
        self.assertEqual(review['default_shortlist_ids'],['CAND_001'])
        self.assertFalse(review['render_ready'])
        self.assertEqual(review['curator_import_status'],'CURATOR_IMPORT_PENDING')
        self.assertEqual(review['candidates'][0]['title_suggestion'],'GANCHO ORIGINAL DO ANALYZER')
        self.assertIn('upstream_incomplete',review['candidates'][1]['blockers'])
        self.assertIn('camera_requires_source_preservation_or_review',
                      review['candidates'][0]['blockers'])
        self.assertEqual(review['candidates'][0]['generated_hook_idea'],'HOOK ORIGINAL')
        self.assertEqual(review['candidates'][0]['editorial_score_final'],0.61)

    def test_draft_contains_only_explicit_selection_and_never_approval(self):
        review=read_analyzer_review(self.inbox)
        draft=make_editorial_draft(review,['CAND_001'],{
            'CAND_001':{'title':'TÍTULO REVISADO',
                        'layout':'smart_zoom','notes':'Checar guitarra e rosto'}})
        self.assertEqual(draft['selected_reel_count'],1)
        self.assertEqual(draft['selected_story_count'],0)
        self.assertEqual(draft['source_story_candidate_count'],0)
        clip=draft['selected_reels'][0]
        self.assertEqual(clip['source_candidate_id'],'CAND_001')
        self.assertEqual(clip['source_start'],12.0)
        self.assertEqual(clip['source_end'],28.0)
        self.assertEqual(clip['layout'],'smart_zoom')
        self.assertFalse(clip['title_needs_review'])
        self.assertEqual(clip['evidence']['camera_feasibility'],'source_preserving_only')
        self.assertFalse(clip['camera_reviewed'])
        self.assertFalse(clip['preview_approved'])
        self.assertFalse(draft['render_ready'])
        self.assertFalse(draft['publication_ready'])
        self.assertFalse(draft['contains_video'])
        self.assertFalse(draft['human_approved'])
        self.assertNotIn('project.json',json.dumps(draft))

    def test_never_preselects_the_first_pass_shortlist(self):
        review=read_analyzer_review(self.inbox)
        with self.assertRaisesRegex(ValueError,'Selecione explicitamente'):
            make_editorial_draft(review,[])
        self.assertEqual(len(review['default_shortlist_ids']),1)

    def test_keeps_blocked_candidates_marked_for_human_review(self):
        review=read_analyzer_review(self.inbox)
        draft=make_editorial_draft(review,['CAND_002'])
        clip=draft['selected_reels'][0]
        self.assertIn('commercial_content_review',clip['evidence']['blockers'])
        self.assertIn('publication_eligible_false',clip['evidence']['blockers'])
        self.assertEqual(clip['status'],'REVIEW_REQUIRED')
        self.assertTrue(clip['title_needs_review'])

    def test_rejects_duplicates_unknown_ids_bad_layouts(self):
        review=read_analyzer_review(self.inbox)
        for ids,kwargs in (
            (['CAND_001','CAND_001'],{}),
            (['not_exported'],{}),
            (['CAND_001'],{'CAND_001':{'layout':'unsafe_auto_publish'}}),
        ):
            with self.assertRaises(ValueError):
                make_editorial_draft(review,ids,kwargs)

    def test_revisions_are_idempotent_and_source_is_immutable(self):
        review=read_analyzer_review(self.inbox)
        media_before=self.package.read_bytes()
        root=self.root/'output'/'scripts'
        first=export_editorial_draft(review,['CAND_001'],destination_root=root)
        again=export_editorial_draft(review,['CAND_001'],destination_root=root)
        self.assertEqual(first,again)
        updated=export_editorial_draft(
            review,['CAND_001'],overrides={'CAND_001':{'layout':'solo_fit'}},
            destination_root=root)
        self.assertNotEqual(first,updated)
        self.assertEqual(self.package.read_bytes(),media_before)
        self.assertTrue(first.is_file())
        self.assertTrue(updated.is_file())
        self.assertEqual(len(list(root.rglob('R6_REVIEW_*.json'))),2)
        self.assertNotIn(str(self.inbox),updated.read_text(encoding='utf-8'))

    def test_altered_zip_is_rejected_before_any_review(self):
        self.package.write_bytes(self.package.read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'zip_bytes_mismatch'):
            read_analyzer_review(self.inbox)

    def test_cli_r6_review_without_workdir(self):
        capture=StringIO()
        with redirect_stdout(capture):
            code=main(['r6-review','--inbox',str(self.inbox)])
        self.assertEqual(code,0)
        parsed=json.loads(capture.getvalue())
        self.assertEqual(parsed['candidate_count'],2)
        self.assertNotIn('transcript_excerpt',parsed['candidates'][0])

    def test_cli_draft_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError,'confirm-review-draft'):
            main(['r6-draft','--inbox',str(self.inbox),'--ids','CAND_001'])

    def test_cli_draft_only_exports_selection(self):
        with patch('ldporto_studio.r6_review.export_editorial_draft',
                   return_value=self.root/'output'/'scripts'/'R6_REVIEW_DEMO.json') as fake:
            capture=StringIO()
            with redirect_stdout(capture):
                code=main(['r6-draft','--inbox',str(self.inbox),
                           '--ids','CAND_001','--confirm-review-draft'])
        self.assertEqual(code,0)
        self.assertEqual(fake.call_args.args[1],['CAND_001'])
        result=json.loads(capture.getvalue())
        self.assertFalse(result['render_ready'])
        self.assertEqual(result['selected_reels'],1)


if __name__=='__main__':
    unittest.main()
