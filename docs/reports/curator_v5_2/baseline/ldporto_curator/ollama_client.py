from __future__ import annotations
import json, requests

def review_candidates(candidates, cfg, log=print):
    ocfg=cfg.get('ollama',{})
    if not ocfg.get('enabled',True) or not candidates:
        return candidates, {'used':False,'reason':'disabled_or_empty'}
    base=str(ocfg.get('base_url','http://127.0.0.1:11434')).rstrip('/')
    model=ocfg.get('model','qwen3:14b')
    compact=[]
    for c in candidates:
        compact.append({
          'clip_id':c['clip_id'],'start':c['source_start'],'end':c['source_end'],'duration':c['duration'],
          'score':c['score'],'reason':c.get('reason'),'title':c.get('title_text'),'context':c.get('context_summary','')[:1200]
        })
    schema={
      'type':'object','properties':{
        'ranking':{'type':'array','items':{'type':'object','properties':{
          'clip_id':{'type':'string'},'editorial_score':{'type':'number'},'title':{'type':'string'},'hook':{'type':'string'},'why':{'type':'string'},'approve':{'type':'boolean'}
        },'required':['clip_id','editorial_score','title','hook','why','approve']}}
      },'required':['ranking']
    }
    prompt=(
      'Você é editor de vídeos curtos PT-BR. Revise SOMENTE os candidatos fornecidos. '
      'Não altere timestamps nem invente fatos. Avalie se cada trecho funciona sozinho, tem hook, desenvolvimento e fechamento. '
      'Aprove apenas o que vale publicar. Títulos devem ser fortes e fiéis, sem clickbait falso. '
      'Responda no schema JSON solicitado. Candidatos:\n'+json.dumps(compact,ensure_ascii=False)
    )
    payload={'model':model,'prompt':prompt,'stream':False,'format':schema,'keep_alive':ocfg.get('keep_alive','15m'),'options':{
      'num_ctx':int(ocfg.get('num_ctx',32768)),'num_predict':int(ocfg.get('num_predict',4096)),'temperature':float(ocfg.get('temperature',0)),
      'top_k':int(ocfg.get('top_k',40)),'top_p':float(ocfg.get('top_p',0.9)),'repeat_penalty':float(ocfg.get('repeat_penalty',1.05)),'seed':int(ocfg.get('seed',42))}}
    try:
        log(f'Ollama Fase 2: revisando {len(candidates)} candidatos com {model}...')
        r=requests.post(base+'/api/generate',json=payload,timeout=float(ocfg.get('timeout_seconds',600))); r.raise_for_status()
        raw=r.json().get('response') or '{}'; data=json.loads(raw); ranking=data.get('ranking') or []
        byid={c['clip_id']:c for c in candidates}; valid=[]
        seen=set()
        for x in ranking:
            cid=x.get('clip_id')
            if cid not in byid or cid in seen: continue
            seen.add(cid); c=dict(byid[cid]); c['ollama_phase2']={k:x.get(k) for k in ('editorial_score','why','approve')}
            if x.get('title'): c['title_text']=str(x['title']).strip().upper()[:110]
            if x.get('hook'): c['hook_text']=str(x['hook']).strip()[:180]
            if x.get('why'): c['reason_phase2']=str(x['why']).strip()[:900]
            if bool(x.get('approve')):
                sc=float(x.get('editorial_score') or 0); c['score']=round(0.55*float(c['score'])+0.45*max(0,min(100,sc*100 if sc<=1 else sc)),1)
                valid.append(c)
        # Keep candidates omitted by model only as review-needed if model response was incomplete.
        if not valid:
            return candidates,{'used':True,'valid':False,'reason':'no_valid_approved_items'}
        valid.sort(key=lambda c:c['score'],reverse=True)
        for i,c in enumerate(valid,1): c['rank']=i; c['clip_id']=f'CLIP_{i:03d}'
        return valid,{'used':True,'valid':True,'model':model,'returned':len(ranking),'approved':len(valid)}
    except Exception as e:
        log('Ollama Fase 2 indisponível; mantendo curadoria determinística. Motivo: '+str(e))
        return candidates,{'used':False,'reason':'error','error':str(e)}
