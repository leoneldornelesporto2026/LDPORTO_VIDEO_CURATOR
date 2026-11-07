"""Build an *unapproved* portrait camera proposal for second-curation previews.

Source-bound Analyzer Director regions are always preferred. Remaining seconds
use an explicitly unverified center crop rather than claiming a person tracker.
Only use on draft-captions review outputs; never feed a final approval path.
"""
from __future__ import annotations

import math


def build_editorial_fill(camera, duration, *, max_regions=24):
    if not isinstance(camera, dict) or not isinstance(duration,(int,float)):
        raise ValueError("Plano editorial inválido")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duração editorial inválida")
    if camera.get("decision") not in ("preserve","crop","dynamic"):
        raise ValueError("Decisão de câmera não reconhecida")
    if camera.get("decision") == "crop":
        # A whole-clip HOG/face track is still a suggestion, not a guarantee.
        return {
            **camera,
            "draft_editorial_fill":True,
            "verified_portrait_coverage_percent":0.,
            "editorial_unverified_coverage_percent":100.,
            "source_portrait_coverage_percent":100.,
            "review_required":True,
            "reason": "Detecção de câmera local: prévia vertical não aprovada",
        }

    raw=camera.get("camera_regions",[]) if camera.get("decision")=="dynamic" else []
    if not isinstance(raw,list):
        raise ValueError("Regiões de câmera inválidas")
    safe=[]
    previous=0.
    for row in sorted(raw,key=lambda r:r["start"]):
        if not isinstance(row,dict):
            raise ValueError("Região inválida")
        start,end,x=(float(row[k]) for k in ("start","end","x"))
        if (not all(math.isfinite(v) for v in (start,end,x))
                or start < previous-0.001 or start < 0 or
                not start < end <= duration+.002 or not 0 <= x <= 1):
            raise ValueError("Regiões fora do intervalo ou sobrepostas")
        previous=end
        safe.append(dict(row))
    # Every uncovered gap is a FULL HEIGHT center crop, visibly labeled
    # as a proposal, never an automatically verified solo-person shot.
    regions=[]
    cursor=0.
    verified_seconds=0.
    suggested_seconds=0.
    for row in safe:
        a=max(0.,float(row["start"]))
        b=min(duration,float(row["end"]))
        if a > cursor+.001:
            regions.append({"start":round(cursor,3),"end":round(a,3),
                            "x":.5,"source":"CENTER_CROP_REVIEW_REQUIRED"})
        source=row.get("source","")
        if source=="ANALYZER_R6_SAFE_SOLO":
            verified_seconds+=b-a
        else:
            suggested_seconds+=b-a
        regions.append({**row,"start":round(a,3),"end":round(b,3)})
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
        **camera,
        "decision":"dynamic",
        "camera_regions":regions,
        "camera_points":[],
        "draft_editorial_fill":True,
        "portrait_coverage_percent":100.,
        "verified_portrait_coverage_percent":round(verified_seconds/duration*100,1),
        "other_detected_portrait_coverage_percent":round(suggested_seconds/duration*100,1),
        "editorial_unverified_coverage_percent":round(
            (duration-verified_seconds)/duration*100,1),
        "source_portrait_coverage_percent":100.,
        "review_required":True,
        "fallback_mode":"CENTER_CROP_REVIEW_REQUIRED",
        "reason":"R6 confirmado onde disponível; restante em recorte central experimental para segunda curadoria",
    }
