"""Jerk/acceleration/speed limited camera recommendations in source coordinates."""
from dataclasses import dataclass
from collections import deque
import math


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def ease_in_out(fraction):
    fraction = clamp(fraction, 0., 1.)
    return fraction * fraction * (3. - 2. * fraction)


class SmartZoomState:
    def __init__(self):
        self.current_camera_mode = 'SOURCE_PRESERVE'
        self.current_target = None
        self.current_zoom = self.target_zoom = 1.
        self.state_entered_at = self.last_switch_at = 0.
        self.last_zoom_event_at = -math.inf
        self.events = []
        self.event_times = deque()
        self.used_beats = set()
        self.transition = None
        self.hold_until = 0.

    def reset_shot(self, time):
        self.current_target = None
        self.current_zoom = self.target_zoom = 1.
        self.transition = None
        self.hold_until = time
        self.state_entered_at = time

    def curve(self, time):
        if not self.transition:
            return self.target_zoom
        start, duration, before, after = self.transition
        if time >= start + duration:
            self.transition = None
            return after
        return before + (after - before) * ease_in_out((time - start) / duration)

    def decide(self, time, *, target, confidence, safe, zoom_cap, face_size,
               source_close, source_motion, speech_seconds, remaining_seconds,
               beat, micro_interruption, cfg, max_speed=.035):
        reasons = []
        while self.event_times and self.event_times[0] <= time - 60:
            self.event_times.popleft()
        if not target or not safe:
            reasons.append('CROP_UNSAFE' if target else 'INSUFFICIENT_CONFIDENCE')
            if self.current_target and self.current_zoom > 1.001:
                reasons.append('TARGET_LOST_DURING_ZOOM')
            self.current_target, self.target_zoom, self.transition = None, 1., None
            self.current_camera_mode = 'SOURCE_PRESERVE'
            return {'zoom': 1., 'requested_zoom': 1., 'mode': self.current_camera_mode,
                    'reason_codes': reasons, 'digital_motion_allowed': False}
        if target != self.current_target:
            self.current_target = target
            self.current_zoom = self.target_zoom = 1.
            self.transition = None
            self.state_entered_at = self.last_switch_at = time
            self.hold_until = time
        if not cfg['enabled']:
            reasons.append('SMART_ZOOM_DISABLED')
        if source_close or face_size >= cfg['max_face_size']:
            reasons.append('SOURCE_ALREADY_CLOSE')
        if face_size < cfg['min_face_size']:
            reasons.append('FACE_TOO_SMALL')
        if source_motion > cfg['max_source_motion']:
            reasons.append('SOURCE_CAMERA_MOVING')
        if confidence < cfg['min_confidence'] and not micro_interruption:
            reasons.append('INSUFFICIENT_CONFIDENCE')
        blocked = bool(reasons)
        if micro_interruption:
            reasons.append('MICRO_INTERRUPTION_SUPPRESSED')
        goal = min(cfg['max_zoom_factor'], max(1., zoom_cap))
        beat_key = (beat or {}).get('id'), target
        request = self.target_zoom
        if beat and not blocked and not micro_interruption and beat_key not in self.used_beats and speech_seconds >= cfg['min_speaker_persistence']:
            if len(self.event_times) >= cfg['max_zoom_events_per_minute']:
                reasons.append('ZOOM_RATE_LIMIT')
            elif time < self.hold_until:
                reasons.append('MINIMUM_ZOOM_DWELL')
            else:
                request = cfg['max_zoom_factor']
                if goal < request:
                    reasons.append('UPSCALE_OR_CROP_LIMIT')
                duration = max(cfg['min_zoom_duration'], cfg['transition_duration'], 1.6 * abs(goal - self.current_zoom) / max_speed)
                if remaining_seconds < duration:
                    reasons.append('INSUFFICIENT_ZOOM_DURATION')
                elif goal - self.current_zoom > .035:
                    self.transition = (time, duration, self.current_zoom, goal)
                    self.target_zoom = goal
                    self.hold_until = time + duration + cfg['min_hold_duration']
                    self.last_zoom_event_at = time
                    self.event_times.append(time)
                    self.used_beats.add(beat_key)
                    self.events.append({'start': time, 'end': time + duration, 'zoom_start': self.current_zoom,
                        'zoom_end': goal, 'mode': 'SMART_ZOOM_IN', 'target_person_id': target,
                        'reason_codes': [(beat or {})['reason'], 'ACTIVE_SPEAKER_FOCUS'], 'beat_id': beat_key[0]})
                    reasons.append((beat or {})['reason'])
        if blocked:
            self.target_zoom, self.transition = 1., None
        elif not beat and not micro_interruption and self.target_zoom > 1.035 and time >= self.hold_until and len(self.event_times) < cfg['max_zoom_events_per_minute']:
            duration = max(cfg['min_zoom_duration'], cfg['transition_duration'], 1.6 * abs(self.current_zoom - 1.) / max_speed)
            if remaining_seconds >= duration:
                self.transition = (time, duration, self.current_zoom, 1.)
                self.target_zoom = 1.
                self.event_times.append(time)
                self.hold_until = time + duration + cfg['min_hold_duration']
                self.events.append({'start': time, 'end': time + duration, 'zoom_start': self.current_zoom,
                    'zoom_end': 1., 'mode': 'SMART_ZOOM_OUT', 'target_person_id': target,
                    'reason_codes': ['EDITORIAL_EMPHASIS_COMPLETE']})
                reasons.append('EDITORIAL_EMPHASIS_COMPLETE')
        zoom = self.curve(time)
        mode = ('SMART_ZOOM_IN' if self.transition and self.transition[3] > self.transition[2] else
                'SMART_ZOOM_OUT' if self.transition else 'STATIC_CLOSE' if self.current_zoom * face_size >= cfg['close_face_min'] else 'STATIC_MEDIUM')
        self.current_camera_mode = mode
        return {'zoom': zoom, 'requested_zoom': request, 'mode': mode,
                'reason_codes': reasons or ['STABLE_EDITORIAL_FRAMING'], 'digital_motion_allowed': not blocked,
                'limited_by_quality': goal + 1e-6 < request}


