from __future__ import annotations
from collections import defaultdict
import math
import statistics


def _cx(center):
    if isinstance(center, dict):
        try:
            return float(center.get('x'))
        except Exception:
            return None
    if isinstance(center, (list, tuple)) and center:
        try:
            return float(center[0])
        except Exception:
            return None
    return None


def _area(p):
    b = p.get('face_bbox') or p.get('bbox') or {}
    try:
        return max(0.0, float(b.get('width', 0))) * max(0.0, float(b.get('height', 0)))
    except Exception:
        return 0.0


def _face_bbox(p):
    return p.get('face_bbox') or (p.get('bbox') if str(p.get('bbox_kind') or '').lower() == 'face' else None)


def _positions(t):
    out = []
    for p in (t.get('people_positions') or []):
        if not p.get('safe_crop_possible', True):
            continue
        x = _cx(p.get('center'))
        if x is None:
            continue
        fb = _face_bbox(p)
        out.append({
            'x': max(0.0, min(1.0, x)),
            'area': _area(p),
            'face': bool(fb),
            'face_bbox': fb,
            'person_id': p.get('person_id'),
            'lip_opening': p.get('lip_opening'),
            'lip_activity': p.get('lip_activity'),
            'samples': int(p.get('samples') or 0),
        })
    return out


