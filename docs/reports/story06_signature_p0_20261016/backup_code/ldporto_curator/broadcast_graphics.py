"""Persistent fixed-coordinate graphic candidates; OCR remains optional."""
import cv2
import numpy as np


def detect_graphics(frames, fps=2., visual_text=None):
    if len(frames) < 4:
        return {'schema_version': '1.0', 'regions': [], 'status': 'insufficient_temporal_samples'}
    samples = np.stack([cv2.resize(frame, (320, 180)) for frame in frames])
    gray = np.stack([cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in samples])
    edges = np.stack([cv2.Canny(frame, 60, 140) > 0 for frame in gray])
    persistence = np.mean(edges, axis=0) >= .75
    regions = []
    # Horizontal broadcast strips: wide persistent edges AND spatial text density.
    for kind, first, last in [('lower_third', .60, .96), ('banner', 0., .22)]:
        a, b = int(first * 180), int(last * 180)
        density = persistence[a:b].mean(axis=1)
        occupied = np.flatnonzero(density >= .04)
        if len(occupied) < 3:
            continue
        y0, y1 = max(a, a + int(occupied[0]) - 4), min(b, a + int(occupied[-1]) + 5)
        band = persistence[y0:y1]
        edge_density = float(band.mean())
        horizontal = float(np.mean([part.mean() > .02 for part in np.array_split(band, 4, axis=1)]))
        temporal_change = float(np.mean(np.std(gray[:, y0:y1].astype(float), axis=0)) / 255)
        if edge_density < .025 or horizontal < .5 or temporal_change > .08:
            continue
        regions.append({'kind': kind, 'x_start': 0., 'x_end': 1., 'y_start': y0 / 180, 'y_end': y1 / 180,
                        'persistent': True, 'confidence': .75, 'needs_review': True,
                        'evidence': {'edge_density': edge_density, 'horizontal_coverage': horizontal,
                                     'fixed_coordinate_persistence': .75, 'color_stability_proxy': 1 - temporal_change,
                                     'sample_count': len(frames), 'observed_seconds': len(frames) / fps},
                        'ocr_text': visual_text or [], 'measurement': 'graphic_candidate_not_text_recognition'})
    return {'schema_version': '1.0', 'regions': regions, 'status': 'measured', 'ocr_required': False}


def face_safe_height(graphics, default=1.):
    regions = (graphics or {}).get('regions', [])
    return min([float(row['y_start']) for row in regions
                if row.get('persistent') and row.get('kind') in {'lower_third', 'ticker', 'banner'}
                and row.get('y_start', 0) > .4] or [default])


def inspect_candidate_graphics(video, candidates, limit=16):
    """Eight seeks per selected candidate; never decode a full programme for graphics."""
    cap = cv2.VideoCapture(str(video))
    intervals, sampled = [], 0
    try:
        if not cap.isOpened():
            return {'schema_version': '1.0', 'status': 'unavailable', 'intervals': [], 'sampled_frames': 0}
        for row in sorted(candidates, key=lambda r: float(r.get('editorial_score') or 0), reverse=True)[:limit]:
            core = row.get('core_moment') or row
            start, end = float(row.get('ideal_start', core['start'])), float(row.get('ideal_end', core['end']))
            if end <= start:
                continue
            frames = []
            for t in np.linspace(start, end, 8, endpoint=False):
                cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
                ok, frame = cap.read()
                if ok:
                    frames.append(frame)
            sampled += len(frames)
            result = detect_graphics(frames, fps=len(frames) / (end - start))
            intervals.append({'start': start, 'end': end, 'moment_id': row.get('moment_id'), **result})
    finally:
        cap.release()
    return {'schema_version': '1.0', 'status': 'measured', 'intervals': intervals,
            'sampled_frames': sampled, 'scope': 'selected_candidate_windows', 'ocr_required': False}


class GraphicsAccumulator:
    """Bounded memory: eight downsampled frames, with temporal intervals retained."""
    def __init__(self):
        self.frames, self.times, self.intervals = [], [], []
        self.last = -1.

    def add(self, time, frame):
        if time - self.last < 1.:
            return
        self.last = time
        self.frames.append(cv2.resize(frame, (320, 180)))
        self.times.append(time)
        if len(self.frames) >= 8:
            self.flush()

    def flush(self):
        if len(self.frames) >= 4:
            result = detect_graphics(self.frames, fps=1.)
            if result['regions']:
                self.intervals.append({'start': self.times[0], 'end': self.times[-1] + 1., **result})
        self.frames, self.times = [], []

    def result(self):
        self.flush()
        return {'schema_version': '1.0', 'intervals': self.intervals,
                'regions': [], 'status': 'measured_temporal_intervals', 'ocr_required': False}
