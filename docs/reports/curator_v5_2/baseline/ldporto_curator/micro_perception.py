"""Clip-local perception at 5–10 fps. Local tracks never imply acoustic identity."""
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np
from .utils import load_json, write_json, file_fingerprint
from .approval import file_hash
from .broadcast_graphics import detect_graphics


def _iou(a, b):
    intersection = max(0., min(a['x'] + a['width'], b['x'] + b['width']) - max(a['x'], b['x'])) * max(0., min(a['y'] + a['height'], b['y'] + b['height']) - max(a['y'], b['y']))
    return intersection / max(a['width'] * a['height'] + b['width'] * b['height'] - intersection, 1e-9)


def _detector(model):
    if not model.is_file():
        return None
    engine = cv2.FaceDetectorYN.create(str(model), '', (320, 320), .85, .3, 1000)
    def detect(frame):
        height, width = frame.shape[:2]
        engine.setInputSize((width, height))
        _, faces = engine.detect(frame)
        rows = []
        for face in faces if faces is not None else []:
            x, y, w, h = map(float, face[:4])
            if x < 0 or y < 0 or x + w > width or y + h > height:
                continue
            rows.append({'face_bbox': {'x': x / width, 'y': y / height, 'width': w / width, 'height': h / height},
                         'detection_confidence': float(face[-1])})
        return rows
    return detect


def open_clip_source(video, start, end):
    if not math.isfinite(start + end) or not 0 <= start < end:
        raise ValueError('Invalid clip source bounds')
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        cap.release()
        raise ValueError('Clip source is not decodable')
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if source_fps <= 0 or end > cap.get(cv2.CAP_PROP_FRAME_COUNT) / source_fps + .1:
        cap.release()
        raise ValueError('Clip outside actual source duration')
    return cap, source_fps


def inspect_clip(video, clip, cache_dir, cfg=None, detector=None, progress=None):
    cfg = cfg or {}
    fps = float(cfg.get('sample_fps', 6))
    start, end = float(clip['source_start']), float(clip['source_end'])
    if not 5 <= fps <= 10 or not math.isfinite(start + end) or not 0 <= start < end or end - start > cfg.get('max_clip_seconds', 240):
        raise ValueError('Microperception requires a bounded clip and 5–10 fps')
    model = Path(cfg.get('face_model') or Path(__file__).resolve().parents[2] / 'LDPORTO_VIDEO_ANALYZER/models/face_detection_yunet_2023mar.onnx')
    model_hash = file_hash(model) if model.is_file() and detector is None else 'injected' if detector else 'unavailable'
    signature = {'source': file_fingerprint(Path(video)), 'start': start, 'end': end, 'config': cfg,
                 'model': model_hash, 'code': file_hash(__file__),
                 'graphics_code': file_hash(Path(__file__).with_name('broadcast_graphics.py')), 'opencv': cv2.__version__}
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    path = Path(cache_dir) / (key + '.json')
    saved = load_json(path, {}) or {}
    if saved.get('key') == key and saved.get('checksum') == hashlib.sha256(json.dumps(saved['data'], sort_keys=True).encode()).hexdigest():
        return {**saved['data'], 'cache_hit': True}
    detect = detector or _detector(model)
    cap, source_fps = open_clip_source(video, start, end)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    observations, frames, shots, graphics = [], [], [], []
    current_tracks, track_count = {}, 0
    shot_id, shot_start, previous, previous_sample = 'MICRO_SHOT_0000', start, None, start
    graphic_samples, graphic_start = [], start
    next_sample, index, last_time = start, int(round(start * source_fps)), start
    def flush_graphics(until):
        if len(graphic_samples) >= 4:
            result = detect_graphics(graphic_samples, fps=len(graphic_samples) / max(until - graphic_start, .1))
            if result['regions']:
                graphics.append({'start': graphic_start, 'end': until, **result})
    try:
        while index / source_fps < end:
            got, frame = cap.read()
            if not got:
                break
            t = index / source_fps
            pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if start <= pts < end and pts >= last_time:
                t = pts
            index += 1
            if t + 1e-6 < next_sample:
                continue
            while next_sample <= t + 1e-6:
                next_sample += 1 / fps
            last_time = t
            small = cv2.resize(frame, (160, 90))
            difference = float(np.mean(cv2.absdiff(small, previous)) / 255) if previous is not None else 0.
            if difference > cfg.get('cut_threshold', .18) and t - shot_start >= .6:
                shots.append({'shot_id': shot_id, 'start': shot_start, 'end': t, 'cut_difference': difference})
                flush_graphics(t)
                shot_id = f'MICRO_SHOT_{len(shots):04}'
                shot_start, graphic_start, graphic_samples, current_tracks = t, t, [], {}
            previous = small
            graphic_samples.append(cv2.resize(frame, (320, 180)))
            if len(graphic_samples) >= 32:
                flush_graphics(min(end, t + 1 / fps))
                graphic_samples, graphic_start = [], min(end, t + 1 / fps)
            scale = min(1., float(cfg.get('max_width', 960)) / frame.shape[1])
            image = cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale))) if scale < 1 else frame
            detections = detect(image) if detect else []
            tracks, used = {}, set()
            for detection in sorted(detections, key=lambda r: r.get('detection_confidence', 0), reverse=True):
                face = detection['face_bbox']
                matches = [( _iou(face, prior['face_bbox']), tid) for tid, prior in current_tracks.items()
                           if tid not in used and t - prior['time'] <= .6]
                similarity, tid = max(matches, default=(0., None))
                if similarity < .35:
                    track_count += 1
                    tid = f'MICRO_TRACK_{track_count:05}'
                used.add(tid)
                x, y = face['x'] + face['width'] / 2, face['y'] + face['height'] / 2
                ih, iw = image.shape[:2]
                face_image = image[max(0, int(face['y'] * ih)):min(ih, int((face['y'] + face['height']) * ih)),
                                   max(0, int(face['x'] * iw)):min(iw, int((face['x'] + face['width']) * iw))]
                sharpness = float(cv2.Laplacian(cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if face_image.size else 0.
                row = {**detection, 'time': t, 'track_id': tid, 'person_id': 'LOCAL_' + tid, 'shot_id': shot_id,
                       'face_visible': True, 'safe_crop_possible': True, 'body_visible': False, 'bbox_kind': 'face',
                       'center': {'x': x, 'y': y}, 'head_center': {'x': x, 'y': y}, 'sharpness': sharpness,
                       'speaker_identity_confirmed': False, 'person_detection_kind': 'FACE_ONLY_PERSON'}
                observations.append(row)
                tracks[tid] = row
            current_tracks = tracks
            frames.append({'time': t, 'shot_id': shot_id, 'face_count': len(detections), 'source_motion_proxy': difference})
            if progress:
                progress((t - start) / (end - start), f'{len(frames)} amostras do corte')
        flush_graphics(end)
        shots.append({'shot_id': shot_id, 'start': shot_start, 'end': end})
    finally:
        cap.release()
    result = {'schema_version': '4.4.0', 'status': 'measured' if detect else 'face_model_unavailable',
              'observations': observations, 'frames': frames, 'shots': shots,
              'broadcast_graphics': {'intervals': graphics, 'status': 'measured'}, 'cache_hit': False,
              'sampled_start': frames[0]['time'] if frames else None, 'sampled_end': frames[-1]['time'] if frames else None,
              'sample_count': len(frames), 'sample_fps': fps, 'raw_tracklets': track_count,
              'speaker_identity_method': 'not_inferred_from_local_faces', 'face_model_fingerprint': model_hash}
    write_json(path, {'key': key, 'checksum': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(), 'data': result})
    return result
