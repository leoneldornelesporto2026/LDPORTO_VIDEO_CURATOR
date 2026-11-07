"""Static contracts for the Windows NASA pilot. Windows execution is still required."""
from pathlib import Path
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / 'scripts' / 'windows'
          / 'testing' / 'PILOTO_NASA_R57_RASCUNHO.ps1')


class PilotNASAContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding='utf-8-sig')

    def test_requires_explicit_candidate_and_opt_in(self):
        for value in ('[Parameter(Mandatory=$true)]','[string]$CandidateId',
                      'if (-not $ConfirmTechnicalPilot)',
                      'Where-Object { $_.id -eq $CandidateId }'):
            self.assertIn(value, self.source)

    def test_sha_and_review_flags_remain_mandatory(self):
        for value in ('Get-FileHash','--confirm-review-draft',
                      '--confirm-review-only','--confirm-preview-only',
                      'human_approved','publication_ready','r57_imported'):
            self.assertIn(value, self.source)

    def test_no_git_writes_no_media_download_or_project_import(self):
        for command in ('r6-review','r6-draft','r6-story-propose',
                        'r6-caption-drafts','r6-cover-drafts',
                        'r6-assets-prefill','r6-assets','r6-r57-preview-package'):
            self.assertIn("'" + command + "'", self.source)
        for forbidden in ('git push','git reset','git merge','git checkout',
                          'git clean','Invoke-WebRequest','Project.create('):
            self.assertNotIn(forbidden, self.source)

    def test_missing_assets_block_zip_and_zip_is_separately_confirmed(self):
        self.assertIn('if ($missing.Count -gt 0)', self.source)
        self.assertIn('elseif ($CreatePreviewZip)', self.source)
        self.assertIn('PENDENTE:', self.source)
        self.assertIn("'develop'", self.source)


if __name__ == '__main__':
    unittest.main()