def _bbox_iou(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    try:
        ax1, ay1 = float(a.get('x', 0)), float(a.get('y', 0))
        ax2, ay2 = ax1 + float(a.get('width', 0)), ay1 + float(a.get('height', 0))
        bx1, by1 = float(b.get('x', 0)), float(b.get('y', 0))
        bx2, by2 = bx1 + float(b.get('width', 0)), by1 + float(b.get('height', 0))
    except Exception:
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aa + ba - inter
    return inter / union if union > 1e-9 else 0.0


def _distinct_face_pair(faces, layout=''):
    """Return two genuinely distinct faces.

    Track IDs can fragment the same person, so geometry wins over identity IDs.
    For observation-driven mode we also allow an empty layout if geometry clearly
    shows two separated faces in the same short time window.
    """
    if len(faces) != 2:
        return None
    if layout and ('two_person' not in layout and 'two_shot' not in layout and 'split' not in layout and 'unknown' not in layout):
        return None
    pair = sorted(faces, key=lambda p: p['x'])
    separation = pair[1]['x'] - pair[0]['x']
    if separation < 0.20:
        return None
    if _bbox_iou(pair[0].get('face_bbox'), pair[1].get('face_bbox')) > 0.08:
        return None
    return pair


def _mapping_dict(mapping_rows):
    out = {}
    for row in mapping_rows or []:
        if not isinstance(row, dict):
            continue
        speaker = row.get('speaker') or row.get('speaker_id') or row.get('label')
        person = row.get('person_id') or row.get('person') or row.get('mapped_person_id')
        conf = row.get('confidence')
        try:
            conf = float(conf) if conf is not None else 1.0
        except Exception:
            conf = 0.0
        if speaker and person and conf >= 0.50:
            out[str(speaker)] = str(person)
    return out


def _timeline_speaker_target(bundle, a_abs, b_abs, candidate_ids):
    """Use explicit Analyzer voice->person evidence when it exists."""
    candidate_ids = {str(x) for x in candidate_ids if x}
    if not candidate_ids:
        return None, None
    mapping = _mapping_dict(getattr(bundle, 'speaker_person_mapping', []))
    votes = defaultdict(float)
    reasons = defaultdict(set)
    for t in bundle.timeline:
        ta, tb = float(t.get('start', 0)), float(t.get('end', 0))
        overlap = max(0.0, min(b_abs, tb) - max(a_abs, ta))
        if overlap <= 0:
            continue
        active = t.get('active_person') or t.get('primary_person')
        if active and str(active) in candidate_ids:
            votes[str(active)] += overlap * 3.0
            reasons[str(active)].add('active_person')
        speaker = t.get('speaker')
        if speaker and str(speaker) in mapping and mapping[str(speaker)] in candidate_ids:
            pid = mapping[str(speaker)]
            votes[pid] += overlap * 4.0
            reasons[pid].add('speaker_person_mapping')
        for sp in (t.get('speakers') or []):
            if str(sp) in mapping and mapping[str(sp)] in candidate_ids:
                pid = mapping[str(sp)]
                votes[pid] += overlap * 2.0
                reasons[pid].add('speaker_person_mapping')
    if not votes:
        return None, None
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    top_pid, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if top < 0.25 or (second > 0 and top < second * 1.25):
        return None, None
    return top_pid, '+'.join(sorted(reasons[top_pid])) or 'speaker_evidence'


def _lip_target(faces, cfg):
    """Choose a face only when mouth-motion evidence is meaningfully stronger.

    `lip_activity` is computed from the Analyzer's high-frequency observations.
    We require enough samples and a clear margin to avoid random mouth-open frames.
    """
    if len(faces) < 2:
        return None
    min_samples = int(cfg.get('lip_min_samples', 3))
    min_activity = float(cfg.get('lip_min_activity', 0.035))
    margin = float(cfg.get('lip_activity_margin', 1.35))
    scored = []
    for f in faces:
        act = f.get('lip_activity')
        if act is None or int(f.get('samples') or 0) < min_samples:
            continue
        try:
            scored.append((float(act), f))
        except Exception:
            pass
    if len(scored) < 2:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top, second = scored[0], scored[1]
    if top[0] < min_activity:
        return None
    if second[0] > 1e-6 and top[0] < second[0] * margin:
        return None
    return top[1]


def _classify_interval(t, bundle=None, camera_cfg=None):
    """Choose the safest useful camera for one short interval.

    Priority:
      1) explicit speaker/person mapping or active_person
      2) clear lip/mouth activity
      3) one clear face -> crop
      4) two genuinely distinct faces -> split (never lock to the wrong one)
      5) group/ambiguity -> full-frame over blurred background
    """
    camera_cfg = camera_cfg or {}
    layout = str(t.get('recommended_layout') or '').lower()
    ps = _positions(t)
    faces = [p for p in ps if p['face']]

    if bundle is not None and faces:
        pid, why = _timeline_speaker_target(
            bundle,
            float(t.get('start', 0)),
            float(t.get('end', 0)),
            [p.get('person_id') for p in faces],
        )
        if pid:
            tgt = next((p for p in faces if str(p.get('person_id')) == str(pid)), None)
            if tgt:
                return {
                    'mode': 'crop', 'center_x': tgt['x'], 'person_id': pid,
                    'reason': why or 'speaker_evidence', 'speaker_evidence': True,
                    'protected': True,
                }

    lip = _lip_target(faces, camera_cfg)
    if lip:
        return {
            'mode': 'crop', 'center_x': lip['x'], 'person_id': lip.get('person_id'),
            'reason': 'lip_activity', 'speaker_evidence': True, 'protected': True,
        }

    if len(ps) == 1:
        return {'mode': 'crop', 'center_x': ps[0]['x'], 'reason': 'single_detection'}

    if len(faces) == 1 and len(ps) <= 2:
        return {'mode': 'crop', 'center_x': faces[0]['x'], 'reason': 'single_face_plus_aux_detection'}

    pair = _distinct_face_pair(faces, layout)
    if pair:
        return {
            'mode': 'split_screen',
            'split_centers_x': [pair[0]['x'], pair[1]['x']],
            'person_ids': [pair[0].get('person_id'), pair[1].get('person_id')],
            'reason': 'two_faces_speaker_uncertain',
            'speaker_evidence': False,
        }

    return {'mode': 'full_frame_blur', 'reason': 'ambiguous_or_group_composition'}


def _scene_for_time(bundle, t):
    for s in bundle.scenes:
        if float(s.get('start', 0)) <= t < float(s.get('end', 0)):
            return s
    return None


def _cluster_nearby_faces(items, x_tol=0.075):
    """Collapse fragmented face tracks occupying the same screen position."""
    if not items:
        return []
    items = sorted(items, key=lambda p: p['x'])
    groups = []
    for p in items:
        if not groups or abs(p['x'] - statistics.median([x['x'] for x in groups[-1]])) > x_tol:
            groups.append([p])
        else:
            groups[-1].append(p)
    out = []
    for g in groups:
        weights = [max(1e-5, float(x.get('area') or 0.0)) for x in g]
        denom = sum(weights)
        x = sum(float(item['x']) * w for item, w in zip(g, weights)) / denom
        # keep the representative with most observations / largest face
        rep = max(g, key=lambda z: (int(z.get('samples') or 0), float(z.get('area') or 0.0)))
        r = dict(rep)
        r['x'] = x
        r['area'] = statistics.median([float(z.get('area') or 0.0) for z in g])
        r['samples'] = sum(int(z.get('samples') or 0) for z in g)
        lips = [float(z['lip_opening']) for z in g if z.get('lip_opening') is not None]
        if lips:
            r['lip_opening'] = statistics.median(lips)
        acts = [float(z['lip_activity']) for z in g if z.get('lip_activity') is not None]
        if acts:
            r['lip_activity'] = max(acts)
        out.append(r)
    return out


def _summarize_observation_window(rows):
    by = defaultdict(list)
    for o in rows:
        if not o.get('face_visible'):
            continue
        if not o.get('safe_crop_possible', True):
            continue
        x = _cx(o.get('center'))
        fb = _face_bbox(o)
        if x is None or not fb:
            continue
        by[str(o.get('person_id') or f'anon_{len(by)}')].append(o)

    people = []
    for pid, xs in by.items():
        centers = [_cx(x.get('center')) for x in xs]
        centers = [x for x in centers if x is not None]
        if not centers:
            continue
        areas = [_area(x) for x in xs]
        lip = [float(x['lip_opening']) for x in xs if x.get('lip_opening') is not None]
        # Activity = temporal mouth movement + a small absolute-opening component.
        # This is intentionally conservative and only used when it clearly wins.
        lip_activity = None
        if len(lip) >= 3:
            mean = statistics.mean(lip)
            std = statistics.pstdev(lip) if len(lip) > 1 else 0.0
            lip_activity = std + 0.30 * mean
        rep = max(xs, key=lambda z: (_area(z), float(z.get('detection_confidence') or 0.0)))
        people.append({
            'person_id': pid,
            'center': {'x': statistics.median(centers), 'y': _cx({'x': 0.5}) or 0.5},
            'bbox': rep.get('bbox'),
            'bbox_kind': 'face',
            'face_bbox': rep.get('face_bbox') or rep.get('bbox'),
            'safe_crop_possible': True,
            'lip_opening': statistics.median(lip) if lip else None,
            'lip_activity': lip_activity,
            'samples': len(xs),
            '_area': statistics.median(areas) if areas else 0.0,
        })
    # `_positions` recomputes area from bbox. Keep only clusters that are spatially distinct.
    proxy = []
    for p in people:
        proxy.append({
            'x': _cx(p.get('center')) or 0.5,
            'area': p.pop('_area', 0.0),
            'face': True,
            'face_bbox': p.get('face_bbox'),
            'person_id': p.get('person_id'),
            'lip_opening': p.get('lip_opening'),
            'lip_activity': p.get('lip_activity'),
            'samples': p.get('samples'),
            '_raw': p,
        })
    clusters = _cluster_nearby_faces(proxy)
    result = []
    for c in clusters:
        raw = dict(c.get('_raw') or {})
        raw['center'] = {'x': c['x'], 'y': 0.5}
        raw['lip_opening'] = c.get('lip_opening')
        raw['lip_activity'] = c.get('lip_activity')
        raw['samples'] = c.get('samples')
        result.append(raw)
    return result


def _build_observation_intervals(bundle, clip_start, clip_end, camera_cfg):
    observations = [
        o for o in getattr(bundle, 'people_observations', [])
        if clip_start - 0.05 <= float(o.get('time', -1)) <= clip_end + 0.05 and o.get('face_visible')
    ]
    if not observations:
        return []
    window = max(0.45, float(camera_cfg.get('observation_window_seconds', 0.90)))
    # Anchor windows to the clip so the plan is stable across runs.
    duration = max(0.0, clip_end - clip_start)
    intervals = []
    n = max(1, int(math.ceil(duration / window)))
    for i in range(n):
        a = clip_start + i * window
        b = min(clip_end, a + window)
        rows = [o for o in observations if a <= float(o.get('time', -1)) < b]
        if not rows:
            continue
        positions = _summarize_observation_window(rows)
        if not positions:
            continue
        mid = (a + b) / 2
        scene = _scene_for_time(bundle, mid) or {}
        layout = str(scene.get('scene_type') or 'unknown').lower()
        # Dense observation windows are more local than the scene-level label.
        # If exactly two stable faces are visible *now*, treat this short window as
        # a two-person composition even when the whole scene was labelled 'group'.
        if len(positions) == 2:
            layout = 'two_person_scene'
        elif len(positions) >= 3:
            layout = 'group_scene'
        intervals.append({
            'start': a,
            'end': b,
            'scene_id': scene.get('scene_id'),
            'recommended_layout': layout,
            'people_positions': positions,
        })
    return intervals



def _merge_ranges(ranges):
    clean = sorted((float(a), float(b)) for a, b in ranges if b > a)
    out = []
    for a, b in clean:
        if out and a <= out[-1][1] + 0.35:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _question_ranges(bundle, clip_start, clip_end):
    """Weak conversational-turn hints, never treated as ground-truth identity.

    We use Analyzer Q/A hints plus conservative Portuguese question cues. The only
    action these ranges can trigger is choosing the *other* face when a near-future
    single-face shot strongly suggests which face is answering. Otherwise we keep
    split-screen/full-frame.
    """
    ranges = []
    for qa in getattr(bundle, 'questions_answers', []) or []:
        if not isinstance(qa, dict):
            continue
        try:
            a = float(qa.get('question_start'))
            b = float(qa.get('question_end'))
        except Exception:
            continue
        if b >= clip_start and a <= clip_end:
            ranges.append((max(clip_start, a - 1.5), min(clip_end, b + 0.35)))

    import re
    trigger = re.compile(r'\b(qual|quanto|quanta|quantos|quantas|quem|onde|por que|quando você|você acha|você acredita)\b', re.I)
    answer = re.compile(r'\b(eu|pra mim|para mim|no meu|na minha|eu acho|eu falo|eu diria)\b', re.I)
    caps = [c for c in getattr(bundle, 'captions', []) if float(c.get('end', 0)) >= clip_start and float(c.get('start', 1e9)) <= clip_end]
    caps.sort(key=lambda c: float(c.get('start', 0)))
    for i, c in enumerate(caps):
        txt = str(c.get('text') or '')
        if not trigger.search(txt):
            continue
        a = max(clip_start, float(c.get('start', clip_start)) - 2.8)
        b = min(clip_end, float(c.get('end', a)) + 6.5)
        for nxt in caps[i + 1:]:
            ns = float(nxt.get('start', 0))
            if ns > b:
                break
            nt = str(nxt.get('text') or '')
            if ns >= float(c.get('end', 0)) + 0.5 and answer.search(nt):
                b = min(b, ns)
                break
        if b > a:
            ranges.append((a, b))
    return _merge_ranges(ranges)


def _overlaps_any(a, b, ranges):
    return any(max(a, x) < min(b, y) for x, y in ranges)


def _apply_question_focus(classified, bundle, clip_start, clip_end, camera_cfg):
    """On a likely question turn, focus the non-answerer when evidence supports it.

    Example: two people are visible during a question; a few seconds later the
    source/vision collapses to a single face as the answer begins. The future single
    face is treated as the likely answerer, so the question window can safely favor
    the *other* face. This is explicitly marked as inference and only fires with
    strong geometric agreement. If that evidence is absent, we retain split-screen.
    """
    if not camera_cfg.get('question_focus_heuristic', True):
        return classified
    ranges = _question_ranges(bundle, clip_start, clip_end)
    if not ranges:
        return classified
    lookahead = float(camera_cfg.get('question_focus_lookahead_seconds', 9.0))
    match_x = float(camera_cfg.get('question_focus_match_x', 0.16))
    out = [dict(item) for item in classified]
    for i, item in enumerate(out):
        d = item['decision']
        if d.get('mode') != 'split_screen':
            continue
        a, b = item['abs_start'], item['abs_end']
        matched_range = next(((x, y) for x, y in ranges if max(a, x) < min(b, y)), None)
        if not matched_range:
            continue
        centers = [float(x) for x in (d.get('split_centers_x') or [])[:2]]
        if len(centers) != 2:
            continue
        future_center = None
        # Search after the *question turn* rather than after each tiny visual
        # window. This lets the opening words of a long question inherit the
        # same questioner focus once the answerer's subsequent shot is clear.
        search_from = matched_range[1]
        for j in range(i + 1, len(out)):
            f = out[j]
            if f['abs_end'] < search_from:
                continue
            if f['abs_start'] - search_from > lookahead:
                break
            fd = f['decision']
            if fd.get('mode') == 'crop' and 'center_x' in fd:
                future_center = float(fd['center_x'])
                break
        if future_center is None:
            continue
        dist = [abs(x - future_center) for x in centers]
        answerer_idx = 0 if dist[0] <= dist[1] else 1
        if dist[answerer_idx] > match_x:
            continue
        questioner_idx = 1 - answerer_idx
        d = dict(d)
        d.update({
            'mode': 'crop',
            'center_x': centers[questioner_idx],
            'person_id': (d.get('person_ids') or [None, None])[questioner_idx],
            'reason': 'question_turn_focus_inference',
            'speaker_evidence': True,
            'speaker_evidence_kind': 'question_answer_visual_inference',
            'protected': True,
        })
        d.pop('split_centers_x', None)
        out[i]['decision'] = d
    return out

def _duration(s):
    return max(0.0, float(s['end']) - float(s['start']))


def _compatible(a, b):
    # Never smooth through a real shot boundary: it can hide a speaker switch.
    if a.get('scene_id') and b.get('scene_id') and a.get('scene_id') != b.get('scene_id'):
        return False
    if a['mode'] != b['mode']:
        return False
    if bool(a.get('speaker_evidence')) != bool(b.get('speaker_evidence')):
        return False
    if a['mode'] == 'crop':
        return abs(float(a.get('center_x', .5)) - float(b.get('center_x', .5))) <= 0.075
    if a['mode'] == 'split_screen':
        aa = a.get('split_centers_x') or []
        bb = b.get('split_centers_x') or []
        return len(aa) >= 2 and len(bb) >= 2 and max(abs(float(aa[i]) - float(bb[i])) for i in (0, 1)) <= 0.09
    return True


def _merge_pair(a, b):
    da, db = _duration(a), _duration(b)
    total = max(1e-6, da + db)
    out = dict(a)
    out['end'] = b['end']
    if a['mode'] == 'crop':
        out['center_x'] = (float(a.get('center_x', .5)) * da + float(b.get('center_x', .5)) * db) / total
    elif a['mode'] == 'split_screen':
        aa = a.get('split_centers_x') or [.25, .75]
        bb = b.get('split_centers_x') or aa
        out['split_centers_x'] = [
            (float(aa[i]) * da + float(bb[i]) * db) / total for i in (0, 1)
        ]
    return out


def _merge_compatible(segs):
    out = []
    for s in segs:
        if out and abs(float(out[-1]['end']) - float(s['start'])) <= 0.05 and _compatible(out[-1], s):
            out[-1] = _merge_pair(out[-1], s)
        else:
            out.append(dict(s))
    return out


def _absorb_short(segs, minimum):
    segs = [dict(s) for s in segs]
    while len(segs) > 1:
        idx = next((i for i, s in enumerate(segs) if _duration(s) < minimum and not s.get('protected')), None)
        if idx is None:
            break
        cur = segs[idx]
        if idx == 0:
            segs[1]['start'] = cur['start']
            segs.pop(0)
        elif idx == len(segs) - 1:
            segs[idx - 1]['end'] = cur['end']
            segs.pop(idx)
        else:
            prev, nxt = segs[idx - 1], segs[idx + 1]
            if _compatible(prev, nxt):
                prev['end'] = nxt['end']
                segs[idx - 1] = _merge_pair(prev, nxt)
                segs.pop(idx + 1)
                segs.pop(idx)
            elif _duration(prev) >= _duration(nxt):
                prev['end'] = cur['end']
                segs.pop(idx)
            else:
                nxt['start'] = cur['start']
                segs.pop(idx)
        segs = _merge_compatible(segs)
    return segs


def _build_segments(intervals, clip_start, clip_end, min_decision, bundle=None, camera_cfg=None):
    duration = max(0.0, clip_end - clip_start)
    camera_cfg = camera_cfg or {}

    classified = []
    for t in sorted(intervals, key=lambda x: float(x.get('start', 0))):
        aa = max(clip_start, float(t.get('start', clip_start)))
        bb = min(clip_end, float(t.get('end', clip_end)))
        if bb <= aa + 1e-4:
            continue
        d = _classify_interval(t, bundle=bundle, camera_cfg=camera_cfg)
        classified.append({'abs_start': aa, 'abs_end': bb, 'interval': t, 'decision': d})

    if bundle is not None:
        classified = _apply_question_focus(classified, bundle, clip_start, clip_end, camera_cfg)

    raw = []
    cursor = 0.0
    for item in classified:
        t = item['interval']
        a = item['abs_start'] - clip_start
        b = item['abs_end'] - clip_start
        a, b = max(0.0, a), min(duration, b)
        if b <= a + 1e-4:
            continue
        if a > cursor + 0.05:
            raw.append({'start': cursor, 'end': a, 'mode': 'full_frame_blur', 'reason': 'gap_fallback'})
        a = max(a, cursor)
        if b <= a + 1e-4:
            continue
        d = dict(item['decision'])
        d.update({'start': a, 'end': b, 'scene_id': t.get('scene_id')})
        raw.append(d)
        cursor = max(cursor, b)
    if cursor < duration - 0.05:
        raw.append({'start': cursor, 'end': duration, 'mode': 'full_frame_blur', 'reason': 'tail_fallback'})
    if not raw:
        raw = [{'start': 0.0, 'end': duration, 'mode': 'full_frame_blur', 'reason': 'no_visual_evidence'}]

    raw = _merge_compatible(raw)
    raw = _absorb_short(raw, max(0.55, min_decision))
    raw = _merge_compatible(raw)

    raw[0]['start'] = 0.0
    for i in range(1, len(raw)):
        raw[i]['start'] = raw[i - 1]['end']
    raw[-1]['end'] = duration
    for seg in raw:
        seg['start'] = round(max(0.0, float(seg['start'])), 4)
        seg['end'] = round(min(duration, float(seg['end'])), 4)
        if 'center_x' in seg:
            seg['center_x'] = round(max(0.158, min(0.842, float(seg['center_x']))), 4)
        if 'split_centers_x' in seg:
            seg['split_centers_x'] = [round(max(0.0, min(1.0, float(x))), 4) for x in seg['split_centers_x'][:2]]
    return [seg for seg in raw if seg['end'] > seg['start'] + 1e-3]



def _obs_xy(obs):
    c = obs.get('head_center') or obs.get('center') or {}
    try:
        return float(c.get('x')), float(c.get('y'))
    except Exception:
        return None, None


def _obs_face_height(obs):
    b = obs.get('face_bbox') or (obs.get('bbox') if str(obs.get('bbox_kind') or '').lower() == 'face' else None) or {}
    try:
        return max(0.0, float(b.get('height', 0.0)))
    except Exception:
        return 0.0


def _cluster_obs_faces(rows, x_tol=0.075):
    """Build spatial face clusters for one small time window.

    Analyzer track IDs may fragment, therefore continuity is primarily geometric.
    """
    items=[]
    for o in rows:
        if not o.get('face_visible') or not o.get('safe_crop_possible', True):
            continue
        x,y=_obs_xy(o)
        if x is None or y is None:
            continue
        h=_obs_face_height(o)
        if h <= 0:
            continue
        items.append({
            'x':max(0.0,min(1.0,x)), 'y':max(0.0,min(1.0,y)), 'h':h,
            'person_id':o.get('person_id'),
            'confidence':float(o.get('detection_confidence') or 0.0),
            'lip_opening':o.get('lip_opening'),
        })
    if not items:
        return []
    items.sort(key=lambda z:z['x'])
    groups=[]
    for it in items:
        if not groups or abs(it['x']-statistics.median([q['x'] for q in groups[-1]]))>x_tol:
            groups.append([it])
        else:
            groups[-1].append(it)
    out=[]
    for g in groups:
        lips=[]
        for q in g:
            if q.get('lip_opening') is not None:
                try:lips.append(float(q['lip_opening']))
                except Exception:pass
        ids=[str(q.get('person_id')) for q in g if q.get('person_id')]
        out.append({
            'x':statistics.median([q['x'] for q in g]),
            'y':statistics.median([q['y'] for q in g]),
            'h':statistics.median([q['h'] for q in g]),
            'confidence':statistics.median([q['confidence'] for q in g]),
            'lip_opening':statistics.median(lips) if lips else None,
            'person_ids':set(ids),
            'samples':len(g),
        })
    return out


def _choose_motion_cluster(clusters, prev_x, target_pid, speaker_evidence):
    if not clusters:
        return None
    best=None; best_score=-1e9
    for c in clusters:
        proximity=max(0.0,1.0-min(1.0,abs(float(c['x'])-float(prev_x))/0.30))
        score=4.0*proximity + 0.35*min(1.0,float(c.get('confidence') or 0.0))
        if target_pid and str(target_pid) in c.get('person_ids',set()):
            score += 5.0
        # Mouth opening is a weak cue only after the interval was already selected
        # as speaker-focused. It must never pull the camera across the table alone.
        if speaker_evidence and c.get('lip_opening') is not None:
            score += min(1.2,max(0.0,float(c['lip_opening']))*2.2)
        # Prefer a well-observed face over one-frame noise.
        score += min(0.6,0.12*int(c.get('samples') or 0))
        if score>best_score:
            best_score=score; best=c
    return best


def _smooth_motion_points(points, camera_cfg):
    if not points:
        return []
    alpha=float(camera_cfg.get('motion_ema_alpha',0.42))
    alpha=max(0.05,min(0.95,alpha))
    dead_x=float(camera_cfg.get('motion_deadzone_x',0.012))
    dead_y=float(camera_cfg.get('motion_deadzone_y',0.015))
    max_vx=float(camera_cfg.get('max_pan_speed_per_second',0.18))
    max_vy=float(camera_cfg.get('max_tilt_speed_per_second',0.12))
    out=[dict(points[0])]
    for p in points[1:]:
        prev=out[-1]; dt=max(1e-3,float(p['time'])-float(prev['time']))
        tx=alpha*float(p['x'])+(1-alpha)*float(prev['x'])
        ty=alpha*float(p['y'])+(1-alpha)*float(prev['y'])
        if abs(tx-float(prev['x']))<dead_x: tx=float(prev['x'])
        if abs(ty-float(prev['y']))<dead_y: ty=float(prev['y'])
        dx=max(-max_vx*dt,min(max_vx*dt,tx-float(prev['x'])))
        dy=max(-max_vy*dt,min(max_vy*dt,ty-float(prev['y'])))
        q=dict(p); q['x']=max(0.0,min(1.0,float(prev['x'])+dx)); q['y']=max(0.0,min(1.0,float(prev['y'])+dy))
        q['motion_speed']=((dx*dx+dy*dy)**0.5)/dt
        out.append(q)
    return out


def _zoom_for_point(point, speaker_evidence, camera_cfg, prev_zoom=None):
    if not camera_cfg.get('smart_zoom',True):
        return 1.0
    zmin=float(camera_cfg.get('min_zoom',1.00))
    zmax=float(camera_cfg.get('max_zoom',1.13))
    small=float(camera_cfg.get('zoom_face_height_small',0.10))
    large=float(camera_cfg.get('zoom_face_height_large',0.30))
    h=max(0.0,float(point.get('h') or 0.0))
    if h<=0:
        target=zmin
    elif large<=small:
        target=zmin
    else:
        ratio=max(0.0,min(1.0,(large-h)/(large-small)))
        target=zmin+ratio*(zmax-zmin)
    if speaker_evidence:
        target += float(camera_cfg.get('zoom_speaker_bonus',0.012))
    lip=point.get('lip_opening')
    if speaker_evidence and lip is not None:
        try:
            if float(lip)>=float(camera_cfg.get('zoom_lip_threshold',0.20)):
                target += float(camera_cfg.get('zoom_lip_bonus',0.008))
        except Exception:
            pass
    speed=float(point.get('motion_speed') or 0.0)
    fast=float(camera_cfg.get('zoom_motion_speed_threshold',0.10))
    if speed>fast:
        target -= float(camera_cfg.get('zoom_motion_widening',0.025))*min(1.0,(speed-fast)/max(0.02,fast))
    target=max(zmin,min(zmax,target))
    if prev_zoom is not None:
        step=float(camera_cfg.get('zoom_max_step',0.012))
        target=max(float(prev_zoom)-step,min(float(prev_zoom)+step,target))
    return max(zmin,min(zmax,target))


def _simplify_motion_points(points, camera_cfg):
    if len(points)<=2:
        return points
    tol_x=float(camera_cfg.get('motion_simplify_x',0.010))
    tol_y=float(camera_cfg.get('motion_simplify_y',0.012))
    tol_z=float(camera_cfg.get('motion_simplify_zoom',0.007))
    out=[points[0]]
    for i in range(1,len(points)-1):
        a=out[-1]; b=points[i]; c=points[i+1]
        span=max(1e-6,float(c['time'])-float(a['time']))
        r=max(0.0,min(1.0,(float(b['time'])-float(a['time']))/span))
        px=float(a['x'])+(float(c['x'])-float(a['x']))*r
        py=float(a['y'])+(float(c['y'])-float(a['y']))*r
        pz=float(a['zoom'])+(float(c['zoom'])-float(a['zoom']))*r
        if abs(float(b['x'])-px)<=tol_x and abs(float(b['y'])-py)<=tol_y and abs(float(b['zoom'])-pz)<=tol_z:
            continue
        out.append(b)
    out.append(points[-1])
    return out


def _motion_points_for_segment(bundle, seg, clip_start, camera_cfg):
    if seg.get('mode')!='crop':
        return []
    abs_start=clip_start+float(seg['start']); abs_end=clip_start+float(seg['end'])
    if abs_end-abs_start<0.35:
        return []
    obs=[o for o in getattr(bundle,'people_observations',[]) if abs_start-0.10<=float(o.get('time',-1))<=abs_end+0.10 and o.get('face_visible')]
    if not obs:
        return []
    step=max(0.45,float(camera_cfg.get('motion_keyframe_seconds',0.90)))
    radius=max(0.18,min(0.55,step*0.55))
    times=[abs_start]
    t=abs_start+step
    while t<abs_end-0.15:
        times.append(t); t+=step
    if abs_end-times[-1]>0.10: times.append(abs_end)
    target_pid=seg.get('person_id'); prev_x=float(seg.get('center_x',0.5))
    speaker=bool(seg.get('speaker_evidence'))
    points=[]
    for t in times:
        rows=[o for o in obs if abs(float(o.get('time',-1))-t)<=radius]
        clusters=_cluster_obs_faces(rows)
        chosen=_choose_motion_cluster(clusters,prev_x,target_pid,speaker)
        if chosen is None:
            continue
        prev_x=float(chosen['x'])
        points.append({
            'time':t-clip_start,'x':float(chosen['x']),'y':float(chosen['y']),'h':float(chosen['h']),
            'lip_opening':chosen.get('lip_opening'),'person_ids':sorted(chosen.get('person_ids') or []),
            'samples':int(chosen.get('samples') or 0),'motion_speed':0.0,
        })
    if not points:
        return []
    # Ensure exact segment boundaries. Do not extrapolate beyond the selected subject.
    if points[0]['time']>float(seg['start'])+0.05:
        q=dict(points[0]); q['time']=float(seg['start']); points.insert(0,q)
    else:
        points[0]['time']=float(seg['start'])
    if points[-1]['time']<float(seg['end'])-0.05:
        q=dict(points[-1]); q['time']=float(seg['end']); points.append(q)
    else:
        points[-1]['time']=float(seg['end'])
    points=_smooth_motion_points(points,camera_cfg)
    prev_z=None
    for p in points:
        p['zoom']=_zoom_for_point(p,speaker,camera_cfg,prev_z); prev_z=p['zoom']
    return _simplify_motion_points(points,camera_cfg)


def _expand_motion_segments(bundle, segments, clip_start, camera_cfg):
    if not camera_cfg.get('motion_follow',True):
        return segments
    out=[]
    for seg in segments:
        if seg.get('mode')!='crop':
            out.append(dict(seg)); continue
        pts=_motion_points_for_segment(bundle,seg,clip_start,camera_cfg)
        if len(pts)<2:
            s=dict(seg); s['zoom']=round(float(camera_cfg.get('min_zoom',1.0)),4); out.append(s); continue
        for a,b in zip(pts,pts[1:]):
            if float(b['time'])<=float(a['time'])+1e-3:
                continue
            s=dict(seg)
            s.update({
                'start':round(float(a['time']),4),'end':round(float(b['time']),4),
                'center_x_start':round(float(a['x']),5),'center_x_end':round(float(b['x']),5),
                'center_y_start':round(float(a['y']),5),'center_y_end':round(float(b['y']),5),
                'center_x':round((float(a['x'])+float(b['x']))/2,5),
                'zoom':round((float(a['zoom'])+float(b['zoom']))/2,4),
                'motion_follow':True,
                'reason':str(seg.get('reason') or 'crop')+'+smart_motion',
            })
            out.append(s)
    # Preserve exact contiguous boundaries after expansion.
    if out:
        out[0]['start']=0.0
        for i in range(1,len(out)):
            out[i]['start']=out[i-1]['end']
    return [s for s in out if float(s.get('end',0))>float(s.get('start',0))+1e-3]

def build_camera_plan(bundle, clip, cfg=None):
    start, end = float(clip['source_start']), float(clip['source_end'])
    camera_cfg = (cfg or {}).get('camera', {}) if isinstance(cfg, dict) else {}
    min_decision = float(camera_cfg.get('min_decision_seconds', 0.85))

    observation_intervals = _build_observation_intervals(bundle, start, end, camera_cfg)
    timeline_intervals = [t for t in bundle.timeline if t.get('end', 0) >= start and t.get('start', 1e9) <= end]

    # Prefer dense face observations when they cover a meaningful part of the clip.
    obs_coverage = sum(max(0.0, float(x['end']) - float(x['start'])) for x in observation_intervals)
    duration = max(1e-6, end - start)
    use_observations = bool(observation_intervals) and obs_coverage / duration >= float(camera_cfg.get('observation_min_coverage', 0.45))
    source_intervals = observation_intervals if use_observations else timeline_intervals

    segments = _build_segments(
        source_intervals, start, end, min_decision,
        bundle=bundle, camera_cfg=camera_cfg,
    )
    segments = _expand_motion_segments(bundle, segments, start, camera_cfg)

    modes = {}
    for s in segments:
        modes[s['mode']] = modes.get(s['mode'], 0.0) + _duration(s)
    dominant = max(modes, key=modes.get) if modes else 'full_frame_blur'
    centers = [float(s['center_x']) for s in segments if s['mode'] == 'crop' and 'center_x' in s]
    center = statistics.median(centers) if centers else 0.5
    speaker_segments = [s for s in segments if s.get('speaker_evidence')]
    uncertain_two_face = [s for s in segments if s.get('reason') == 'two_faces_speaker_uncertain']

    return {
        'mode': 'adaptive_timeline',
        'segments': segments,
        'normalized_center_x': round(max(0.158, min(0.842, center)), 4),
        'dynamic_active_speaker': bool(speaker_segments),
        'speaker_aware': True,
        'motion_follow': bool(camera_cfg.get('motion_follow', True)),
        'smart_zoom': bool(camera_cfg.get('smart_zoom', True)),
        'motion_segments': sum(1 for s in segments if s.get('motion_follow')),
        'speaker_evidence_segments': len(speaker_segments),
        'uncertain_two_face_segments': len(uncertain_two_face),
        'visual_source': 'people_observations' if use_observations else 'timeline',
        'dominant_mode': dominant,
        'reason': (
            'Câmera v3: speaker/person explícito -> crop; atividade labial confiável -> crop; '
            'uma face -> crop; duas faces sem locutor resolvido -> split-screen; grupo/ambiguidade -> '
            'quadro completo com fundo desfocado. Usa observações densas de rosto quando disponíveis e '
            'não suaviza através de cortes reais de cena; crop ativo acompanha o rosto com pan/tilt suave e zoom inteligente conservador.'
        ),
        'source_timeline_intervals': len(timeline_intervals),
        'source_observation_intervals': len(observation_intervals),
        'needs_review': False,
    }
