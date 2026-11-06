"""Automated smoke ID choice only: never promote Analyzer proposals to approved cuts."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ldporto_studio.__main__ import main
from ldporto_studio.r6_review import read_analyzer_review
from ldporto_studio.r6_smoke import pick_smoke_candidates, run_r6_smoke
from test_r6_review import make_valid_r6_delivery


class R6SmokeTests(unittest.TestCase):
    def setUp(self):
        root=tempfile.TemporaryDirectory(prefix='ldporto_smoke_')
        self.addCleanup(root.cleanup)
        self.root=Path(root.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO001'/'RUN001'
        self.package=make_valid_r6_delivery(self.inbox)
        self.review=read_analyzer_review(self.inbox)

    def test_picks_real_distinct_ids_without_promising_eligibility(self):
        for row in self.review['candidates']:
            row['publication_eligible']=False
            row['blockers'].append('publication_eligible_false')
        selected=pick_smoke_candidates(self.review,2)
        self.assertEqual(set(selected),{'CAND_001','CAND_002'})
        self.assertEqual(selected[0],'CAND_001')
        self.assertTrue(all(self.review['candidates'][i]['publication_eligible'] is False
                            for i in range(2)))

    def test_count_requires_one_to_five(self):
        for count in (0,-1,6,True,1.2,"2"):
            with self.assertRaises(ValueError):
                pick_smoke_candidates(self.review,count)

    def test_refuses_duplicate_or_overlapping_intervals(self):
        clone=dict(self.review['candidates'][0],candidate_id='CAND_ALT',rank=99)
        self.review['candidates']=[self.review['candidates'][0],clone]
        with self.assertRaisesRegex(ValueError,'intervalos distintos'):
            pick_smoke_candidates(self.review,2)

    def test_smoke_writes_ignored_separate_draft_and_runs_preflight(self):
        original=self.package.read_bytes()
        result=run_r6_smoke(self.inbox,2,self.root/'output'/'r6_smoke')
        self.assertEqual(result['status'],'SMOKE_PASSED_WITH_PENDING_HUMAN_REVIEWS')
        self.assertEqual(result['auto_test_selected_count'],2)
        self.assertFalse(result['render_ready'])
        self.assertFalse(result['human_approved'])
        self.assertFalse(result['media_created'])
        self.assertEqual(result['preflight']['selected_count'],2)
        self.assertEqual(result['preflight']['inspection_status'],
                         'VALID_DRAFT_WITH_PENDING_REVIEWS')
        self.assertFalse(result['preflight']['render_ready'])
        file=Path(result['draft_path'])
        self.assertIn('r6_smoke',file.parts)
        self.assertTrue(file.is_file())
        self.assertFalse((self.root/'output'/'scripts').exists())
        data=json.loads(file.read_text(encoding='utf-8'))
        self.assertEqual(data['selection_origin'],'AUTOMATED_TECHNICAL_SMOKE_TEST_ONLY')
        self.assertFalse(data['editorial_selection_confirmed'])
        self.assertTrue(data['do_not_publish_or_render'])
        self.assertEqual(data['selected_reel_count'],2)
        self.assertEqual(data['source_story_candidate_count'],0)
        self.assertTrue(all(clip['preview_approved'] is False for clip in data['selected_reels']))
        self.assertEqual(original,self.package.read_bytes())

    def test_repeating_smoke_does_not_duplicate_file(self):
        first=run_r6_smoke(self.inbox,1,self.root/'output'/'r6_smoke')
        next=run_r6_smoke(self.inbox,1,self.root/'output'/'r6_smoke')
        self.assertEqual(first['draft_path'],next['draft_path'])
        self.assertEqual(len(list((self.root/'output').rglob('SMOKE_R6_*.json'))),1)

    def test_cli_smoke_no_ids_no_prompts_no_media(self):
        with patch('ldporto_studio.r6_smoke.application_root',return_value=self.root):
            out=StringIO()
            with redirect_stdout(out):
                status=main(['r6-smoke','--inbox',str(self.inbox)])
        self.assertEqual(status,0)
        result=json.loads(out.getvalue())
        self.assertEqual(result['auto_test_selected_count'],2)
        self.assertFalse(result['render_ready'])
        self.assertEqual(len(result['test_candidate_ids']),2)
        self.assertTrue(Path(result['draft_path']).is_file())


if __name__=='__main__':
    unittest.main()
