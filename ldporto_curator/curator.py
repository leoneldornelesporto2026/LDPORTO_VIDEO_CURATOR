from __future__ import annotations
from pathlib import Path
import json, math
from .utils import load_json, write_json
from .ollama_client import review_candidates

def _overlap(a,b):
    inter=max(0,min(a['end'],b['end'])-max(a['start'],b['start']))
    small=max(0.001,min(a['end']-a['start'],b['end']-b['start']))
    return inter/small

def _segment_context(bundle,start,end):
    segs=[s for s in bundle.segments if s.get('end',0)>=start and s.get('start',1e9)<=end]
    return segs

def _snap(bundle,start,end,min_d,max_d):
    segs=bundle.segments
    if not segs: return max(0,start),min(bundle.analysis.get('metadata',{}).get('duration',end),end)
    duration=float(bundle.analysis.get('metadata',{}).get('duration') or 0)
    candidates=[s for s in segs if s.get('end',0)>=start-25 and s.get('start',1e9)<=end+25]
    if not candidates: return start,end
    # nearest sentence/segment boundary around requested times
    s0=min(candidates,key=lambda s:abs(float(s.get('start',0))-start))
    s1=min(candidates,key=lambda s:abs(float(s.get('end',0))-end))
    a=float(s0.get('start',start)); b=float(s1.get('end',end))
    if b-a<min_d:
        center=(a+b)/2; a=max(0,center-min_d/2); b=min(duration or center+min_d/2,center+min_d/2)
    if b-a>max_d:
        b=a+max_d
    return round(a,3),round(b,3)

def _title_from_text(text):
    t=' '.join((text or '').split()).strip(' .!?')
    if not t: return 'UM TRECHO QUE VALE O CORTE'
    words=t.split()[:11]
    out=' '.join(words).upper()
    return out if len(out)<=72 else out[:69]+'…'

