"""Unapproved scene-aware full-height portrait proposals for caption review only.

Certified Analyzer solo regions override optional *unverified* camera
recommendations. Remaining frames use an explicitly labelled center crop.
The resulting MP4 is a review preview, not a publication or human-verified cut.
"""
from __future__ import annotations

import math


def _verified_row(row, duration):
    if not isinstance(row,dict):
        raise ValueError("Região de câmera inválida")
    try:
        start,end,x=(float(row[k]) for k in ("start","end","x"))
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError("Região sem tempo ou coordenada") from exc
    if (not all(math.isfinite(v) for v in (start,end,x))
            or not 0<=start<end<=duration+.002 or not 0<=x<=1):
        raise ValueError("Região de câmera inválida ou fora da fonte")
    return {**row,"start":round(start,3),
            "end":round(min(duration,end),3),"x":x}


def _clip_row(row, start, end):
    region={**row,"start":round(start,3),"end":round(end,3)}
    points=row.get("camera_points",[])
    if points:
        within=[dict(p) for p in points
                if start-.001 <= float(p["t"]) <= end+.001]
        if len(within)>=2:
            region["camera_points"]=within
        else:
            region.pop("camera_points",None)
            region.pop("tracking",None)
    return region


def build_editorial_fill(camera, duration, *, max_regions=24):
    if not isinstance(camera,dict) or not isinstance(duration,(int,float)):
        raise ValueError("Plano editorial inválido")
    if not math.isfinite(duration) or duration<=0:
        raise ValueError("Duração editorial inválida")
    if camera.get("decision") not in ("preserve","crop","dynamic"):
        raise ValueError("Decisão de câmera não reconhecida")
    if camera["decision"]=="crop":
        return {**camera,"draft_editorial_fill":True,
                "portrait_coverage_percent":100.,
                "verified_portrait_coverage_percent":0.,
                "editorial_unverified_coverage_percent":100.,
                "source_portrait_coverage_percent":100.,
                "review_required":True,
                "reason":"Detector local: recorte vertical experimental não aprovado"}
    raw=camera.get("camera_regions",[]) if camera["decision"]=="dynamic" else []
    if not isinstance(raw,list):
        raise ValueError("Regiões de câmera inválidas")
    selected=sorted((_verified_row(r,duration) for r in raw),
                    key=lambda r:(r["start"],r["end"]))
    for left,right in zip(selected,selected[1:]):
        if right["start"]<left["end"]-.001:
            raise ValueError("Regiões sobrepostas: revisão obrigatória")

    # Use the original Analyzer's explicitly solo-person geometry even when
    # its safety gate could not certify a finished crop. This is NOT evidence
    # of a verified face/person; it only guides the review camera position.
    # Priority: certified Analyzer geometry > observed face/shot focus >
    # uncertified Analyzer guidance > center-only trial crop. All proposed
    # regions remain visibly unverified and cannot enter an approved render.
    for key,limit,label in (
            ("scene_focus_regions",7,"OpenCV rosto/cena"),
            ("r6_review_regions",4,"Analyzer R6 não certificado")):
        proposals=camera.get(key,[])
        if not isinstance(proposals,list):
            raise ValueError("Sugestões inválidas: "+label)
        rows=sorted((_verified_row(r,duration) for r in proposals),
                    key=lambda r:-(r["end"]-r["start"]))[:limit]
        for proposal in rows:
            remaining=[(proposal["start"],proposal["end"])]
            for existing in selected:
                next_remaining=[]
                for a,b in remaining:
                    if b<=existing["start"]+.001 or a>=existing["end"]-.001:
                        next_remaining.append((a,b))
                    else:
                        if a<existing["start"]-.001:
                            next_remaining.append((a,existing["start"]))
                        if b>existing["end"]+.001:
                            next_remaining.append((existing["end"],b))
                remaining=next_remaining
            for a,b in remaining:
                if b-a>=.05:
                    selected.append(_clip_row(proposal,a,b))
            selected.sort(key=lambda r:(r["start"],r["end"]))

    regions=[]
    cursor=0.
    verified_seconds=0.
    guided_seconds=0.
    face_seconds=0.
    for row in selected:
        a,b=row["start"],row["end"]
        if a>cursor+.001:
            regions.append({"start":round(cursor,3),"end":round(a,3),
                            "x":.5,"source":"CENTER_CROP_REVIEW_REQUIRED"})
        source=row.get("source","")
        if source=="ANALYZER_R6_SAFE_SOLO":
            verified_seconds+=b-a
        elif source=="ANALYZER_R6_SOLO_REVIEW_REQUIRED":
            guided_seconds+=b-a
        elif source in ("OPENCV_FACE_FOCUS_REVIEW_REQUIRED",
                        "OPENCV_BODY_FOCUS_REVIEW_REQUIRED"):
            face_seconds+=b-a
        regions.append(row)
        cursor=b
    if cursor<duration-.001:
        regions.append({"start":round(cursor,3),"end":round(duration,3),
                        "x":.5,"source":"CENTER_CROP_REVIEW_REQUIRED"})
    if not regions:
        regions=[{"start":0.,"end":round(duration,3),"x":.5,
                  "source":"CENTER_CROP_REVIEW_REQUIRED"}]
    if len(regions)>max_regions:
        raise ValueError("Muitas regiões editoriais: revisar e consolidar câmera")
    return {
        **camera,"decision":"dynamic","camera_regions":regions,
        "camera_points":[],"draft_editorial_fill":True,
        "portrait_coverage_percent":100.,
        "verified_portrait_coverage_percent":round(verified_seconds/duration*100,1),
        "r6_unverified_guidance_percent":round(guided_seconds/duration*100,1),
        "scene_face_focus_percent":round(face_seconds/duration*100,1),
        "center_fallback_percent":round(max(
            0.,duration-verified_seconds-guided_seconds-face_seconds)/duration*100,1),
        "editorial_unverified_coverage_percent":round(
            (duration-verified_seconds)/duration*100,1),
        "source_portrait_coverage_percent":100.,"review_required":True,
        "fallback_mode":"CENTER_CROP_REVIEW_REQUIRED",
        "reason":"R6 seguro + foco de rosto por cena + R6 não certificado + centro somente como última opção",
    }
