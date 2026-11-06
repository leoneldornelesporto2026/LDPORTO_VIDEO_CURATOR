"""R6 review: searchable catalog, duplicate visibility and conservative preflight.

Pure helper logic for the GUI and CLI. Produces no edits to the original R6
archive, no media, no renders, no R57 approval, and no silent shortlist.
"""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

from .core import sha256_file
from .r6_review import read_analyzer_review

FILTERS = {
    'all': 'Todos os candidatos',
    'shortlist': 'Shortlist do Analyzer (não aprovada)',
    'with_title': 'Com título sugerido',
    'duration_15_90': 'Duração de 15 a 90 segundos',
    'non_commercial': 'Sem alerta comercial explícito',
    'fewest_blockers': 'Até 3 alertas registrados',
}

def _interval_key(candidate):
    # Interval identity is based on exact video timing at millisecond precision.
    return (round(float(candidate['start']), 3),round(float(candidate['end']), 3))

def summarize_review(review):
    candidates=review['candidates']
    ranges=Counter(_interval_key(row) for row in candidates)
    shortlist=set(review.get('default_shortlist_ids') or [])
    return {
        'candidate_count':len(candidates),
        'story_candidate_count':review['story_candidate_count'],
        'shortlist_count':sum(row['candidate_id'] in shortlist for row in candidates),
        'same_interval_alternates':sum(count-1 for count in ranges.values() if count>1),
        'unique_intervals':len(ranges),
        'titles_to_review':sum(row['title_suggestion'].startswith('TÍTULO A REVISAR') for row in candidates),
        'with_explicit_blockers':sum(bool(row.get('blockers')) for row in candidates),
        'publication_eligible_false':sum(row.get('publication_eligible') is False for row in candidates),
        'caption_alerts':sum('captions_unverified' in row.get('blockers',[]) for row in candidates),
        'camera_alerts':sum('camera_requires_source_preservation_or_review' in row.get('blockers',[]) for row in candidates),
        'render_ready':False,
    }

def select_visible_candidates(review,filter_key='all',query='',collapse_duplicates=False):
    """Filters VIEW only; does not select cuts or change approval state."""
    if filter_key not in FILTERS:
        raise ValueError('Filtro R6 inválido')
    phrase=str(query or '').strip().casefold()
    shortlist=set(review.get('default_shortlist_ids') or [])
    seen_intervals=set()
    out=[]
    for row in review['candidates']:
        if filter_key=='shortlist' and row['candidate_id'] not in shortlist:
            continue
        if filter_key=='with_title' and row['title_suggestion'].startswith('TÍTULO A REVISAR'):
            continue
        if filter_key=='duration_15_90' and not 15<=row['duration_seconds']<=90:
            continue
        if filter_key=='non_commercial' and ('commercial_content_review' in row.get('blockers',[]) or
                                             row.get('content_type') in
                                             ('commercial_promotion','advertisement','sponsor_read','merchandising')):
            continue
        if filter_key=='fewest_blockers' and len(row.get('blockers',[]))>3:
            continue
        if phrase and not any(phrase in str(row.get(key) or '').casefold() for key in (
                'candidate_id','title_suggestion','transcript_excerpt','generated_hook_idea','content_type')):
            continue
        interval=_interval_key(row)
        if collapse_duplicates and interval in seen_intervals:
            continue
        seen_intervals.add(interval)
        out.append(row)
    return out

def _validated_draft(data):
    if not isinstance(data,dict) or data.get('type')!='SECOND_CURATION_DRAFT_NOT_R57_EXECUTION':
        raise ValueError('Arquivo não é um roteiro R6 do Curator')
    if data.get('render_ready') is not False or data.get('publication_ready') is not False:
        raise ValueError('Roteiro afirma indevidamente render/publicação pronta')
    if data.get('human_approved') is not False or data.get('contains_video') is not False:
        raise ValueError('Roteiro afirma indevidamente aprovação/mídia')
    selected=data.get('selected_reels')
    if not isinstance(selected,list) or not selected:
        raise ValueError('Roteiro sem Reels selecionados')
    return selected

