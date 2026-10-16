"""Small indexes shared by perception and editorial stages. No media decoding."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
import math


def number(value, default=0.):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else default


class IntervalCursor:
    """Monotonic interval sweep, including overlapping voices (amortized O(N + hits))."""
    def __init__(self, rows):
        self.rows = sorted((r for r in rows if isinstance(r.get('start'), (float, int))
                            and isinstance(r.get('end'), (float, int)) and r['end'] > r['start']),
                           key=lambda r: r['start'])
        self.index = 0
        self.live = []
        self.last = -math.inf

    def at(self, t):
        if t < self.last:
            self.index, self.live = 0, []
        self.last = t
        self.live = [r for r in self.live if r['end'] > t]
        while self.index < len(self.rows) and self.rows[self.index]['start'] <= t:
            r = self.rows[self.index]
            if r['end'] > t:
                self.live.append(r)
            self.index += 1
        return self.live


class VisualIndex:
    def __init__(self, vision):
        self.frames = sorted(vision.get('frames', []), key=lambda r: r['time'])
        self.times = [r['time'] for r in self.frames]
        self.observations = defaultdict(dict)
        for row in vision.get('observations', []):
            if row.get('person_id'):
                self.observations[row['time']][row['person_id']] = row

    def near(self, t, start, end, max_gap):
        i = bisect_left(self.times, t)
        candidates = [self.frames[j] for j in (i-1, i) if 0 <= j < len(self.frames)
                      and start <= self.times[j] < end and abs(self.times[j]-t) <= max_gap]
        if not candidates:
            return None, {}
        frame = min(candidates, key=lambda r: abs(r['time']-t))
        visible = set(frame.get('visible_people', []))
        return frame, {p: o for p, o in self.observations[frame['time']].items() if p in visible}


class SampleIndex:
    def __init__(self, people):
        self.rows = {p['person_id']: sorted(p.get('samples', []), key=lambda r: r['time']) for p in people}
        self.times = {p: [r['time'] for r in rows] for p, rows in self.rows.items()}

    def near(self, person, t, start, end, max_gap=.6):
        times = self.times.get(person, [])
        i = bisect_left(times, t)
        choices = [self.rows[person][j] for j in (i-1, i) if 0 <= j < len(times)
                   and start <= times[j] < end and abs(times[j]-t) <= max_gap]
        return min(choices, key=lambda r: abs(r['time']-t), default=None)


def union_duration(rows):
    end, total = -math.inf, 0.
    for r in sorted(rows, key=lambda r: r['start']):
        total += max(0., r['end']-max(end, r['start']))
        end = max(end, r['end'])
    return total
