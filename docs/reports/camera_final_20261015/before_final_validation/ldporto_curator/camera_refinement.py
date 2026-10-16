"""Evidence-driven final camera: persistence, shot reset, geometry, bounded motion and GC."""
from collections import defaultdict
import math
from .director_config import resolve_config
from .camera_evidence import VisualTargetEvidence, camera_state
from .camera_geometry import geometry, crop_rect, contains, base_size, subject_box
from .camera_motion import CameraMotion
from .temporal import IntervalCursor
from .broadcast_graphics import face_safe_height


def use_analyzer_director(director, start, end, minimum_coverage=.8):
    def valid(r):
        try:
            cam=r['camera']
            centers=[cam['center_start'],cam['center_end']]
            return (r['end']>start and r['start']<end and r['end']>r['start'] and r.get('focus_person') and r.get('source_shot_id')
                and r.get('layout')=='single_person' and (r.get('crop') or {}).get('safe') is True
                and float(r.get('focus_confidence') or 0)>=.85
                and r.get('camera_evidence_role') in {'CONFIRMED_SPEAKER','PROBABLE_SPEAKER','DOMINANT_FACE'}
                and all(math.isfinite(float(cam.get(key, 1))) and 1 <= float(cam.get(key, 1)) <= 1.35
                        for key in ('zoom_start', 'zoom_end'))
                and all(len(center)==2 and all(math.isfinite(float(x)) and 0<=x<=1 for x in center) for center in centers))
        except (KeyError,TypeError,ValueError):
            return False
    eligible=sorted((r for r in director if valid(r)),key=lambda r:r['start'])
    covered,until=0.,start
    for row in eligible:
        a,b=max(start,row['start'],until),min(end,row['end'])
        if b>a:
            covered+=b-a
            until=b
    coverage=covered/(end-start)
    if coverage < minimum_coverage:
        return None
    rows, previous = [], start
    for r in eligible:
        a, b = max(start, r['start'], previous), min(end, r['end'])
        if b <= a:
            continue
        if a > previous:
            rows.append({'start': previous - start, 'end': a - start, 'mode': 'full_frame_blur', 'reason': 'SOURCE_PRESERVE'})
        cam = r['camera']
        def center_at(time):
            fraction = (time - r['start']) / (r['end'] - r['start'])
            eased = fraction * fraction * (3 - 2 * fraction)
            return [x + (y - x) * eased for x,y in zip(cam['center_start'], cam['center_end'])]
        first, last = center_at(a), center_at(b)
        rows.append({'start': a - start, 'end': b - start, 'mode': 'crop', 'person_id': r['focus_person'],
                     'center_x': first[0], 'center_x_start': first[0], 'center_x_end': last[0],
                     'center_y_start': first[1], 'center_y_end': last[1],
                     'zoom': min(cam.get('zoom_start', 1), cam.get('zoom_end', 1)), 'motion_follow': True, 'motion_easing': 'smoothstep',
                     'subject_screen_y': .5,
                     'evidence_role': r['camera_evidence_role'], 'speaker_identity_confirmed': r.get('speaker_identity_confirmed', False),
                     'source_shot_id': r['source_shot_id'], 'reason': 'ANALYZER_SAFE_TARGET', 'crop_safe': True})
        previous = b
    if previous < end:
        rows.append({'start': previous - start, 'end': end - start, 'mode': 'full_frame_blur', 'reason': 'SOURCE_PRESERVE'})
    return {'schema_version': '4.4.0', 'mode': 'adaptive_timeline', 'segments': rows,
            'visual_source': 'analyzer_director', 'needs_review': True,
            'diagnostics': {'analyzer_safe_focus_fraction': coverage, 'micro_perception_skipped': True}}


def _render_rect(metadata, style, center_x, center_y=.5, zoom=1., source_height=1., output_height=1.):
    width,height=metadata['width'],metadata['height']
    if abs(metadata.get('rotation',0)) % 180:
        width,height=height,width
    aspect=style['output_width']/(style['output_height']*output_height)
    source_aspect=width/(height*source_height)
    w,h=(height*source_height*aspect/width,source_height) if source_aspect>aspect else (1.,width/aspect/height)
    w,h=w/zoom,h/zoom
    return {'x':max(0.,min(1.-w,center_x-w/2)), 'y':max(0.,min(source_height-h,center_y-h/2)), 'width':w,'height':h}