def preflight_editorial_draft(draft_file, inbox_directory, media_file=None):
    """Validate draft against the CURRENT R6 origin, including SHA256.

    Never declares render-ready: the R6->R57 asset/Story contract and human
    video/audio/caption verification are still pending. The optional media SHA
    check is exact identity only; similarity/duration are NOT inferred.
    """
    p=Path(draft_file).expanduser().resolve()
    if not p.is_file() or p.stat().st_size > 3*1024*1024:
        raise ValueError('Roteiro inexistente ou acima do limite')
    data=json.loads(p.read_text(encoding='utf-8'))
    rows=_validated_draft(data)
    review=read_analyzer_review(inbox_directory)
    source=data.get('source') or {}
    if not isinstance(source,dict):
        raise ValueError('Proveniência do roteiro inválida')
    current=review['source']
    for key in ('source_sha256','zip_sha256','run_id'):
        if source.get(key)!=current.get(key):
            raise ValueError('Proveniência divergente do R6: '+key)
    by_id={item['candidate_id']:item for item in review['candidates']}
    pending=[]
    checked=[]
    seen=set()
    warnings=[]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict):
            raise ValueError('Corte inválido no roteiro')
        cid=row.get('source_candidate_id')
        if cid not in by_id or cid in seen:
            raise ValueError('ID inexistente/duplicado no roteiro: '+str(cid))
        seen.add(cid)
        original=by_id[cid]
        for key,new in (('source_start','start'),('source_end','end')):
            value=row.get(key)
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
                raise ValueError('Tempo inválido no roteiro: '+str(cid))
            if abs(float(value)-float(original[new]))>0.001:
                raise ValueError('Timestamp diverge do Analyzer: '+str(cid))
        for flag in ('preview_approved','captions_verified','captions_enabled',
                     'camera_reviewed','audio_reviewed','rights_verified'):
            if row.get(flag) is not False:
                raise ValueError('O roteiro possui revisão/aprovação indevida: '+str(cid)+'/'+flag)
        if row.get('id')!=f'REEL_{i:02d}':
            raise ValueError('Sequência de ID de Reel divergente: '+str(cid))
        if row.get('layout') not in ('preserve','center_crop','solo_fit','smart_zoom'):
            raise ValueError('Layout inválido no roteiro: '+str(cid))
        flags=list(original.get('blockers') or [])
        if row.get('title_needs_review'):
            flags.append('title_unreviewed')
        if row.get('layout')!='preserve':
            flags.append('requested_crop_requires_visual_verification')
        checked.append({'id':row.get('id'),'source_candidate_id':cid,'start':original['start'],
                        'end':original['end'],'review_flags':flags})
        pending.extend(flags)
    intervals=Counter(_interval_key(by_id[cid]) for cid in seen)
    duplicate_intervals=sum(count-1 for count in intervals.values() if count>1)
    windows=sorted((item['start'],item['end']) for item in checked)
    overlap_pairs=sum(1 for i,a in enumerate(windows) for b in windows[i+1:]
                      if b[0]<a[1] and a[0]<b[1])
    if duplicate_intervals:
        warnings.append('selected_candidates_share_exact_source_interval')
    if overlap_pairs:
        warnings.append('selected_candidates_have_overlapping_source_timestamps')
    media={'status':'NOT_CHECKED','sha256':None,'matches_analyzer':None}
    if media_file is not None:
        file=Path(media_file).expanduser().resolve()
        if not file.is_file() or file.suffix.lower() not in ('.mp4','.mkv','.mov','.webm','.m4v'):
            raise ValueError('Fonte audiovisual ausente ou formato inválido')
        digest=sha256_file(file)
        exact=digest==current['source_sha256']
        media={'status':'EXACT_SOURCE_SHA256' if exact else 'DIFFERENT_SOURCE_SHA256_REVIEW_REQUIRED',
               'sha256':digest,'matches_analyzer':exact}
        if not exact:
            warnings.append('timestamps_and_audio_may_not_align_with_alternate_media')
    return {
        'schema_version':'ldporto-r6-editorial-preflight-1.0',
        'inspection_status':'VALID_DRAFT_WITH_PENDING_REVIEWS',
        'source_video_title':current['title'],
        'source_sha256':current['source_sha256'],
        'source_zip_sha256':current['zip_sha256'],
        'selected_count':len(rows),
        'source_story_candidate_count':review['story_candidate_count'],
        'selected_same_interval_alternates':duplicate_intervals,
        'selected_overlapping_pairs':overlap_pairs,
        'review_flag_counts':dict(sorted(Counter(pending).items())),
        'checked_reels':checked,
        'media_identity':media,
        'warnings':warnings,
        'next_step':'Prepare R57 render assets and perform manual media/audio/camera/captions verification',
        'render_ready':False,'publication_ready':False,'source_preserved':True,
    }
