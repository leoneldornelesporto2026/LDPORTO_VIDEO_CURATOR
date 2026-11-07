"""Conservative shot-aware face positioning for editorial portrait camera.

An observed face is a *focus suggestion*, not identity/approval. Only the
original MP4 is sampled (OpenCV preinstalled locally); no model downloads.
"""
from __future__ import annotations

import math
import statistics


def shot_changed(previous, frame, cv2):
    """Strong appearance discontinuity, avoiding tracking through scene cuts."""
    if previous is None or frame is None:
        return False
    try:
        a=cv2.cvtColor(cv2.resize(previous,(160,90)),cv2.COLOR_BGR2HSV)
        b=cv2.cvtColor(cv2.resize(frame,(160,90)),cv2.COLOR_BGR2HSV)
        def hist(im):
            h=cv2.calcHist([im],[0,1],None,[20,12],[0,180,0,256])
            cv2.normalize(h,h,0,1,cv2.NORM_MINMAX)
            return h
        score=cv2.compareHist(hist(a),hist(b),cv2.HISTCMP_BHATTACHARYYA)
        return score>.58
    except (ValueError,cv2.error):
        return False


def face_focus(frame, cascade, profile, cv2):
    """Find exactly one front/profile face, retaining edge-of-frame faces."""
    h,w=frame.shape[:2]
    if h<=0 or w<=0:
        return None
    scale=min(1.,960/max(w,h))
    scaled=cv2.resize(frame,(max(1,int(w*scale)),max(1,int(h*scale))))
    gray=cv2.cvtColor(scaled,cv2.COLOR_BGR2GRAY)
    gray=cv2.equalizeHist(gray)
    faces=cascade.detectMultiScale(gray,scaleFactor=1.12,
                                   minNeighbors=4,minSize=(22,22))
    source="FACE_FRONT"
    if len(faces)==0 and profile is not None and not profile.empty():
        faces=profile.detectMultiScale(gray,scaleFactor=1.12,
                                      minNeighbors=4,minSize=(22,22))
        source="FACE_PROFILE"
        if len(faces)==0:
            flipped=cv2.flip(gray,1)
            faces=profile.detectMultiScale(flipped,scaleFactor=1.12,
                                           minNeighbors=4,minSize=(22,22))
            if len(faces)==1:
                x,y,fw,fh=(int(v) for v in faces[0])
                faces=[(gray.shape[1]-x-fw,y,fw,fh)]
    if len(faces)!=1:
        return None
    x,y,fw,fh=(int(v) for v in faces[0])
    full_width=gray.shape[1]
    center=(x+fw/2)/full_width
    if not .015<=center<=.985 or fw<22:
        return None
    return {"cx":round(float(center),6),"kind":source,
            "confidence":1.,"width":round(fw/full_width,5)}


def plan_shot_focus(samples, duration, source_width, source_height,
                    *, max_scenes=7):
    """Stable per-shot 9:16 proposals; make no claim of verified identity."""
    if not (0<duration and math.isfinite(duration)
            and source_width>0 and source_height>0):
        return []
    ratio=(9/16)/(source_width/source_height)
    if not 0<ratio<.99 or not samples:
        return []
    samples=sorted(samples,key=lambda s:s["t"])
    groups=[]
    for row in samples:
        if not isinstance(row,dict) or not math.isfinite(float(row.get("t",-1))):
            continue
        if not groups or row["shot"]!=groups[-1][0]["shot"]:
            groups.append([])
        groups[-1].append(row)
    candidates=[]
    for idx,group in enumerate(groups):
        if len(group)==0:
            continue
        faces=[row for row in group
               if row.get("kind") in ("FACE_FRONT","FACE_PROFILE")]
        bodies=[row for row in group if row.get("kind")=="BODY"]
        focus=faces if faces else bodies
        if not focus or any(row.get("kind")=="GROUP" for row in group):
            continue
        centers=[float(row["cx"]) for row in focus]
        if not all(math.isfinite(x) and .0<=x<=1. for x in centers):
            continue
        if max(centers)-min(centers)>.36:
            # Another person, abrupt move or unreliable track: don't chase.
            continue
        left=(0. if idx==0 else
              (groups[idx-1][-1]["t"]+group[0]["t"])/2)
        right=(duration if idx==len(groups)-1 else
               (group[-1]["t"]+groups[idx+1][0]["t"])/2)
        left=max(0.,min(duration,float(left)))
        right=max(left,min(duration,float(right)))
        if right-left < 1.2:
            continue
        center=statistics.median(centers)
        half=ratio/2
        x=(max(half,min(1-half,center))-half)/(1-ratio)
        region={
            "start":round(left,3),"end":round(right,3),
            "x":round(max(0.,min(1.,x)),6),
            "source":"OPENCV_FACE_FOCUS_REVIEW_REQUIRED" if faces else
                     "OPENCV_BODY_FOCUS_REVIEW_REQUIRED",
            "focus_samples":len(focus),
            "shot_id":group[0]["shot"],
            "review_required":True,
        }
        if len(focus)>=3 and max(centers)-min(centers)>=.075:
            # Smooth subject movement inside the same shot; never chase a
            # detection across a scene cut or synthesize missing keyframes.
            track=[]
            ema=float(focus[0]["cx"])
            for index,frame in enumerate(focus):
                ema=.70*ema+.30*float(frame["cx"])
                if index % max(1,len(focus)//5)==0 or index==len(focus)-1:
                    current=max(half,min(1-half,ema))
                    track.append({"t":round(float(frame["t"]),3),
                                  "x":round((current-half)/(1-ratio),6)})
            if len(track)>=2:
                region["camera_points"]=track[:8]
                region["tracking"]="SMOOTH_FACE_WITHIN_SHOT_REVIEW_REQUIRED"
        candidates.append(region)
    # Long coherent shots are more valuable than unstable short cuts;
    # conserve FFmpeg region budget for certified R6 and human edits.
    candidates.sort(key=lambda r:(-(r["end"]-r["start"]),r["start"]))
    return sorted(candidates[:max(0,max_scenes)],
                  key=lambda r:(r["start"],r["end"]))