def refine_camera_plan(micro, metadata, start, end, cfg=None, suggested_layout=None):
    cfg = cfg or {}
    style = resolve_config({**cfg.get('director_style', {}), 'dominant_face_fallback': True})
    observations = defaultdict(dict)
    times = {float(start), float(end)}
    for row in micro.get('observations', []):
        if start <= row['time'] < end:
            observations[row['time']][row['person_id']] = row
            times.add(row['time'])
    times.update(r['time'] for r in micro.get('frames', []) if start <= r['time'] < end)
    for shot in micro.get('shots', []):
        times.update(t for t in (shot['start'], shot['end']) if start <= t <= end)
    times = sorted(times)
    shots = IntervalCursor(micro.get('shots', []))
    graphics = IntervalCursor((micro.get('broadcast_graphics') or {}).get('intervals', []))
    tracker = VisualTargetEvidence()
    current_shot, mode, focus, pair, current_geo = None, 'full_frame_blur', None, (), None
    since, outside_since, controller = start, None, CameraMotion()
    track_first, rows, switches, unsafe, resets = {}, [], 0, 0, 0
    split_anchors = {}
    for t, until in zip(times, times[1:]):
        shot = next(iter(shots.at(t + 1e-6)), {})
        sid = shot.get('shot_id')
        reset = sid != current_shot or not rows
        if reset:
            current_shot, mode, focus, pair, current_geo = sid, 'full_frame_blur', None, (), None
            tracker, track_first, controller = VisualTargetEvidence(), {}, CameraMotion()
            since, outside_since = t, None
            split_anchors = {}
            resets += 1
        obs = observations.get(t, {})
        current_ids = set(obs)
        track_first = {p: first for p, first in track_first.items() if p in current_ids}
        for p in obs:
            track_first.setdefault(p, t)
        dominant = tracker.update(obs, t, sid, style)
        g_rows = list(graphics.at(t + 1e-6))
        regions = [r for g in g_rows for r in g.get('regions', [])]
        panel_height = face_safe_height({'regions': regions})
        face_overlap = any(o['face_bbox']['y'] + o['face_bbox']['height'] + .04 > panel_height for o in obs.values()) if panel_height < 1 else False
        safe = {p: geometry([row], metadata, style) for p, row in obs.items()}
        safe = {p: g for p, g in safe.items() if g['safe'] and float(obs[p].get('detection_confidence') or 0) >= style['minimum_target_confidence']}
        desired, target, targets, geo = 'full_frame_blur', None, (), None
        reason, evidence = 'INSUFFICIENT_VISUAL_EVIDENCE', 'SOURCE_PRESERVE'
        if dominant and dominant['person_id'] in safe and not face_overlap and suggested_layout != 'source_preserve':
            target = dominant['person_id']
            if obs[target]['face_bbox']['height'] < .42:
                desired, geo, reason, evidence = 'crop', safe[target], 'DOMINANT_FACE', 'DOMINANT_FACE'
        stable_pair = tuple(sorted(p for p in safe if t - track_first[p] >= style['minimum_face_duration']))
        if (len(obs) == len(stable_pair) == 2 and target is None and not face_overlap and suggested_layout not in {'single_speaker', 'source_preserve'}
                and (suggested_layout in {'two_shot', 'split_screen', 'speaker_reaction'} or cfg.get('allow_stable_two_face_layout', True))):
            union = geometry([obs[p] for p in stable_pair], metadata, style)
            if union['safe'] and suggested_layout != 'split_screen':
                desired, targets, geo = 'crop', stable_pair, union
                reason, evidence = 'TWO_STABLE_FACES_SAFE_UNION', 'TWO_SHOT'
            else:
                # Panel aspect differs from a single vertical crop; keep real face/head bounds.
                valid_panels = all(obs[p]['face_bbox']['height'] + style['headroom'] + .08 <= panel_height for p in stable_pair)
                if valid_panels:
                    desired, targets, reason, evidence = 'split_screen', stable_pair, 'TWO_STABLE_FACES_UNRESOLVED_VOICE', 'TWO_SHOT'
        lost = mode in {'crop', 'split_screen'} and ((focus and focus not in safe) or (pair and not set(pair) <= safe.keys()))
        if face_overlap:
            desired, target, targets, reason = 'full_frame_blur', None, (), 'GRAPHICS_FACE_COLLISION_PRESERVE_SOURCE'
        if suggested_layout == 'source_preserve':
            desired, target, targets, reason = 'full_frame_blur', None, (), 'SECOND_CURATOR_SOURCE_PRESERVE'
        request = (desired, target, targets)
        changed = request != (mode, focus, pair)
        if changed and not reset and not lost and not face_overlap and t - since < style['min_hold_seconds']:
            desired, target, targets, geo = mode, focus, pair, current_geo
            evidence = rows[-1]['evidence_role']
            reason = 'MINIMUM_DWELL_HOLD'
            changed = False
        transition = 'source_cut' if reset else 'cut' if changed else 'hold'
        if changed or reset:
            if changed and not reset:
                switches += 1
            mode, focus, pair, current_geo = desired, target, targets, geo
            since = t
            controller = CameraMotion(*(geo['center'] if geo else [.5, .5]), 1.)
        else:
            mode, focus, pair = desired, target, targets
        if mode == 'crop':
            live = [obs[p] for p in ([focus] if focus else pair) if p in obs]
            geo = geometry(live, metadata, style) if live else {'safe': False}
            before = controller.snapshot(t)
            if geo['safe']:
                controller.move([*geo['center'], 1.], t, until - t, style)
                rect = crop_rect([controller.x.position, controller.y.position], controller.zoom.position, base_size(metadata, style))
                if not contains(rect, geo['subject_bounds']):
                    geo = {'safe': False}
            if not geo['safe']:
                mode, focus, pair, current_geo = 'full_frame_blur', None, (), None
                controller = CameraMotion()
                since = t
                transition, reason, evidence = 'safety_cut', 'UNSAFE_MOTION_OR_MISSING_FACE', 'SOURCE_PRESERVE'
                unsafe += 1
            after = controller.snapshot(until)
        else:
            before, after = controller.snapshot(t), controller.snapshot(until)
        if mode == 'split_screen':
            if changed or reset or set(split_anchors) != set(pair):
                split_anchors = {p:obs[p]['face_bbox']['x']+obs[p]['face_bbox']['width']/2 for p in pair}
            panel_fraction=.44 if regions else .5
            panel_safe=all(contains(_render_rect(metadata,style,split_anchors[p],panel_height/2,source_height=panel_height,output_height=panel_fraction),
                                    subject_box(obs[p],style)) for p in pair)
            if not panel_safe:
                mode,focus,pair,current_geo='full_frame_blur',None,(),None
                since=t
                transition,reason,evidence='safety_cut','STATIC_SPLIT_TARGET_LEFT_SAFE_PANEL','SOURCE_PRESERVE'
                unsafe+=1
        elif mode == 'crop' and regions:
            subjects=[obs[p] for p in ([focus] if focus else pair) if p in obs]
            delivered=_render_rect(metadata,style,after['center'][0],after['center'][1],source_height=panel_height,output_height=.88)
            if not subjects or any(not contains(delivered,subject_box(o,style)) for o in subjects):
                mode,focus,pair,current_geo='full_frame_blur',None,(),None
                since=t
                transition,reason,evidence='safety_cut','GRAPHICS_CROP_DOES_NOT_FIT_HEAD','SOURCE_PRESERVE'
                unsafe+=1
        row = {'start': t - start, 'end': until - start, 'mode': mode, 'person_id': focus,
            'person_ids': list(pair), 'source_shot_id': sid, 'center_x': after['center'][0], 'center_y': after['center'][1],
            'center_x_start': before['center'][0], 'center_x_end': after['center'][0],
            'center_y_start': before['center'][1], 'center_y_end': after['center'][1],
            'zoom': 1., 'motion_follow': mode == 'crop', 'motion_easing': 'smoothstep',
            'subject_screen_y': .5,
            'reason': reason, 'evidence_role': evidence if mode != 'full_frame_blur' else 'SOURCE_PRESERVE',
            'speaker_identity_confirmed': False, 'speaker_evidence': False,
            'graphics_policy': 'single_copy_source_strip' if regions else 'none', 'graphics_regions': regions,
            'panel_source_height': panel_height, 'crop_safe': mode != 'crop' or geo.get('safe', False),
            'camera_state': camera_state(transition, 'two_shot' if pair and mode == 'crop' else 'split_candidate' if mode == 'split_screen' else 'single_person' if mode == 'crop' else 'full_frame',
                                         'pan' if math.dist(before['center'], after['center']) > .001 else 'hold'),
            'needs_review': True}
        if mode == 'split_screen':
            row['split_centers_x'] = sorted(split_anchors[p] for p in pair)
        signature = (sid, mode, focus, pair, row['evidence_role'], panel_height)
        if rows and rows[-1]['_signature'] == signature and transition == 'hold':
            prior = rows[-1]
            prior.update(end=row['end'], center_x_end=row['center_x_end'], center_y_end=row['center_y_end'])
        else:
            row['_signature'] = signature
            rows.append(row)
    for row in rows:
        row.pop('_signature', None)
    duration = end - start
    resolved = sum(s['end'] - s['start'] for s in rows if s['mode'] != 'full_frame_blur')
    actual_switches = sum(a['source_shot_id'] == b['source_shot_id'] and
        (a['mode'],a['person_id'],a['person_ids']) != (b['mode'],b['person_id'],b['person_ids']) for a,b in zip(rows,rows[1:]))
    return {'schema_version': '4.4.0', 'mode': 'adaptive_timeline', 'segments': rows, 'visual_source': 'clip_micro_perception',
            'normalized_center_x': .5, 'dynamic_active_speaker': False, 'speaker_evidence_segments': 0,
            'uncertain_two_face_segments': sum(s['mode'] == 'split_screen' for s in rows), 'motion_segments': sum(s['motion_follow'] for s in rows),
            'diagnostics': {'target_switches': actual_switches, 'proposed_target_switches':switches, 'shot_resets': resets, 'unsafe_crop_avoided': unsafe,
                            'resolved_visual_focus_fraction': resolved / duration, 'zoom_factor': 1.,
                            'speaker_identity_confirmed_count': 0, 'graphics_intervals': len((micro.get('broadcast_graphics') or {}).get('intervals', []))},
            'needs_review': True}
