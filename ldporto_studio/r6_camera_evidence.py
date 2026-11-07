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
    result={"trusted_regions":[],"evidence_status":"NO_R6_CAMERA_EVIDENCE",
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
    for row in handoff.get("segments",[]):
        if not isinstance(row,dict) or row.get("recommended_composition")!="FOCUS_PERSON_9X16":
            continue
        evidence=row.get("evidence") or {}
        rect=((row.get("crop") or {}).get("rect_end"))
        if (evidence.get("crop_geometrically_valid") is not True or
                not isinstance(rect,dict) or
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
        regions.append({"start":round(left-start,3),"end":round(right-start,3),
                        "x":round(normalized,6),
                        "source":"ANALYZER_R6_SAFE_SOLO",
                        "director_id":row.get("director_id")})
    regions=sorted(regions,key=lambda r:(r["start"],r["end"]))
    valid=[]
    for row in regions:
        if valid and row["start"]<valid[-1]["end"]-0.001:
            # Do not guess which conflicting source director region is right.
            return {**result,"evidence_status":"OVERLAPPING_R6_REGIONS_REVIEW",
                    "source_zip_sha256":inspected["zip_sha256"],
                    "handoff_sha256":sha256(data).hexdigest()}
        valid.append(row)
    return {"trusted_regions":valid[:24],
            "evidence_status":"SAFE_SOURCE_BOUND_SEGMENTS" if valid else
                              "NO_VERIFIED_R6_SOLO_REGIONS",
            "source":"ANALYZER_R6_CANONICAL",
            "source_zip_sha256":inspected["zip_sha256"],
            "handoff_sha256":sha256(data).hexdigest()}