def curate(bundle, cfg, project_root: Path, log=print):
    c=cfg.get('curation',{})
    min_d=float(c.get('min_duration',30)); max_d=float(c.get('max_duration',120)); maxn=int(c.get('max_approved_clips',12))
    second = getattr(bundle, 'second_decisions', {})
    if second:
        from .second_curation_decisions import compile_decisions
        rows = compile_decisions(second, bundle.second_package, bundle.analysis['metadata'], bundle.segments)
        decisions = []
        for row in rows[:maxn]:
            decisions.append({'clip_id': f"SECOND_{row['decision_id']}", 'rank': len(decisions) + 1,
                'source_start': row['start'], 'source_end': row['end'], 'duration': row['end'] - row['start'],
                'title_text': row['title'], 'hook_text': row['title'], 'title_style': 'IMPACTO', 'title_duration': 5.0,
                'score': None, 'reason': row['reason'], 'topic': 'second_curator', 'context_summary': '',
                'evidence_segment_ids': row['evidence_segment_ids'], 'word_ids': [], 'scene_ids': [],
                'warnings': [], **{key: row[key] for key in ('curation_source', 'candidate_ids', 'action', 'original_ranks', 'suggested_layout', 'needs_review')}})
        return decisions
    if bundle.analysis.get('second_curation_import'):
        shortlist = load_json(bundle.root / 'editorial/default_shortlist.json', {}).get('candidate_ids', [])
        rows = [r for r in bundle.second_package.get('candidates', []) if r['candidate_id'] in shortlist
                and (r.get('commercial_classification') or {}).get('eligibility') != 'excluded'
                and r.get('content_type') not in {'advertisement', 'commercial_promotion', 'sponsor_read', 'event_promotion', 'self_promotion'}]
        first = {'schema_version': '4.4.0', 'source_sha256': bundle.analysis['metadata']['sha256'], 'provider': 'manual_json',
                 'actions': [{'decision_id': f'FIRST_{index + 1}', 'action': 'approve', 'candidate_ids': [r['candidate_id']],
                              'reason': 'Seleção da primeira passagem; revisão do preview pendente.', 'title': r.get('topic') or 'Trecho selecionado'} for index, r in enumerate(rows)]}
        bundle.second_decisions = first
        decisions = curate(bundle, cfg, project_root, log)
        bundle.second_decisions = {}
        for row in decisions:
            row['curation_source'] = 'FIRST_PASS'
        return decisions
    decisions=[]
    overrides=load_json(project_root/'curation_overrides.json',{}) or {}
    imported=load_json(project_root/'.cache/active_override_import.json',{}) or {}
    if imported.get('override_path'):
        overrides={**overrides, **(load_json(imported['override_path'],{}) or {})}
    seeds=overrides.get(bundle.video_id) if c.get('use_human_overrides',True) else None
    if seeds:
        for seed in seeds[:maxn]:
            start,end=_snap(bundle,float(seed['start']),float(seed['end']),min_d,max_d)
            segs=_segment_context(bundle,start,end)
            decisions.append({
              'clip_id':f"CLIP_{len(decisions)+1:03d}",'rank':len(decisions)+1,'score':seed.get('score',90),
              'source_start':start,'source_end':end,'duration':round(end-start,3),'reason':seed.get('reason'),
              'topic':'human_curated','context_summary':' '.join(s.get('text','') for s in segs[:3])[:700],
              'hook_text':seed.get('title'),'title_text':seed.get('title'),'title_style':seed.get('style','IMPACTO'),'title_duration':5.0,
              'evidence_segment_ids':[s.get('segment_id') for s in segs], 'scene_ids':sorted({x for s in segs for x in (s.get('scene_ids') or [])}),
              'word_ids':[x for s in segs for x in (s.get('word_ids') or [])], 'warnings':[], 'needs_review':False,
              'curation_source':'MANUAL_OVERRIDE'
            })
    else:
        review_scores={x.get('moment_id'):x for x in (bundle.review.get('top_moments') or [])}
        pool=[]
        for m in bundle.editorial:
            base=float((m.get('editorial') or {}).get('score') or m.get('confidence') or 0.5)
            rr=review_scores.get(m.get('moment_id')) or {}
            rscore=float(rr.get('editorial_score') or 0)
            score=round(100*(0.58*base+0.42*rscore),1)
            start=float(m.get('possible_start') if m.get('possible_start') is not None else m.get('start',0))
            end=float(m.get('possible_end') if m.get('possible_end') is not None else m.get('end',start+min_d))
            start,end=_snap(bundle,start,end,min_d,max_d)
            title=rr.get('title_idea') or _title_from_text(m.get('text'))
            pool.append((score,m,rr,start,end,title))
        pool.sort(key=lambda x:x[0],reverse=True)
        for score,m,rr,start,end,title in pool:
            cand={'start':start,'end':end}
            if any(_overlap(cand,{'start':d['source_start'],'end':d['source_end']})>float(c.get('overlap_threshold',0.72)) for d in decisions): continue
            segs=_segment_context(bundle,start,end)
            decisions.append({
              'clip_id':f"CLIP_{len(decisions)+1:03d}",'rank':len(decisions)+1,'score':score,
              'source_start':start,'source_end':end,'duration':round(end-start,3),
              'reason':rr.get('why') or m.get('reason'),'topic':','.join(m.get('categories') or []),'context_summary':' '.join(s.get('text','') for s in segs[:3])[:700],
              'hook_text':rr.get('hook_text') or title,'title_text':title.upper(),'title_style':'IMPACTO','title_duration':5.0,
              'evidence_segment_ids':[s.get('segment_id') for s in segs], 'scene_ids':sorted({x for s in segs for x in (s.get('scene_ids') or [])}),
              'word_ids':[x for s in segs for x in (s.get('word_ids') or [])], 'warnings':[], 'needs_review':bool(m.get('context_required')),
              'curation_source':'FIRST_PASS'
            })
            if len(decisions)>=maxn: break
    if not seeds and decisions:
        decisions, meta = review_candidates(decisions, cfg, log=log)
        for d in decisions: d.setdefault("warnings",[]); d["phase2_ollama_meta"]=meta
    return decisions
