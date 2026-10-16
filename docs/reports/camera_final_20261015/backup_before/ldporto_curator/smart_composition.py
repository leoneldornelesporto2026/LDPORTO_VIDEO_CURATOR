"""Guarded portrait composition after clip-local camera perception.

Decisions are proposals, not approval. Unmeasured map motion is never invented.
The engine never runs during preview re-use or approval; only on explicit camera
plan generation. All output modes already exist in the V4.4 renderer.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
from collections import defaultdict

from .camera_geometry import base_size, contains, crop_rect, geometry, subject_box
from .director_config import resolve_config

_MAP_KINDS = {'map', 'route_map', 'aircraft_route'}
_SHA = re.compile(r'^[a-fA-F0-9]{64}$')


def _finite(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _bbox(b):
    if not isinstance(b, dict):
        return None
    xywh = [_finite(b.get(k)) for k in ('x', 'y', 'width', 'height')]
    if any(v is None for v in xywh):
        return None
    x, y, w, h = xywh
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        return None
    return [x, y, x+w, y+h]


def _map_evidence(region, start, end):
    """Only frame-located and *explicitly reviewed* visual evidence can steer map crop.

    Spoken words ('mapa', 'aviao') and scene summaries have no spatial proof.
    """
    if not isinstance(region, dict) or region.get('kind') not in _MAP_KINDS:
        return None
    if region.get('evidence_kind') != 'visual_region' or region.get('reviewed') is not True:
        return None
    a, b = _finite(region.get('start')), _finite(region.get('end'))
    if a is None or b is None or a >= b or a < start or b > end:
        return None
    samples = region.get('samples')
    if not isinstance(samples, list) or len(samples) < 3:
        return None
    seen, boxes = set(), []
    for sample in samples:
        if not isinstance(sample, dict):
            return None
        t = _finite(sample.get('observed_at'))
        box = _bbox(sample.get('bbox'))
        if (t is None or t < a or t > b or not box or
                not _SHA.fullmatch(str(sample.get('frame_sha256') or ''))):
            return None
        seen.add(round(t, 4))
        boxes.append(box)
    if len(seen) < 3 or max(seen) - min(seen) < 0.5:
        return None
    union = [min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes)]
    # Real visual samples must cover the interval, not an isolated moment.
    if min(seen) > a + max(.5, (b-a)*.2) or max(seen) < b - max(.5, (b-a)*.2):
        return None
    return a, b, union, region['kind']


def _host_zoom(row, obs_times, metadata, style):
    """Restrained static zoom, checked against EVERY measured face within the row.

    No sharpness = no digital enlargement. No confirmed single-face samples = no zoom.
    """
    if (row.get('mode') != 'crop' or not row.get('person_id') or
            row.get('graphics_policy') == 'single_copy_source_strip' or
            row.get('reason') in {'SOURCE_PRESERVE', 'ANALYZER_SAFE_TARGET'}):
        return False
    a, b = float(row['start']), float(row['end'])
    if b - a < 4.0 or row.get('zoom', 1.) > 1.0001:
        return False
    pid = str(row['person_id'])
    samples = []
    for time, group in obs_times.items():
        if a - 1e-5 <= time <= b + 1e-5:
            faces = [r for r in group if r.get('face_visible') and r.get('face_bbox')]
            if len(faces) != 1 or str(faces[0].get('person_id')) != pid:
                return False
            samples.append((time, faces[0]))
    if len(samples) < 8 or samples[-1][0] - samples[0][0] < 3.:
        return False
    requested = 1.045  # Under 5%; no theatrical snap-ins.
    geo = geometry([o for _, o in samples], metadata, style, requested_zoom=requested)
    if not geo.get('safe') or geo.get('actual_zoom', 1.) < requested - 1e-4 or geo.get('quality_unknown'):
        return False
    base = base_size(metadata, style)
    start_x = _finite(row.get('center_x_start', row.get('center_x', .5)))
    end_x = _finite(row.get('center_x_end', row.get('center_x', .5)))
    start_y = _finite(row.get('center_y_start', .5))
    end_y = _finite(row.get('center_y_end', .5))
    if None in (start_x, end_x, start_y, end_y):
        return False
    for t, obs in samples:
        alpha = min(1., max(0., (t-a) / max(b-a, .001)))
        # Keep the crop safe along the path, not just at its endpoints.
        cx = start_x + (end_x-start_x)*alpha
        cy = start_y + (end_y-start_y)*alpha
        if not contains(crop_rect((cx,cy), requested, base), subject_box(obs, style)):
            return False
    row['zoom'] = requested
    row['reason'] = str(row.get('reason') or '') + '+SAFE_HOST_MICRO_ZOOM'
    row['zoom_evidence'] = 'face_geometry_sharpness_verified'
    return True


def _map_compose(row, evidence, metadata, style):
    """Map/aircraft ROI only when observed spatial geometry can fit a 9:16 crop.

    If critical map detail is wider than portrait, never crop it away.
    """
    a, b, union, kind = evidence
    rec = deepcopy(row)
    base = base_size(metadata, style)
    if not base:
        return None
    # Breathing margins around labels/route; no crop forced on wide maps.
    margin = .025
    box = [max(0., union[0]-margin), max(0., union[1]-margin),
           min(1., union[2]+margin), min(1., union[3]+margin)]
    x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
    rect = crop_rect((x,y), 1., base)
    rec['start'], rec['end'] = a, b
    rec['needs_review'] = True
    rec['visual_content'] = kind
    rec['zoom_evidence'] = 'reviewed_visual_samples'
    if contains(rect, box):
        rec.update(mode='crop', person_id=None, person_ids=[], motion_follow=False,
                   zoom=1., center_x=x, center_y_start=y, center_y_end=y,
                   center_x_start=x, center_x_end=x,
                   reason='MAP_SPATIAL_ROI_SAFE', evidence_role='MEASURED_MAP_ROI',
                   crop_safe=True, graphics_policy='none')
    else:
        rec.update(mode='full_frame_blur', person_id=None, person_ids=[], motion_follow=False,
                   zoom=1., reason='MAP_WIDE_KEEP_ALL_LABELS', evidence_role='SOURCE_PRESERVE',
                   crop_safe=True)
    return rec


def improve_camera_plan(plan, micro, metadata, start, end, cfg=None):
    """Add safe portrait crop/zoom and map-composition decisions to a NEW plan.

    Preserves ids, timestamps, input objects, and original revision immutability.
    Measured map regions are optional: without them maps stay source-preserved.
    """
    out = deepcopy(plan)
    if not isinstance(out, dict) or out.get('mode') != 'adaptive_timeline':
        return out
    micro = micro if isinstance(micro, dict) else {}
    style = resolve_config((cfg or {}).get('director_style', {}))
    before = out.get('segments') or []
    if not before or base_size(metadata, style) is None:
        return out
    valid_maps = []
    for item in micro.get('visual_focus_regions') or []:
        checked = _map_evidence(item, start, end)
        if checked:
            valid_maps.append(checked)
    # Reject overlapping or conflicting annotations instead of arbitrating guesses.
    valid_maps.sort(key=lambda item: item[0])
    if any(b[0] < a[1] for a, b in zip(valid_maps, valid_maps[1:])):
        valid_maps = []
    modified = []
    map_count = wide_count = 0
    for segment in before:
        original_start, original_end = float(segment['start']), float(segment['end'])
        cur = original_start
        boundaries = [original_start, original_end]
        for m in valid_maps:
            boundaries.extend([max(original_start, min(original_end, m[0]-start)),
                               max(original_start, min(original_end, m[1]-start))])
        boundaries = sorted(set(round(v, 6) for v in boundaries))
        for a, b in zip(boundaries, boundaries[1:]):
            if b-a < 1e-6:
                continue
            part = deepcopy(segment)
            part['start'], part['end'] = a, b
            evidence = next((m for m in valid_maps if m[0]-start <= a+1e-5 and b <= m[1]-start+1e-5), None)
            if evidence:
                composed = _map_compose(part, (a,b,evidence[2],evidence[3]), metadata, style)
                if composed:
                    part = composed
                    map_count += (part['mode'] == 'crop')
                    wide_count += (part['mode'] == 'full_frame_blur')
            modified.append(part)
    # Tiny guard: zoom only on original, unsplit host segments; never add zoom to maps.
    obs_times = defaultdict(list)
    for row in micro.get('observations') or []:
        try:
            t = float(row['time']) - float(start)
            if math.isfinite(t):
                obs_times[t].append(row)
        except (KeyError, ValueError, TypeError):
            pass
    zooms = 0
    if not valid_maps:
        for row in modified:
            zooms += bool(_host_zoom(row, obs_times, metadata, style))
    out['segments'] = modified
    out.setdefault('diagnostics', {})['content_aware_camera'] = {
        'host_micro_zoom_segments': int(zooms),
        'map_spatial_roi_segments': int(map_count),
        'map_wide_source_preserved_segments': int(wide_count),
        'unvalidated_map_crops_generated': 0,
        'policy': 'host_stable_safe_zoom; reviewed_map_region_only; wide_preserve_source',
        'quality_claim': 'human_review_required',
    }
    out['needs_review'] = True
    return out
