"""Visual-only 9:16 crop proof; optional and conservative. No speaker identity inferred.

Requires original MP4 and OpenCV. Never edits video, source, tests, or old approvals.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(8*1024*1024),b''):h.update(data)
    return h.hexdigest()


def observe(video, start, end, cascade):
    import cv2
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError('OpenCV não conseguiu abrir a mídia original')
    # ~1 observation per 2s, maximum 36; never infer speaker/person identity.
    steps=max(8,min(36, math.ceil((end-start)/2.0)))
    seen=[];missing=0;multiple=0
    try:
        for i in range(steps):
            t=start+(end-start)*((i+.5)/steps)
            cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ret,frame=cap.read()
            if not ret:
                missing+=1;continue
            h,w=frame.shape[:2]
            if w<320 or h<240:
                missing+=1;continue
            ratio=960./max(960.,w)
            small=cv2.resize(frame,(round(w*ratio),round(h*ratio)),interpolation=cv2.INTER_AREA)
            gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            gray=cv2.equalizeHist(gray)
            faces=cascade.detectMultiScale(gray,scaleFactor=1.12,minNeighbors=5,minSize=(38,38))
            if len(faces)!=1:
                if len(faces)>1:multiple+=1
                missing+=1;continue
            x,y,fw,fh=faces[0]
            seen.append({'x':(x+fw/2)/small.shape[1], 'y':(y+fh/2)/small.shape[0],
                         'face_h':fh/small.shape[0], 'face_w':fw/small.shape[1]})
    finally:cap.release()
    frac=len(seen)/steps
    if frac<.82 or multiple>0 or len(seen)<7:
        return {'decision':'SOURCE_PRESERVE','reason':'rosto único visível insuficiente ou múltiplos rostos', 'samples':steps,'observed':len(seen),'multiple':multiple}
    centers=[a['x'] for a in seen]
    ys=[a['y'] for a in seen]
    xsum=sum(centers)/len(centers)
    spread=max(centers)-min(centers)
    if (spread>.085 or max(ys)-min(ys)>.16 or not .22<=xsum<=.78 or
        any(not .07<=v['face_h']<=.26 or v['face_w']>.12 for v in seen)):
        return {'decision':'SOURCE_PRESERVE','reason':'movimento ou rosto incompatível com crop estável', 'samples':steps,'observed':len(seen),'x_spread':round(spread,4)}
    return {'decision':'MANUAL_KEYFRAMES','reason':'rosto único e estável medido nos quadros; identidade NÃO confirmada',
        'samples':steps,'observed':len(seen),'x_spread':round(spread,4),'center_x':round(xsum,4),
        'points':[{'time':0.0,'x':round(xsum,4),'y':.5,'zoom':1.0}]}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--curator',type=Path,required=True)
    p.add_argument('--plano',type=Path,required=True)
    p.add_argument('--midia',type=Path,required=True)
    p.add_argument('--aplicar',action='store_true')
    args=p.parse_args()
    root=args.curator.resolve(strict=True)
    index=args.plano.resolve(strict=True)
    allowed=(root/'output'/'projects'/'9UCGZia2p1k').resolve()
    if not (index.name=='series_index.json' and index.parent.is_relative_to(allowed)
            and index.parent.name.startswith('stories_')):
        raise ValueError('Selecione um novo projeto de Stories do show, não revisões antigas')
    import cv2
    cascade_path=Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'
    cascade=cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():raise ValueError('Detector facial OpenCV indisponível')
    sys.path.insert(0,str(root))
    from ldporto_curator.series_workflow import SeriesProject
    from ldporto_curator.config import load_config
    project=SeriesProject(index.parent,load_config(root/'config.yaml'))
    episodes=project.episodes()
    if project.evidence['source']['sha256']!='5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea':
        raise ValueError('SHA256 da fonte do plano não pertence ao show')
    if len(episodes)!=7 or any(ep.get('preview') or ep.get('final') or ep.get('human_approval') or
          ep.get('camera_plan') or ep.get('status') in {'REJECTED','APPROVED','PREVIEW_APPROVED'}
          for ep in episodes):
        raise ValueError('A câmera exige novo projeto sem prévias nem aprovações; nenhum arquivo alterado')
    movie=args.midia.resolve(strict=True)
    if sha256(movie)!=project.evidence['source']['sha256']:
        raise ValueError('MP4 original não corresponde ao Analyzer; operação bloqueada')
    decisions=[]
    for ep in episodes:
        entry=observe(movie,ep['source_start'],ep['source_end'],cascade)
        entry.update({'episode_id':ep['episode_id'],'series_id':ep['series_id'],'order':ep['order'],
                      'source_start':ep['source_start'],'source_end':ep['source_end']})
        decisions.append(entry)
    print(json.dumps({'source_sha256':project.evidence['source']['sha256'],'published':False,
         'preview_approved':False,'segments':decisions},ensure_ascii=False,indent=2))
    if not args.aplicar:
        print('SIMULAÇÃO: nenhum arquivo modificado. Para criar novas revisões, executar --aplicar.')
        return
    # User opt-in. Only apply if there is positive measured evidence. All others
    # retain existing AUTO_CONSERVADOR; safety fallback remains.
    import datetime
    backup=Path.home()/'Videos'/'LDPORTO_CURATOR_BACKUPS'/'CAMERA_SHOW_9UCGZia2p1k'
    backup.mkdir(parents=True,exist_ok=True)
    token=hashlib.sha256(index.read_bytes()).hexdigest()
    dest=backup/(datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+token[:12]+'.json')
    with dest.open('xb') as file:file.write(index.read_bytes())
    changes=0
    for entry in decisions:
        if entry['decision']!='MANUAL_KEYFRAMES':continue
        ep=next(x for x in project.episodes() if x['series_id']==entry['series_id'] and x['order']==entry['order'])
        project.edit(ep['episode_id'],camera_mode='MANUAL_KEYFRAMES',camera_keyframes=entry['points'])
        changes+=1
    print('CAMERA_REVISADA:',changes,'episódios; outros mantidos conservadores.')
    print('BACKUP:',dest)
    print('APROVACAO: PENDENTE. Visual humano deve confirmar crop no MP4 antes de qualquer lote.')

if __name__=='__main__': main()
