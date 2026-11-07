"""Conservative, explainable portrait framing for concert videos.

Never invents human detections. A confident, single full-body detection permits a
vertical crop. Otherwise the full 16:9 frame remains visible on a blurred canvas.
Optional cv2 HOG person detector; missing cv2 cleanly falls back to preservation.
No pretrained weights are downloaded at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import statistics

LAYOUTS = ('preserve', 'center_crop', 'solo_fit', 'smart_zoom')


@dataclass(frozen=True)
class BodyObservation:
    """A body bounding box in normalized 0..1 source coordinates."""
    t: float
    cx: float
    width: float
    y: float
    height: float
    people: int = 1
    faces: int = 0
    face_only: bool = False
    motion_fallback: bool = False
    confidence: float = 1.0


def _valid_solo_subject(o, crop_ratio):
    if o is None or o.people != 1 or o.faces > 1 or o.motion_fallback:
        return False
    if not all(math.isfinite(x) for x in (o.t,o.cx,o.width,o.y,o.height)):
        return False
    if (o.width <= 0 or o.cx-o.width/2 < .01 or o.cx+o.width/2 > .99
            or o.width*1.40 > crop_ratio):
        return False
    if o.face_only:
        # Head-and-shoulders interviews rarely expose a full body. This is
        # explicitly a FACE detection, not an invented full-body box.
        return (o.faces == 1 and o.width >= .035 and o.height >= .035
                and .015 <= o.y <= .72 and o.y+o.height <= .85)
    return (o.height >= .30 and o.y >= .015 and o.y+o.height <= .985)


def _valid_scene_focus(o, crop_ratio):
    if _valid_solo_subject(o,crop_ratio):
        return True
    return (o is not None and o.motion_fallback is True and o.people==1
            and o.faces<=1 and o.confidence>=.63
            and math.isfinite(o.cx) and math.isfinite(o.width)
            and .01<o.width<=crop_ratio and .02<=o.cx<=.98)


def decide_scene_regions(observations, source_width, source_height, duration,
                         *, min_samples=2, min_seconds=2.8):
    """Conservative solo-person intervals inside an otherwise preserved 16:9 cut.

    At least 2 adjacent physical detections are necessary. Unknown/group
    frames create full-scene periods; no blind extrapolation through them.
    """
    result={'decision':'preserve','camera_regions':[],
            'reason':'Sem sequência de pessoa única para corte vertical'}
    if (source_width <= 0 or source_height <= 0 or duration <= 0
            or not math.isfinite(duration) or len(observations) < 4):
        return result
    ratio=(9/16)/(source_width/source_height)
    if ratio >= .98:
        return {**result,'reason':'Fonte já é vertical'}
    active=[_valid_scene_focus(o,ratio) for o in observations]
    regions=[]
    i=0
    while i < len(observations):
        if not active[i]:
            i+=1
            continue
        j=i
        while j+1 < len(observations) and active[j+1]:
            j+=1
        sequence=observations[i:j+1]
        centers=[o.cx for o in sequence]
        # Scene cut or tracker jump: no crop for unstable group.
        stable=(max(centers)-min(centers)) <= .22
        # Optical movement without a recognized face/body is an editorial
        # candidate, not a verified lone person: require more observations.
        motion_only=all(o.motion_fallback for o in sequence)
        enough=len(sequence)>=max(min_samples,3 if motion_only else 2)
        left=(0 if i == 0 else (observations[i-1].t+sequence[0].t)/2
              if observations[i-1] is not None else sequence[0].t)
        right=(duration if j == len(observations)-1 else
               (sequence[-1].t+observations[j+1].t)/2
               if observations[j+1] is not None else sequence[-1].t)
        left=max(0.,min(duration,float(left)))
        right=max(0.,min(duration,float(right)))
        if (enough and stable and right-left >= min_seconds):
            half=ratio/2
            cx=max(half,min(1-half,statistics.median(centers)))
            x=(cx-half)/(1-ratio)
            regions.append({'start':round(left,3),'end':round(right,3),
                            'x':round(x,6),'samples':len(sequence),
                            'source':('MOTION_FOCUS_REVIEW_REQUIRED' if motion_only
                                      else 'SINGLE_VISIBLE_SUBJECT')})
        i=j+1
    if not regions:
        return result
    return {'decision':'dynamic','camera_regions':regions,
            'reason':'Alternar pessoa única 9:16 com cena completa 16:9',
            'camera_points':[],'crop_fraction':round(ratio,6)}


def decide_framing(observations: list[BodyObservation | None], source_width: int,
                   source_height: int, mode: str, duration: float) -> dict:
    """Pure decision rules, suitable for deterministic offline regression tests."""
    if mode not in ('solo_fit','smart_zoom'):
        raise ValueError('Modo de câmera não suportado: '+mode)
    base={'requested':mode,'decision':'preserve','reason':'Sem detecção confiável de pessoa inteira',
          'sample_count':len(observations),'valid_samples':0,'camera_points':[]}
    if source_width<=0 or source_height<=0 or not math.isfinite(duration) or duration<=0:
        return {**base,'reason':'Metadados do vídeo inválidos'}
    crop_ratio=(9/16)/(source_width/source_height)
    if crop_ratio >= .98:
        return {**base,'reason':'A fonte já é aproximadamente vertical'}
    if len(observations)<4:
        return {**base,'reason':'Amostras insuficientes para rastreamento seguro'}
    # A single wide/crowded observation is evidence not to cut the band or stage.
    if any(o is not None and (o.people!=1 or o.faces>1) for o in observations):
        return {**base,'reason':'Cena com mais de uma pessoa/rosto — manter palco inteiro'}
    valid=[]
    for observation in observations:
        if observation is None:continue
        o=observation
        if not all(math.isfinite(x) for x in (o.t,o.cx,o.width,o.y,o.height)):
            continue
        if not _valid_solo_subject(o,crop_ratio):
            continue
        valid.append(o)
    base['valid_samples']=len(valid)
    needed=max(4,math.ceil(len(observations)*(.75 if mode=='smart_zoom' else .65)))
    if len(valid)<needed:
        return {**base,'reason':'Corpo completo não identificado com confiança suficiente'}
    centers=[x.cx for x in valid]
    max_step=max(abs(b-a) for a,b in zip(centers,centers[1:])) if len(centers)>1 else 0
    if max_step>.20:
        return {**base,'reason':'Mudança brusca de enquadramento; evitar crop imprevisível'}
    half=crop_ratio/2
    def normalize(cx):
        bounded=max(half,min(1-half,cx))
        return max(0,min(1,(bounded-half)/(1-crop_ratio)))
    if mode=='solo_fit':
        median=statistics.median(centers)
        x=normalize(median)
        return {**base,'decision':'crop','reason':'Pessoa única inteira, centralizada com margens',
                'camera_points':[{'t':0.,'x':round(x,6)}],
                'crop_fraction':round(crop_ratio,6)}
    # Light smoothed tracking: no sudden jumps; zoom factor is fixed (no pumping).
    smoothed=[]
    ema=centers[0]
    for o in valid:
        ema=.72*ema+.28*o.cx
        smoothed.append({'t':round(min(duration,max(0,o.t)),3),
                         'x':round(normalize(ema),6)})
    return {**base,'decision':'crop','reason':'Pessoa única detectada; acompanhamento horizontal suave',
            'camera_points':smoothed,'crop_fraction':round(crop_ratio,6)}


def crop_x_expression(points: list[dict]) -> str:
    """Return FFmpeg crop x formula, normalized within available horizontal range."""
    if not points:
        return '0.5'
    if len(points)==1:
        return f'{points[0]["x"]:.6f}'
    expr=f'{points[-1]["x"]:.6f}'
    for i in range(len(points)-2,-1,-1):
        a,b=points[i],points[i+1]
        ta=float(a['t']);tb=float(b['t'])
        if tb<=ta:continue
        xa=float(a['x']);xb=float(b['x'])
        segment=f'({xa:.6f}+({xb-xa:.6f})*max(0,min(1,(t-{ta:.3f})/{tb-ta:.3f})))'
        expr=f'if(lt(t,{tb:.3f}),{segment},{expr})'
    return expr


def _sample_people(frame, hog, face_cascade, cv2, timestamp: float):
    # Resize all samples to bounded cost and consistent detector coordinates.
    h,w=frame.shape[:2]
    if w<=0 or h<=0:return None
    scale=min(1.0,640/max(w,h))
    if scale<1:
        frame=cv2.resize(frame,(int(w*scale),int(h*scale)))
    h,w=frame.shape[:2]
    boxes,weights=hog.detectMultiScale(frame,winStride=(8,8),padding=(8,8),scale=1.08,useMeanshiftGrouping=False)
    bodies=[]
    for b,score in zip(boxes,weights):
        x,y,bw,bh=[int(v) for v in b]
        if float(score)<.25 or bw<15 or bh<55:continue
        bodies.append((x,y,bw,bh,float(score)))
    # Detect separate faces so solo crop cannot swallow another nearby musician.
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    faces=face_cascade.detectMultiScale(gray,scaleFactor=1.2,minNeighbors=5,minSize=(24,24))
    if len(bodies)>1 or len(faces)>1:
        return BodyObservation(timestamp,.5,1.,0.,1.,people=len(bodies),
                               faces=len(faces))
    if len(bodies)==1:
        x,y,bw,bh,_=bodies[0]
        return BodyObservation(timestamp,(x+bw/2)/w,bw/w,y/h,bh/h,
                               people=1,faces=len(faces))
    if len(faces)==1:
        x,y,fw,fh=[int(v) for v in faces[0]]
        return BodyObservation(timestamp,(x+fw/2)/w,fw/w,y/h,fh/h,
                               people=1,faces=1,face_only=True)
    return None


def _motion_focus(previous, frame, cv2, t, source_width, source_height):
    """Localized optical motion as a FOCUS SUGGESTION, never a person ID.

    Completely moving cameras, scene cuts, noisy footage, and weak activity
    return None. Genuine detections always take priority.
    """
    if previous is None or frame is None:
        return None
    w,h=320,180
    def gray(image):
        scaled=cv2.resize(image,(w,h))
        return cv2.GaussianBlur(cv2.cvtColor(scaled,cv2.COLOR_BGR2GRAY),(7,7),0)
    diff=cv2.absdiff(gray(previous),gray(frame))
    _,mask=cv2.threshold(diff,26,255,cv2.THRESH_BINARY)
    cols=(mask>0).sum(axis=0)
    amount=int(cols.sum())
    total=w*h
    if not int(total*.0025)<=amount<=int(total*.23):
        return None
    ratio=(9/16)/(source_width/source_height)
    size=max(24,min(w,round(w*ratio)))
    if size>=w:
        return None
    window=cols[:size].sum()
    best,start=int(window),0
    for x in range(1,w-size+1):
        window+=int(cols[x+size-1])-int(cols[x-1])
        if window>best:
            best,start=int(window),x
    concentration=best/amount
    if concentration<.63:
        return None
    cx=(start+size/2)/w
    return BodyObservation(t,cx,ratio*.82,.20,.55,
                           people=1,faces=0,motion_fallback=True,
                           confidence=float(concentration))


def analyze_camera(source: str | Path, start: float, end: float, mode: str,
                   *, max_samples: int=42) -> dict:
    """Inspect real source frames. Auto mode FALLS BACK to full 16:9 if uncertain."""
    base={'requested':mode,'decision':'preserve','sample_count':0,
          'valid_samples':0,'camera_points':[]}
    if mode not in ('solo_fit','smart_zoom'):
        raise ValueError('Modo inválido: '+str(mode))
    try:
        import cv2
    except ImportError:
        return {**base,'reason':'OpenCV ausente: mantendo 16:9, sem detecção inventada'}
    cap=cv2.VideoCapture(str(Path(source)))
    if not cap.isOpened():
        cap.release()
        return {**base,'reason':'Não foi possível ler quadros: mantendo 16:9'}
    try:
        w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        hog=cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        cascade=cv2.CascadeClassifier(str(Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'))
        if cascade.empty():
            return {**base,'reason':'Detector de rostos indisponível: mantendo 16:9'}
        duration=max(.1,end-start)
        count=max(4,min(max_samples,math.ceil(duration/1.7)))
        if count>1:
            stamps=[.25+(duration-.5)*i/(count-1) for i in range(count)] if duration>.5 else [duration*i/(count-1) for i in range(count)]
        else:stamps=[duration/2]
        seen=[]
        previous=None
        for idx,t in enumerate(stamps):
            cap.set(cv2.CAP_PROP_POS_MSEC,1000*(start+t))
            ok,frame=cap.read()
            if not ok or frame is None:
                seen.append(None)
                previous=None
                continue
            # HOG is expensive; keep exact visual evidence in a smaller
            # number of samples, and fill gaps with localized optical motion.
            observed=_sample_people(frame,hog,cascade,cv2,t) if idx%3==0 else None
            if observed is None:
                observed=_motion_focus(previous,frame,cv2,t,w,h)
            seen.append(observed)
            previous=frame
        plan=decide_framing(seen,w,h,mode,duration)
        if mode=='smart_zoom' and plan['decision']=='preserve':
            intervals=decide_scene_regions(seen,w,h,duration)
            if intervals['decision']=='dynamic':
                plan={**plan,**intervals}
        plan['source_dimensions']={'width':w,'height':h}
        plan['detector']='OpenCV_HOG_FACE_AND_LOCAL_MOTION_V3'
        plan['motion_is_not_person_verification']=True
        plan['scene_aware']=mode=='smart_zoom'
        return plan
    except (ValueError, RuntimeError, cv2.error) as exc:
        return {**base,'reason':f'Detecção indisponível: {type(exc).__name__}. Mantendo 16:9'}
    finally:
        cap.release()
