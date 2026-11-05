"""Safe Analyzer R6 -> Curator editorial DRAFT bridge, no false R57 import.

Opens an existing *validated* Analyzer inbox delivery and presents its real
candidates for explicit second-curation selection. Exports only JSON instructions
to output/scripts/, never media or fake assets. It cannot approve previews,
declare publication readiness, or replace any existing R57 Studio project.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile

from .analyzer_inbox import inspect_delivery
from .core import atomic_write, fingerprint, now
from .workspace import application_root

MAX_MEMBER = 24 * 1024 * 1024
LAYOUTS = frozenset(('preserve', 'center_crop', 'solo_fit', 'smart_zoom'))
SAFE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')


def _read_json_member(archive: ZipFile, name: str):
    info = archive.getinfo(name)
    if info.file_size < 0 or info.file_size > MAX_MEMBER:
        raise ValueError('Membro R6 excede limite: ' + name)
    return json.loads(archive.read(name))


def _seconds(value, key: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Timestamp inválido: ' + key)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Timestamp não finito: ' + key)
    return result


def _label(row):
    # Official Analyzer R6 stores copy in generated_copy.title_idea.
    # Older exports can use social_copy or a top-level title_idea.
    generated = row.get('generated_copy')
    suggested = generated.get('title_idea') if isinstance(generated, dict) else None
    if not isinstance(suggested, str) or not suggested.strip():
        copy = row.get('social_copy')
        suggested = copy.get('title_idea') if isinstance(copy, dict) else None
    if not isinstance(suggested, str) or not suggested.strip():
        suggested = row.get('title_idea')
    if isinstance(suggested, str) and suggested.strip():
        return ' '.join(suggested.split())[:130]
    return 'TÍTULO A REVISAR — ' + row['candidate_id']


def _slug(value):
    import unicodedata
    clean = unicodedata.normalize('NFKD', str(value)).encode('ascii','ignore').decode('ascii')
    return re.sub('[^a-z0-9]+', '-', clean.lower()).strip('-')[:65] or 'show'


def read_analyzer_review(folder) -> dict:
    """All source bytes are verified by inspect_delivery before parsing candidates."""
    folder = Path(folder).expanduser().resolve()
    inspected = inspect_delivery(folder)
    zip_path = Path(inspected['package_path'])
    with ZipFile(zip_path) as archive:
        metadata = _read_json_member(archive,'source/metadata.json')
        index = _read_json_member(archive,'CURATION_INDEX.json')
        catalog = _read_json_member(archive,'editorial/candidate_catalog.json')
        manifest = _read_json_member(archive,'SECOND_CURATION_MANIFEST.json')
        shortlist = _read_json_member(archive,'editorial/default_shortlist.json')
        stories = _read_json_member(archive,'social/stories_manifest.json') if 'social/stories_manifest.json' in archive.namelist() else {}
    source_sha = metadata.get('sha256')
    if not isinstance(source_sha, str) or not re.fullmatch('[a-fA-F0-9]{64}',source_sha):
        raise ValueError('SHA256 da fonte R6 inválido')
    duration = _seconds(metadata.get('duration'), 'duration')
    if duration<=0:raise ValueError('Duração da mídia R6 inválida')
    entries = catalog.get('candidates')
    if not isinstance(entries,list) or len(entries)!=index.get('candidate_count'):
        raise ValueError('Contagem de candidatos R6 incompatível')
    candidates=[]
    seen=set()
    for rank,row in enumerate(entries,1):
        if not isinstance(row,dict):
            raise ValueError('Candidato R6 inválido')
        cid=row.get('candidate_id')
        if not isinstance(cid,str) or not SAFE_ID.fullmatch(cid) or cid in seen:
            raise ValueError('ID de candidato R6 duplicado/inseguro')
        seen.add(cid)
        start = _seconds(row.get('start'),'start')
        end = _seconds(row.get('end'),'end')
        if not 0 <= start < end <= duration+0.001:
            raise ValueError('Candidato fora da duração: '+cid)
        text = row.get('transcript_literal')
        if not isinstance(text,str):text=''
        caption = row.get('caption_preflight')
        caption = caption if isinstance(caption,dict) else {}
        content_type = row.get('content_type')
        if not isinstance(content_type,str):content_type='uncertain'
        candidate_state=row.get('candidate_state')
        if not isinstance(candidate_state,str):candidate_state='UNVERIFIED'
        blockers=[]
        if row.get('publication_eligible') is False:blockers.append('publication_eligible_false')
        if row.get('default_shortlist_eligible') is False:blockers.append('shortlist_eligible_false')
        if candidate_state=='PROVISIONAL_UPSTREAM_INCOMPLETE':blockers.append('upstream_incomplete')
        if content_type in ('advertisement','commercial_promotion','sponsor_read','merchandising'):
            blockers.append('commercial_content_review')
        if caption.get('status') not in ('ready','verified','approved'):
            blockers.append('captions_unverified')
        editorial_blockers = row.get('editorial_blockers')
        if isinstance(editorial_blockers,list) and editorial_blockers:
            blockers.append('editorial_blockers_recorded')
        if row.get('camera_feasibility') in ('unavailable','source_preserving_only'):
            blockers.append('camera_requires_source_preservation_or_review')
        score = row.get('editorial_score_final')
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score):
            score=None
        generated_copy = row.get('generated_copy')
        hook = generated_copy.get('hook_idea') if isinstance(generated_copy,dict) else None
        if not isinstance(hook,str):
            hook=''
        candidates.append({
            'candidate_id':cid,'rank':int(row.get('rank') or rank),
            'start':round(start,3),'end':round(end,3),
            'duration_seconds':round(end-start,3),
            'title_suggestion':_label(row),
            'transcript_excerpt':text[:3000],
            'content_type':content_type,
            'candidate_state':candidate_state,
            'editorial_score_final':score,
            'generated_hook_idea':hook[:300],
            'context_requirement':row.get('context_requirement'),
            'camera_feasibility':row.get('camera_feasibility'),
            'clean_opening':row.get('clean_opening'),
            'clean_ending':row.get('clean_ending'),
            'editorial_blockers':editorial_blockers[:20] if isinstance(editorial_blockers,list) else [],
            'shortlist_eligible':row.get('default_shortlist_eligible'),
            'publication_eligible':row.get('publication_eligible'),
            'caption_preflight':{'status':caption.get('status'),
                                 'reason_codes':caption.get('reason_codes') or []},
            'camera_handoff_ref':row.get('camera_handoff_ref'),
            'blockers':blockers,
            'requires_editorial_review':True,
        })
    shortlist_rows=shortlist.get('candidate_ids') if isinstance(shortlist,dict) else []
    shortlist_ids=[cid for cid in shortlist_rows if cid in seen] if isinstance(shortlist_rows,list) else []
    story_rows=stories.get('stories',[]) if isinstance(stories,dict) else []
    story_count=len(story_rows) if isinstance(story_rows,list) else 0
    source = index.get('source') if isinstance(index.get('source'),dict) else {}
    title=source.get('title') if isinstance(source.get('title'),str) else None
    return {
        'schema_version':'ldporto-analyzer-r6-review-1.0',
        'type':'ANALYZER_R6_REVIEW_INPUT',
        'inbox_folder':str(folder),
        'source':{
            'title':(title or 'Show sem título — '+source_sha[:12])[:150],
            'url':source.get('url') if isinstance(source.get('url'),str) else None,
            'source_sha256':source_sha.lower(),
            'duration_seconds':duration,
            'run_id':str(manifest.get('run_id') or ''),
            'analysis_state':manifest.get('analysis_status') or 'partial',
            'zip_sha256':inspected['zip_sha256'],
        },
        'candidate_count':len(candidates),
        'story_candidate_count':story_count,
        'default_shortlist_ids':shortlist_ids,
        'candidates':candidates,
        'review_required':True,
        'render_ready':False,
        'curator_import_status':'CURATOR_IMPORT_PENDING',
    }


def make_editorial_draft(review:dict, candidate_ids, overrides=None) -> dict:
    """Only user-selected candidates; no automatic publication or inferred facts."""
    overrides=overrides or {}
    if not isinstance(overrides,dict):
        raise ValueError('Overrides de edição inválidos')
    if not candidate_ids or not isinstance(candidate_ids,(list,tuple)):
        raise ValueError('Selecione explicitamente um ou mais candidatos')
    by_id={row['candidate_id']:row for row in review['candidates']}
    selected=[]
    seen=set()
    for i,cid in enumerate(candidate_ids,1):
        if cid in seen or cid not in by_id:
            raise ValueError('Candidato inexistente ou duplicado: '+str(cid))
        seen.add(cid)
        row=by_id[cid]
        edits=overrides.get(cid,{})
        if not isinstance(edits,dict) or set(edits)-{'title','layout','notes'}:
            raise ValueError('Edição de candidato inválida: '+str(cid))
        layout=edits.get('layout','preserve')
        if layout not in LAYOUTS:
            raise ValueError('Modo de enquadramento inválido: '+str(layout))
        title=edits.get('title',row['title_suggestion'])
        if not isinstance(title,str) or not title.strip() or len(title.strip())>130:
            raise ValueError('Título inválido para: '+str(cid))
        note=edits.get('notes','')
        if not isinstance(note,str) or len(note)>2000:
            raise ValueError('Observação muito longa para: '+str(cid))
        selected.append({
            'id':f'REEL_{i:02d}', 'source_candidate_id':cid,
            'rank_from_analyzer':row['rank'],
            'source_start':row['start'],'source_end':row['end'],
            'duration_seconds':row['duration_seconds'],
            'title':title.strip(),'title_needs_review':('title' not in edits),
            'layout':layout,'center_x':0.5,
            'camera_reviewed':False,
            'captions_enabled':False,'captions_verified':False,
            'audio_reviewed':False,'rights_verified':False,
            'preview_approved':False,
            'evidence':{
                'transcript_excerpt':row['transcript_excerpt'],
                'content_type':row['content_type'],
                'candidate_state':row['candidate_state'],
                'caption_preflight':row['caption_preflight'],
                'camera_handoff_ref':row['camera_handoff_ref'],
                'camera_feasibility':row['camera_feasibility'],
                'editorial_score_final':row['editorial_score_final'],
                'generated_hook_idea':row['generated_hook_idea'],
                'context_requirement':row['context_requirement'],
                'clean_opening':row['clean_opening'],
                'clean_ending':row['clean_ending'],
                'editorial_blockers':row['editorial_blockers'],
                'blockers':row['blockers'],
            },
            'editorial_notes':note,
            'status':'REVIEW_REQUIRED',
        })
    src=review['source']
    return {
        'schema_version':'ldporto-curator-r6-draft-1.0',
        'type':'SECOND_CURATION_DRAFT_NOT_R57_EXECUTION',
        'source':{key:src[key] for key in
                  ('title','url','source_sha256','duration_seconds','run_id',
                   'analysis_state','zip_sha256')},
        'analyzer_candidate_count':review['candidate_count'],
        'selected_reel_count':len(selected),
        'source_story_candidate_count':review['story_candidate_count'],
        'selected_story_count':0,
        'selected_reels':selected,
        'selected_stories':[],
        'next_step':'Prepare verified R57-compatible assets and individual preview review before rendering',
        'requirements':['human_editorial_review','original_media_SHA_review',
                        'camera_inspection','caption_alignment',
                        'R57_contract_conversion','preview_approval','rights_verification'],
        'curator_import_status':'CURATOR_IMPORT_PENDING',
        'render_ready':False,'publication_ready':False,'human_approved':False,
        'contains_video':False,'contains_audio':False,
    }


def export_editorial_draft(review:dict,candidate_ids,overrides=None,destination_root=None) -> Path:
    """Content-addressed revision. Identical selections are idempotent."""
    document=make_editorial_draft(review,candidate_ids,overrides)
    src=review['source']
    root=Path(destination_root).expanduser().resolve() if destination_root else application_root()/'output'/'scripts'
    folder=root/(_slug(src['title'])+'_'+src['source_sha256'][:12])
    digest=fingerprint(document)[:16]
    target=folder/('R6_REVIEW_'+digest+'.json')
    if target.exists():
        existing=json.loads(target.read_text(encoding='utf-8'))
        if fingerprint(existing)!=fingerprint(document):
            raise ValueError('Conflito em revisão existente; original preservado')
        return target
    atomic_write(target,document)
    return target
