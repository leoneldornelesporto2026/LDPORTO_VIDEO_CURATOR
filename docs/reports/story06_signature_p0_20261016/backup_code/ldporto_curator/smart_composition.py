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
from .camera_motion import ease_in_out

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
    """One optional eased push, checked against EVERY measured face within a shot.

    No sharpness = no digital enlargement. No confirmed single-face samples = no zoom.
    """
    if (row.get('mode') != 'crop' or not row.get('person_id') or
            row.get('graphics_policy') == 'single_copy_source_strip' or
            row.get('reason') in {'SOURCE_PRESERVE', 'ANALYZER_SAFE_TARGET'}):
        return False
    zoom_cfg = style['smart_zoom']
    if not zoom_cfg['enabled'] or zoom_cfg['micro_zoom_factor'] <= 1.0001:
        return False
    a, b = float(row['start']), float(row['end'])
    hold = zoom_cfg['micro_zoom_min_hold_seconds']
    duration = min(zoom_cfg['micro_zoom_duration'], b-a-hold)
    if duration < 3. or row.get('zoom', 1.) > 1.0001:
        return False
    pid = str(row['person_id'])
    samples = []
    for time, group in obs_times.items():
        if a - 1e-5 <= time < b - 1e-5:
            faces = [r for r in group if r.get('face_visible') and r.get('face_bbox')]
            if len(faces) != 1 or str(faces[0].get('person_id')) != pid:
                return False
            samples.append((time, faces[0]))
    samples.sort(key=lambda item: item[0])
    gap = style['max_observation_gap_seconds']
    if (len(samples) < 8 or samples[-1][0] - samples[0][0] < 3.
            or samples[0][0] > a+gap or samples[-1][0] < b-gap
            or any(right[0]-left[0] > gap+1e-6 for left, right in zip(samples, samples[1:]))):
        return False
    requested = min(zoom_cfg['micro_zoom_factor'], zoom_cfg['max_zoom_factor'])
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
        if row.get('motion_easing') == 'smoothstep':
            alpha = ease_in_out(alpha)
        # Keep the crop safe along the path, not just at its endpoints.
        cx = start_x + (end_x-start_x)*alpha
        cy = start_y + (end_y-start_y)*alpha
        if not contains(crop_rect((cx,cy), requested, base), subject_box(obs, style)):
            return False
        # Faces must stay clear of the lower caption band. A measured shoulder
        # or hand may extend below it; moving the captions is never necessary.
        rect = crop_rect((cx,cy), requested, base)
        face = obs['face_bbox']
        if (face['y']+face['height']-rect['y'])/rect['height'] > .72:
            return False
    row['zoom'] = requested
    row['zoom_start'], row['zoom_end'] = 1., requested
    row['zoom_transition_start'] = hold
    row['zoom_transition_duration'] = duration
    row['zoom_easing'] = 'smoothstep'
    row['reason'] = str(row.get('reason') or '') + '+SAFE_HOST_MICRO_ZOOM'
    row['zoom_evidence'] = 'face_geometry_sharpness_verified'
    return True


def _slice_segment(segment, start, end):
    """Retain the source position when a measured visual region splits a row."""
    out = deepcopy(segment)
    a, b = float(segment['start']), float(segment['end'])
    if abs(start-a) < 1e-8 and abs(end-b) < 1e-8:
        return out
    for axis in ('x', 'y'):
        first = float(segment.get('center_'+axis+'_start', segment.get('center_'+axis, .5)))
        last = float(segment.get('center_'+axis+'_end', first))
        def at(time):
            fraction = min(1., max(0., (time-a)/max(b-a, 1e-9)))
            if segment.get('motion_easing') == 'smoothstep':
                fraction = ease_in_out(fraction)
            return first+(last-first)*fraction
        out['center_'+axis+'_start'], out['center_'+axis+'_end'] = at(start), at(end)
    out['center_x'] = out['center_x_start']
    out['start'], out['end'] = start, end
    return out


