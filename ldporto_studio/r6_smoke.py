"""One-command R6 technical smoke: auto-pick IDs, export disposable draft, preflight.

Auto selection is FOR CONTRACT TESTING ONLY. Never recommend or approve clips.
All outputs are under ignored output/r6_smoke/ (not versionable editorial scripts).
The producer ZIP, existing R57 projects, source media and approvals are untouched.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .core import atomic_write, fingerprint
from .r6_review import make_editorial_draft, read_analyzer_review
from .r6_workflow import preflight_editorial_draft
from .workspace import application_root

_MAX_SMOKE_CUTS = 5


def pick_smoke_candidates(review, count: int = 2) -> list[str]:
    """Choose stable, distinct, nonoverlapping intervals as technical test inputs.

    Ranking is only a heuristic for TEST COVERAGE, not content quality or
    suitability for publication. A review may contain zero eligible clips.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _MAX_SMOKE_CUTS:
        raise ValueError('Quantidade de testes deve estar entre 1 e 5')
    rows=review.get('candidates', [])
    if not isinstance(rows,list):
        raise ValueError('Catálogo R6 inválido')
    shortlist=set(review.get('default_shortlist_ids') or [])

    def sort_key(row):
        duration=float(row['duration_seconds'])
        is_commercial=('commercial_content_review' in row.get('blockers',[]) or
                       row.get('content_type') in ('advertisement','commercial_promotion','sponsor_read','merchandising'))
        return (
            is_commercial,
            not (15 <= duration <= 90),
            len(row.get('blockers') or []),
            row.get('candidate_id') not in shortlist,
            row.get('title_suggestion','').startswith('TÍTULO A REVISAR'),
            int(row.get('rank') or 999999),
            str(row.get('candidate_id') or ''),
        )

    chosen=[]
    for row in sorted(rows,key=sort_key):
        if len(chosen)>=count:
            break
        start,end=float(row['start']),float(row['end'])
        if any(start < prior['end'] and prior['start'] < end for prior in chosen):
            continue
        chosen.append(row)
    if len(chosen)<count:
        raise ValueError(
            'Não há intervalos distintos suficientes para testar sem sobreposição. '
            'Nada foi exportado.'
        )
    return [row['candidate_id'] for row in chosen]


def run_r6_smoke(inbox_directory, count: int = 2, output_root=None) -> dict:
    """Execute safe smoke end to end, with no ID prompt and no media render."""
    review=read_analyzer_review(inbox_directory)
    picked=pick_smoke_candidates(review,count)
    draft=make_editorial_draft(
        review,picked,{cid:{'layout':'preserve'} for cid in picked}
    )
    # Distinguish machine-selected test cases from any intentional editorial
    # selection even if someone later copies a JSON from this ignored folder.
    draft['selection_origin']='AUTOMATED_TECHNICAL_SMOKE_TEST_ONLY'
    draft['editorial_selection_confirmed']=False
    draft['do_not_publish_or_render']=True
    draft['test_provenance']={
        'rule':'unique_nonoverlapping_intervals_lowest_explicit_blockers_first',
        'note':'Test-only IDs. All Analyzer eligibility, audio, captions and camera '
               'blockers remain in the file. Not a recommendation.',
    }
    root = (Path(output_root).expanduser().resolve()
            if output_root is not None
            else application_root()/'output'/'r6_smoke')
    source_sha=review['source']['source_sha256'][:12]
    zip_sha=review['source']['zip_sha256'][:12]
    path=root/source_sha/zip_sha/('SMOKE_R6_'+fingerprint(draft)[:16]+'.json')
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(data)!=fingerprint(draft):
            raise ValueError('Conflito de roteiro técnico. Arquivo original preservado.')
    else:
        atomic_write(path,draft)

    inspection=preflight_editorial_draft(path,inbox_directory)
    if inspection['selected_count']!=len(picked) or inspection['render_ready'] is not False:
        raise ValueError('Smoke falhou na validação do conteúdo selecionado')

    return {
        'status':'SMOKE_PASSED_WITH_PENDING_HUMAN_REVIEWS',
        'source_title':review['source']['title'],
        'analyzer_candidate_count':review['candidate_count'],
        'source_story_candidate_count':review['story_candidate_count'],
        'auto_test_selected_count':len(picked),
        'test_candidate_ids':picked,
        'selection_origin':'AUTOMATED_TECHNICAL_SMOKE_TEST_ONLY',
        'draft_path':str(path),
        'preflight':inspection,
        'original_zip_sha256':review['source']['zip_sha256'],
        'render_ready':False,
        'human_approved':False,
        'media_created':False,
        'finals_created':False,
        'git_tracked_output':False,
        'next_step':'Visual editorial review and media provenance, then R6-to-renderable conversion',
    }