@dataclass
class Axis:
    position: float
    velocity: float = 0.
    acceleration: float = 0.

    def advance(self, target, seconds, speed, acceleration, jerk):
        # Fixed small integration steps make behavior independent of input frame rate.
        remaining = seconds
        while remaining > 1e-9:
            dt = min(.025, remaining)
            error = target-self.position
            desired_v = clamp(error*.65, -speed, speed)
            desired_a = clamp((desired_v-self.velocity)*4., -acceleration, acceleration)
            self.acceleration += clamp(desired_a-self.acceleration, -jerk*dt, jerk*dt)
            self.velocity = clamp(self.velocity+self.acceleration*dt, -speed, speed)
            self.position += self.velocity*dt
            remaining -= dt
        return self.position


class CameraMotion:
    def __init__(self, x=.5, y=.5, zoom=1.):
        self.x, self.y, self.zoom = Axis(x), Axis(y), Axis(zoom)
        self.target = [x, y, zoom]
        self.outside_since = None

    def move(self, target, t, dt, cfg):
        dx, dy = abs(target[0]-self.target[0]), abs(target[1]-self.target[1])
        outside = dx > cfg['horizontal_deadzone'] or dy > cfg['vertical_deadzone']
        suppressed = not outside and (dx > 1e-6 or dy > 1e-6)
        if outside:
            if self.outside_since is None:
                self.outside_since = t
            if t-self.outside_since >= cfg['movement_confirm_seconds']:
                self.target[:2] = target[:2]
        else:
            self.outside_since = None
        if abs(target[2]-self.target[2]) > cfg['zoom_deadzone']:
            self.target[2] = target[2]
        before = [self.x.position, self.y.position, self.zoom.position]
        for axis, goal in zip((self.x, self.y), self.target[:2]):
            axis.advance(goal, dt, cfg['max_pan_speed'], cfg['max_pan_acceleration'], cfg['max_pan_jerk'])
        self.zoom.advance(self.target[2], dt, cfg['max_zoom_speed'],
                          cfg['max_zoom_acceleration'], cfg['max_zoom_jerk'])
        after = [self.x.position, self.y.position, self.zoom.position]
        return before, after, suppressed

    def snapshot(self, time):
        return {'time': time, 'center': [self.x.position, self.y.position],
                'zoom': self.zoom.position, 'target': list(self.target),
                'velocity': [self.x.velocity, self.y.velocity, self.zoom.velocity],
                'acceleration': [self.x.acceleration, self.y.acceleration, self.zoom.acceleration]}
