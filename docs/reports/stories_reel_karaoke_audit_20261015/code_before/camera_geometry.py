"""Conservative crop geometry. Safe is geometric, never a claim about model accuracy."""
from .camera_motion import clamp
from .temporal import number


def base_size(metadata, cfg):
    width, height = number(metadata.get('width')), number(metadata.get('height'))
    if width <= 0 or height <= 0:
        return None
    if abs(number(metadata.get('rotation'))) % 180:
        width, height = height, width
    ratio = (cfg['output_width']/cfg['output_height'])/(width/height)
    return min(1., ratio), min(1., 1./ratio), width, height


def subject_box(obs, cfg):
    face = obs.get('face_bbox') or {}
    if not face or not obs.get('face_visible') or obs.get('safe_crop_possible') is not True:
        return None
    x, y, w, h = (number(face.get(k), -1.) for k in ('x', 'y', 'width', 'height'))
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1.000001 or y+h > 1.000001:
        return None
    if h < cfg['min_face_height'] or y < .005:
        return None
    # Full head with breathing room; upper torso only when an actual body box exists.
    bottom = y+h+min(.08, h*.25)
    body = obs.get('bbox') if obs.get('body_visible') and obs.get('bbox_kind') == 'body' else None
    if body:
        bottom = max(bottom, min(1., number(body.get('y'))+number(body.get('height'))*.65))
    return [max(0., x-.015), max(0., y-cfg['headroom']),
            min(1., x+w+.015), min(1., bottom)]


def crop_rect(center, zoom, base):
    w, h = base[0]/zoom, base[1]/zoom
    return {'x': clamp(center[0]-w/2, 0., 1.-w),
            'y': clamp(center[1]-h/2, 0., 1.-h), 'width': w, 'height': h}


def contains(rect, box):
    return bool(rect and box and rect['x'] <= box[0]+1e-8 and rect['y'] <= box[1]+1e-8
                and rect['x']+rect['width'] >= box[2]-1e-8
                and rect['y']+rect['height'] >= box[3]-1e-8)


def geometry(observations, metadata, cfg, requested_zoom=1., motion=None):
    base = base_size(metadata, cfg)
    boxes = [subject_box(o, cfg) for o in observations]
    if not base or not boxes or any(b is None for b in boxes):
        return {'safe': False, 'reason': 'missing_or_unsafe_subject_geometry', 'max_zoom': 1.}
    if any(o.get('sharpness') is not None and number(o['sharpness']) < cfg['min_sharpness'] for o in observations):
        return {'safe': False, 'reason': 'low_face_sharpness', 'max_zoom': 1.}
    union = [min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes)]
    # Missing quality data is allowed only at baseline zoom, marked for review.
    known_quality = all(o.get('sharpness') is not None for o in observations)
    resolution = min(base[0]*base[2]/cfg['output_width'], base[1]*base[3]/cfg['output_height'])
    crop_max = min(base[0]/max(union[2]-union[0], 1e-9), base[1]/max(union[3]-union[1], 1e-9))
    upscale_limit = cfg.get('smart_zoom', {}).get('max_upscale_ratio', 2.)
    quality_cap = resolution * upscale_limit
    cap = min(cfg['max_zoom_default'], cfg['max_zoom_hard'], quality_cap, crop_max)
    if not known_quality:
        cap = min(cap, 1.)
    if cap < 1.:
        return {'safe': False, 'reason': 'upscale_limit' if quality_cap < 1 else 'subjects_do_not_fit_vertical_crop', 'max_zoom': 1.,
            'upscale_ratio': 1 / max(resolution, 1e-9), 'limited_by_quality': quality_cap < 1}
    zoom = min(requested_zoom, cap)
    x, y = (union[0]+union[2])/2, (union[1]+union[3])/2
    if motion and number(motion.get('movement_intensity')) > .08:
        x += clamp(number(motion.get('velocity_x'))*.4, -cfg['lead_room'], cfg['lead_room'])
    rect = crop_rect([x, y], zoom, base)
    if not contains(rect, union):
        rect = crop_rect([(union[0]+union[2])/2, (union[1]+union[3])/2], zoom, base)
    return {'safe': contains(rect, union), 'reason': 'measured_geometry',
            'center': [rect['x']+rect['width']/2, rect['y']+rect['height']/2],
            'rect': rect, 'subject_bounds': union, 'zoom': zoom, 'max_zoom': cap,
            'quality_limited_max_zoom': min(cfg['max_zoom_default'], quality_cap) if known_quality else 1.,
            'requested_zoom': requested_zoom, 'actual_zoom': zoom,
            'upscale_ratio': zoom / max(resolution, 1e-9), 'max_upscale_ratio': upscale_limit,
            'limited_by_quality': requested_zoom > quality_cap,
            'crop_safe_max_zoom': crop_max, 'baseline_requires_upscale': resolution < 1.,
            'quality_unknown': not known_quality, 'base': base[:2]}
