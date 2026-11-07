"""Read actual Analyzer R6 camera recommendations; never infer them from titles.

Only safe, source-bound solo-subject geometries yield portrait crop proposals.
The R6 ZIP/receipt/manifest are revalidated before returning coordinates.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from zipfile import ZipFile

from .analyzer_inbox import inspect_delivery

MEMBER = "camera/shared_camera_handoff.json"


def read_safe_r6_camera(inbox, source_sha256, start, end, source_width, source_height):
    """Return explicit 9:16 source-relative regions, or a documented fallback."""
    result={"trusted_regions":[],"review_regions":[],
            "evidence_status":"NO_R6_CAMERA_EVIDENCE",
            "source":"ANALYZER_R6_CANONICAL"}
    if inbox is None:
        return result
    inspected=inspect_delivery(inbox)
    with ZipFile(inspected["package_path"]) as archive:
        if MEMBER not in archive.namelist():
            return {**result,"evidence_status":"NO_R6_CAMERA_HANDOFF_MEMBER",
                    "source_zip_sha256":inspected["zip_sha256"]}
        manifest=json.loads(archive.read("SECOND_CURATION_MANIFEST.json"))
        record=next((r for r in manifest.get("files",[])
                     if isinstance(r,dict) and r.get("path")==MEMBER),None)
        info=archive.getinfo(MEMBER)
        if not record or info.file_size>24*1024*1024:
            raise ValueError("Câmera R6 ausente do manifesto ou acima do limite")
        data=archive.read(MEMBER)
        if record.get("bytes")!=len(data) or record.get("sha256")!=sha256(data).hexdigest():
            raise ValueError("Plano de câmera R6 não coincide com o manifesto")
        handoff=json.loads(data)
    expected=str(source_sha256).lower()
    if (not isinstance(expected,str) or len(expected)!=64
            or handoff.get("renderer_owner")!="VIDEO_CURATOR"
            or handoff.get("execution_scope")!="recommendation_not_render_or_approval"
            or handoff.get("preview_approved") is not False
            or handoff.get("publish_ready") is not False):
        raise ValueError("Contrato de câmera R6 inválido")
    # Receipt identity is tied to the original source, NOT a transcoded proxy.
    receipt=json.loads((Path(inbox)/"ANALYZER_TO_CURATOR_HANDOFF.json").read_text(encoding="utf-8"))
    if receipt.get("source_sha256")!=expected:
        raise ValueError("Câmera R6 pertence a outra mídia")
    dims_ratio=(9/16)/(source_width/source_height)
    if not 0<dims_ratio<.99:
        return {**result,"evidence_status":"SOURCE_ALREADY_PORTRAIT",
                "source_zip_sha256":inspected["zip_sha256"]}
    regions=[]
    review=[]
    for row in handoff.get("segments",[]):
        if not isinstance(row,dict):
            continue
        evidence=row.get("evidence") or {}
        safe=(row.get("recommended_composition")=="FOCUS_PERSON_9X16"
              and evidence.get("crop_geometrically_valid") is True)
        # Geometry can be useful for an EDITORIAL PROPOSAL even when the
        # Analyzer could not certify a crop. Never promote such a segment.
        proposed=(row.get("layout")=="single_person" or
                  row.get("composition_intent")=="FOCUS_PERSON_9X16" or
                  row.get("recommended_composition")=="FOCUS_PERSON_9X16")
        if not (safe or proposed):
            continue
        rect=((row.get("crop") or {}).get("rect_end"))
        if (not isinstance(rect,dict) or
                not all(isinstance(rect.get(k),(int,float)) and
                        math.isfinite(rect[k]) for k in ("x","y","width","height"))):
            continue
        x0,y0,w,h=(float(rect[k]) for k in ("x","y","width","height"))
        if not (0<=x0<1 and 0<=y0<1 and w>0 and h>0 and
                x0+w<=1.001 and y0+h<=1.001):
            continue
        a,b=row.get("start"),row.get("end")
        if not (isinstance(a,(int,float)) and isinstance(b,(int,float))
                and math.isfinite(a) and math.isfinite(b)):
            continue
        left,right=max(float(a),start),min(float(b),end)
        if right-left<.8:
            continue
        center=min(1-dims_ratio/2,max(dims_ratio/2,x0+w/2))
        normalized=(center-dims_ratio/2)/(1-dims_ratio)
        # Reuse temporal source Director points, not a fixed "person position"
        # inferred from a single thumbnail. Never invent keyframes.
        points=[]
        camera=row.get("camera") or {}
        keyframes=camera.get("keyframes",[]) if isinstance(camera,dict) else []
        for key in keyframes if isinstance(keyframes,list) else []:
            if not isinstance(key,dict):
                continue
            tm,center=key.get("time"),key.get("center")
            if (not isinstance(tm,(int,float)) or not math.isfinite(tm)
                    or not left<=tm<=right or
                    not isinstance(center,(list,tuple)) or len(center)!=2 or
                    not isinstance(center[0],(int,float)) or
                    not math.isfinite(center[0]) or not 0<=center[0]<=1):
                continue
            cx=max(dims_ratio/2,min(1-dims_ratio/2,float(center[0])))
            points.append({"t":round(float(tm)-start,3),
                           "x":round((cx-dims_ratio/2)/(1-dims_ratio),6)})
        points.sort(key=lambda p:p["t"])
        # Require strictly increasing times, and avoid unbounded FFmpeg graphs.
        points=[p for i,p in enumerate(points)
                if i==0 or p["t"]>points[i-1]["t"]+0.001][:24]
        region={"start":round(left-start,3),"end":round(right-start,3),
                "x":round(normalized,6),
                "source":"ANALYZER_R6_SAFE_SOLO",
                "director_id":row.get("director_id")}
        if len(points)>=2:
            region["camera_points"]=points
            region["tracking"]="SOURCE_DIRECTOR_HORIZONTAL_KEYFRAMES"
        if safe:
            regions.append(region)
        else:
            region["source"]="ANALYZER_R6_SOLO_REVIEW_REQUIRED"
            region["crop_geometrically_valid"]=False
            review.append(region)
    regions=sorted(regions,key=lambda r:(r["start"],r["end"]))
    # At most 8 long editorial suggestions: cap graph size and preserve
    # certified segments. Shorter ambiguous suggestions remain unselected.
    review=sorted(review,key=lambda r:r["end"]-r["start"],reverse=True)[:8]
    review=sorted(review,key=lambda r:(r["start"],r["end"]))
    valid=[]
    for row in regions:
        if valid and row["start"]<valid[-1]["end"]-0.001:
            # Do not guess which conflicting source director region is right.
            return {**result,"evidence_status":"OVERLAPPING_R6_REGIONS_REVIEW",
                    "source_zip_sha256":inspected["zip_sha256"],
                    "handoff_sha256":sha256(data).hexdigest()}
        valid.append(row)
    return {"trusted_regions":valid[:24],
            "review_regions":review,
            "evidence_status":"SAFE_SOURCE_BOUND_SEGMENTS" if valid else
                              "SOLO_REVIEW_PROPOSALS_ONLY" if review else
                              "NO_VERIFIED_R6_SOLO_REGIONS",
            "source":"ANALYZER_R6_CANONICAL",
            "source_zip_sha256":inspected["zip_sha256"],
            "handoff_sha256":sha256(data).hexdigest()}
