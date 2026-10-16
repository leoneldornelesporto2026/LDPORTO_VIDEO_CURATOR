from __future__ import annotations
from pathlib import Path
import math
from .utils import run

def _score(s):
    blur=float(s.get('blur_laplacian_variance') or 0)
    br=float(s.get('brightness') or 0)
    black=1 if s.get('possible_black_frame') else 0
    freeze=1 if s.get('possible_freeze_frame') else 0
    motion=float(s.get('camera_motion_proxy') or 0)
    people=len(s.get('visible_people') or [])
    bright_pen=abs(br-115)/120
    return math.log1p(max(0,blur))*2.4 + min(2,people)*1.2 - black*20-freeze*4-bright_pen*2-min(3,motion/30)

def select_candidates(bundle, clip, n=9):
    st,en=clip['source_start'],clip['source_end']
    samples=[s for s in bundle.frame_samples if st<=float(s.get('time',-1))<=en]
    if not samples:
        step=(en-st)/(n+1); return [st+step*(i+1) for i in range(n)]
    ranked=sorted(samples,key=_score,reverse=True)
    selected=[]
    for s in ranked:
        t=float(s.get('time',0))
        if all(abs(t-x)>1.1 for x in selected): selected.append(t)
        if len(selected)>=n: break
    return sorted(selected)

def extract_frame(video:Path,t:float,out:Path):
    out.parent.mkdir(parents=True,exist_ok=True)
    run(['ffmpeg','-y','-ss',f'{t:.3f}','-i',str(video),'-frames:v','1','-q:v','2',str(out)],check=True)
    return out

def create_assets(bundle,clip,video,out_dir,cfg,progress=None):
    n=int(cfg.get('thumbnail',{}).get('candidate_count',9)); times=select_candidates(bundle,clip,n)
    td=out_dir/'thumbnails'; td.mkdir(parents=True,exist_ok=True)
    files=[]
    total=max(1,len(times))
    for i,t in enumerate(times,1):
        if progress: progress((i-1)/total, f'frame {i}/{len(times)}')
        p=extract_frame(video,t,td/f'candidate_{i:02d}_{t:.2f}s.jpg'); files.append((t,p))
        if progress: progress(i/total, f'frame {i}/{len(times)}')
    if not files: return {}
    best=files[0]
    # Best ranked again by nearest frame sample score
    bytime={round(float(s.get('time',0)),3):s for s in bundle.frame_samples}
    def score_item(item):
        t,_=item; nearest=min(bundle.frame_samples,key=lambda s:abs(float(s.get('time',0))-t)) if bundle.frame_samples else {}
        return _score(nearest)
    best=max(files,key=score_item)
    opening=min(files,key=lambda x:abs(x[0]-clip['source_start']))
    clean=max(files,key=score_item)
    import shutil, json
    for src,name in [(opening[1],'opening_frame.jpg'),(best[1],'thumbnail_best.jpg'),(clean[1],'thumbnail_clean.jpg')]: shutil.copy2(src,td/name)
    data={'opening_frame_time':opening[0],'thumbnail_best_time':best[0],'thumbnail_clean_time':clean[0],'candidates':[{'time':t,'file':p.name} for t,p in files]}
    (td/'thumbnail_candidates.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data