def _protect_measured_host(row, obs_times, metadata, style):
    """Recheck the *delivered* merged path, including measured shoulders/hands."""
    if row.get('mode') != 'crop' or not row.get('person_id') or not obs_times:
        return False
    a, b = float(row['start']), float(row['end'])
    pid = str(row['person_id'])
    samples = [(t, next((o for o in group if str(o.get('person_id')) == pid), None))
               for t, group in sorted(obs_times.items()) if a-1e-6 <= t < b-1e-6]
    gap = style['max_observation_gap_seconds']
    reason = None
    if (not samples or samples[0][0] > a+gap or samples[-1][0] < b-gap
            or any(right[0]-left[0] > gap+1e-6 for left, right in zip(samples, samples[1:]))):
        reason = 'HOST_MEASUREMENT_GAP_PRESERVE_SOURCE'
    base = base_size(metadata, style)
    for time, observation in samples:
        if reason:
            break
        if observation is None:
            reason = 'HOST_TARGET_UNOBSERVED_PRESERVE_SOURCE'
            break
        geo = geometry([observation], metadata, style, requested_zoom=float(row.get('zoom', 1.)))
        alpha = min(1., max(0., (time-a)/max(b-a, 1e-9)))
        if row.get('motion_easing') == 'smoothstep':
            alpha = ease_in_out(alpha)
        center = [float(row.get('center_'+axis+'_start', row.get('center_'+axis, .5)))+
                  (float(row.get('center_'+axis+'_end', row.get('center_'+axis, .5)))-
                   float(row.get('center_'+axis+'_start', row.get('center_'+axis, .5))))*alpha
                  for axis in ('x', 'y')]
        # GC layouts have their own panel certificate in refine_camera_plan.
        if (not geo.get('safe') or (not row.get('graphics_regions') and
                not contains(crop_rect(center, float(row.get('zoom', 1.)), base), geo.get('subject_bounds')))):
            reason = 'HOST_BODY_OR_MOTION_UNSAFE_PRESERVE_SOURCE'
    if reason:
        row.update(mode='full_frame_blur', person_id=None, person_ids=[], motion_follow=False,
                   zoom=1., reason=reason, fallback_reason=reason, evidence_role='SOURCE_PRESERVE')
        for key in ('zoom_start', 'zoom_end', 'zoom_transition_start', 'zoom_transition_duration', 'zoom_easing'):
            row.pop(key, None)
        return True
    return False


def _stabilize_focus(rows, style):
    """Do not briefly enter a portrait crop that cannot meet minimum dwell.

    Safety exits are immediate. We suppress the whole brief proposal instead
    of holding an unsafe crop or hiding an actual source cut.
    """
    suppressed, merged = 0, []
    for row in rows:
        if row.get('mode') == 'crop' and float(row['end'])-float(row['start']) < style['min_hold_seconds']-1e-6:
            row.update(mode='full_frame_blur', person_id=None, person_ids=[], motion_follow=False,
                       zoom=1., reason='SHORT_UNSTABLE_FOCUS_PRESERVE_SOURCE',
                       fallback_reason='MINIMUM_FOCUS_DWELL_NOT_AVAILABLE', evidence_role='SOURCE_PRESERVE')
            for key in ('zoom_start', 'zoom_end', 'zoom_transition_start', 'zoom_transition_duration', 'zoom_easing'):
                row.pop(key, None)
            suppressed += 1
        prior = merged[-1] if merged else None
        if (prior and prior.get('mode') == row.get('mode') == 'full_frame_blur'
                and prior.get('source_shot_id') == row.get('source_shot_id')
                and prior.get('visual_content') == row.get('visual_content')
                and abs(float(prior['end'])-float(row['start'])) < 1e-5):
            reasons = prior.setdefault('source_preserve_reasons', [prior.get('reason')])
            if row.get('reason') not in reasons:
                reasons.append(row.get('reason'))
            prior['end'] = row['end']
            for region in row.get('graphics_regions') or []:
                if region not in prior.setdefault('graphics_regions', []):
                    prior['graphics_regions'].append(deepcopy(region))
            if prior.get('graphics_regions'):
                prior['graphics_policy'] = 'single_copy_source_strip'
        else:
            merged.append(row)
    return merged, suppressed


def _mark_focus_transitions(rows, seconds):
    """Blend compositions of identical frames only inside a verified source shot."""
    for index, row in enumerate(rows):
        row.pop('focus_transition_in', None)
        row.pop('focus_transition_out', None)
        if (seconds <= 0 or row.get('mode') != 'crop' or not row.get('person_id')
                or not row.get('source_shot_id') or not row.get('motion_follow')
                or row.get('graphics_regions') or row.get('graphics_policy') == 'single_copy_source_strip'):
            continue
        duration = min(seconds, (float(row['end'])-float(row['start']))/4)
        for neighbor_index, field in ((index-1,'focus_transition_in'),(index+1,'focus_transition_out')):
            if not 0 <= neighbor_index < len(rows):
                continue
            neighbor = rows[neighbor_index]
            # A different GC background composition needs its own certificate.
            lower = any(r.get('persistent') and r.get('y_start',0) > .4
                        for r in neighbor.get('graphics_regions') or [])
            boundary = (float(neighbor['end'])-float(row['start']) if neighbor_index < index else
                        float(row['end'])-float(neighbor['start']))
            if (neighbor.get('mode') == 'full_frame_blur' and not lower
                    and neighbor.get('source_shot_id') == row['source_shot_id'] and abs(boundary) < 1e-5):
                row[field] = duration


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
    resolution = min(base[0]*base[2]/style['output_width'], base[1]*base[3]/style['output_height'])
    quality_ok = resolution*style['smart_zoom']['max_upscale_ratio'] >= 1.
    # Source graphics may change the available subject panel; do not reuse a
    # whole-source crop certificate for that different renderer composition.
    graphics_ok = not row.get('graphics_regions')
    for key in ('zoom_start', 'zoom_end', 'zoom_transition_start', 'zoom_transition_duration', 'zoom_easing'):
        rec.pop(key, None)
    if contains(rect, box) and quality_ok and graphics_ok:
        rec.update(mode='crop', person_id=None, person_ids=[], motion_follow=True,
                   zoom=1., center_x=x, center_y_start=y, center_y_end=y,
                   center_x_start=x, center_x_end=x,
                   subject_screen_y=.5, motion_easing='smoothstep',
                   reason='MAP_SPATIAL_ROI_SAFE', evidence_role='MEASURED_MAP_ROI',
                   crop_safe=True, graphics_policy='none')
    else:
        reason = ('MAP_GRAPHICS_PRESERVE_SOURCE' if not graphics_ok else
                  'MAP_RESOLUTION_PRESERVE_SOURCE' if not quality_ok else 'MAP_WIDE_KEEP_ALL_LABELS')
        rec.update(mode='full_frame_blur', person_id=None, person_ids=[], motion_follow=False,
                   zoom=1., reason=reason, evidence_role='SOURCE_PRESERVE',
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
    for segment in before:
        original_start, original_end = float(segment['start']), float(segment['end'])
        boundaries = [original_start, original_end]
        for m in valid_maps:
            boundaries.extend([max(original_start, min(original_end, m[0]-start)),
                               max(original_start, min(original_end, m[1]-start))])
        boundaries = sorted(set(round(v, 6) for v in boundaries))
        for a, b in zip(boundaries, boundaries[1:]):
            if b-a < 1e-6:
                continue
            part = _slice_segment(segment, a, b)
            evidence = next((m for m in valid_maps if m[0]-start <= a+1e-5 and b <= m[1]-start+1e-5), None)
            if evidence:
                composed = _map_compose(part, (a,b,evidence[2],evidence[3]), metadata, style)
                if composed:
                    part = composed
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
    guarded = sum(_protect_measured_host(row, obs_times, metadata, style) for row in modified)
    modified, suppressed = _stabilize_focus(modified, style)
    if not valid_maps:
        for row in modified:
            zooms += bool(_host_zoom(row, obs_times, metadata, style))
    _mark_focus_transitions(modified, style['focus_transition_seconds'])
    out['segments'] = modified
    diagnostics = out.setdefault('diagnostics', {})
    diagnostics['resolved_visual_focus_fraction'] = sum(float(r['end'])-float(r['start'])
        for r in modified if r.get('mode') != 'full_frame_blur')/max(float(end)-float(start), 1e-9)
    diagnostics['zoom_factor'] = max((r.get('zoom',1.) for r in modified), default=1.)
    out['motion_segments'] = sum(bool(r.get('motion_follow')) for r in modified)
    diagnostics['content_aware_camera'] = {
        'host_micro_zoom_segments': int(zooms),
        'map_spatial_roi_segments': sum(r.get('mode') == 'crop' and r.get('visual_content') in _MAP_KINDS for r in modified),
        'map_wide_source_preserved_segments': sum(r.get('mode') == 'full_frame_blur' and r.get('visual_content') in _MAP_KINDS for r in modified),
        'unvalidated_map_crops_generated': 0,
        'unsafe_host_paths_preserved': int(guarded),
        'brief_focus_proposals_suppressed': int(suppressed),
        'focus_transition_segments': sum(bool(r.get('focus_transition_in') or r.get('focus_transition_out')) for r in modified),
        'focus_transition_seconds': style['focus_transition_seconds'],
        'policy': 'host_stable_safe_zoom; reviewed_map_region_only; wide_preserve_source',
        'micro_zoom_enabled': style['smart_zoom']['enabled'],
        'micro_zoom_factor': style['smart_zoom']['micro_zoom_factor'],
        'micro_zoom_curve': 'one_smoothstep_after_minimum_hold_per_host_shot',
        'quality_claim': 'human_review_required',
    }
    out['needs_review'] = True
    return out
