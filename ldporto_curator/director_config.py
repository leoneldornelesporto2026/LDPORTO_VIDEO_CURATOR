"""Validated style parameters for the one shared camera director engine."""
import math
from copy import deepcopy

SMART_ZOOM_DEFAULTS = {
    'enabled': True, 'profile': 'natural', 'max_zoom_factor': 1.2,
    'max_upscale_ratio': 2.0, 'min_zoom_duration': 6.0,
    'min_hold_duration': 7.0, 'transition_duration': 6.0,
    'min_face_size': .08, 'max_face_size': .42,
    'medium_face_min': .12, 'medium_face_max': .26,
    'close_face_min': .26, 'close_face_max': .42,
    'min_confidence': .8, 'max_zoom_events_per_minute': 2,
    'min_speaker_persistence': 1.5, 'max_source_motion': .08,
}
SMART_ZOOM_PROFILES = {
    'conservative': {'max_zoom_factor': 1.12, 'min_hold_duration': 12., 'transition_duration': 8.},
    'natural': {},
    'dynamic': {'max_zoom_factor': 1.3, 'min_hold_duration': 5., 'max_zoom_events_per_minute': 4},
}


def resolve_smart_zoom(raw=None):
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - set(SMART_ZOOM_DEFAULTS):
        raise ValueError('smart_zoom possui opcoes invalidas')
    profile = raw.get('profile', 'natural')
    if profile not in SMART_ZOOM_PROFILES:
        raise ValueError('smart_zoom.profile invalido')
    cfg = {**SMART_ZOOM_DEFAULTS, **SMART_ZOOM_PROFILES[profile], **raw}
    for key, default in SMART_ZOOM_DEFAULTS.items():
        value = cfg[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError('smart_zoom.' + key + ' deve ser booleano')
        elif isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('smart_zoom.' + key + ' deve ser positivo finito')
    if not 1 <= cfg['max_zoom_factor'] <= 1.4 or not 1 <= cfg['max_upscale_ratio'] <= 3:
        raise ValueError('Smart zoom/upscale fora dos limites de seguranca')
    if not 0 < cfg['min_confidence'] <= 1 or not 0 < cfg['min_face_size'] < cfg['max_face_size'] <= .8:
        raise ValueError('Smart zoom confidence/face size invalido')
    for low, high in (('medium_face_min', 'medium_face_max'), ('close_face_min', 'close_face_max')):
        if not 0 < cfg[low] < cfg[high] <= .8:
            raise ValueError('Smart zoom framing range invalido')
    if not isinstance(cfg['max_zoom_events_per_minute'], int) or not 1 <= cfg['max_zoom_events_per_minute'] <= 6:
        raise ValueError('Smart zoom event rate deve estar em [1,6]')
    if cfg['min_zoom_duration'] < 3 or max(cfg['min_zoom_duration'], cfg['transition_duration'], cfg['min_hold_duration']) > 60:
        raise ValueError('Smart zoom duracoes fora dos limites')
    return cfg

DEFAULTS = {
    'dominant_face_fallback': False, 'minimum_face_duration': 2., 'minimum_dominance_margin': .35,
    'minimum_target_confidence': .85, 'minimum_face_visibility': .8, 'maximum_center_velocity': .10,
    'smart_zoom': deepcopy(SMART_ZOOM_DEFAULTS),
    'enabled': True, 'profile': 'natural', 'lookahead_seconds': 1.8,
    'min_hold_seconds': 3.0, 'preferred_hold_seconds': 6.0,
    'switch_cooldown_seconds': 3.0, 'speaker_confirm_seconds': .9,
    'short_interruption_seconds': 1.0, 'switch_margin': .15,
    'switch_cost': .08, 'persistence_bonus': .08,
    'enter_confidence': .70, 'exit_confidence': .45,
    'horizontal_deadzone': .06, 'vertical_deadzone': .05,
    'movement_confirm_seconds': .5, 'zoom_deadzone': .035,
    'max_zoom_default': 1.35, 'max_zoom_hard': 1.40,
    'normal_zoom': 1.18, 'breathing_zoom': 1.08, 'payoff_zoom': 1.28,
    'breathing_after_seconds': 20.0, 'tick_seconds': .25,
    'max_observation_gap_seconds': .6, 'max_pan_speed': .12,
    'max_pan_acceleration': .18, 'max_pan_jerk': .60,
    'max_zoom_speed': .035, 'max_zoom_acceleration': .045,
    'max_zoom_jerk': .15, 'output_width': 1080, 'output_height': 1920,
    'min_face_height': .06, 'min_sharpness': 40.0,
    'headroom': .04, 'lead_room': .04,
    'quick_exchange_switches': 3, 'quick_exchange_window_seconds': 5.0,
    'enable_split': True, 'enable_reaction_shots': True,
    'enable_lookahead': True, 'debug_output': True,
    'reaction_threshold': .70, 'reaction_delta': .35,
    'reaction_seconds': 1.8, 'reaction_cooldown_seconds': 20.0,
}
PROFILES = {
    'natural': {},
    'podcast': {'min_hold_seconds': 4., 'preferred_hold_seconds': 9.,
                'switch_cooldown_seconds': 4., 'reaction_cooldown_seconds': 35.},
    'dynamic_short': {'min_hold_seconds': 2.5, 'preferred_hold_seconds': 5.,
                      'switch_cooldown_seconds': 2.5, 'normal_zoom': 1.22},
    'documentary': {'min_hold_seconds': 5., 'preferred_hold_seconds': 10.,
                    'normal_zoom': 1.05, 'enable_reaction_shots': False},
    'conservative': {'min_hold_seconds': 6., 'preferred_hold_seconds': 12.,
                     'normal_zoom': 1.05, 'enable_split': False,
                     'enable_reaction_shots': False},
}


def resolve_config(raw=None):
    if raw is not None and not isinstance(raw, dict):
        raise ValueError("camera_director deve ser objeto")
    raw = raw or {}
    unknown = set(raw)-set(DEFAULTS)
    if unknown:
        raise ValueError('camera_director: opções desconhecidas: '+', '.join(sorted(unknown)))
    profile = raw.get('profile', 'natural')
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError('camera_director.profile inválido')
    cfg = {**deepcopy(DEFAULTS), **PROFILES[profile], **{k: v for k, v in raw.items() if v is not None}}
    cfg['smart_zoom'] = resolve_smart_zoom(raw.get('smart_zoom'))
    for key, default in DEFAULTS.items():
        value = cfg[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f'camera_director.{key} deve ser booleano')
        elif isinstance(default, (float, int)):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f'camera_director.{key} deve ser número finito')
            if value < 0:
                raise ValueError(f'camera_director.{key} deve ser não negativo')
            if isinstance(default, int) and (not isinstance(value, int) or value < 1):
                raise ValueError(f'camera_director.{key} deve ser inteiro positivo')
    for key in ('switch_margin', 'switch_cost', 'persistence_bonus', 'enter_confidence',
                'minimum_dominance_margin', 'minimum_target_confidence', 'minimum_face_visibility',
                'exit_confidence', 'horizontal_deadzone', 'vertical_deadzone', 'zoom_deadzone',
                'min_face_height', 'headroom', 'lead_room', 'reaction_threshold', 'reaction_delta'):
        if not 0 <= cfg[key] <= 1:
            raise ValueError(f'camera_director.{key} deve estar entre 0 e 1')
    if not .1 <= cfg['tick_seconds'] <= 1:
        raise ValueError('camera_director.tick_seconds deve estar entre .1 e 1')
    if not 0 < cfg['max_observation_gap_seconds'] <= 2:
        raise ValueError('camera_director.max_observation_gap_seconds deve estar em (0, 2]')
    for key in ('min_hold_seconds', 'speaker_confirm_seconds', 'max_pan_speed',
                'max_pan_acceleration', 'max_pan_jerk', 'max_zoom_speed',
                'max_zoom_acceleration', 'max_zoom_jerk', 'quick_exchange_window_seconds',
                'reaction_seconds'):
        if cfg[key] <= 0:
            raise ValueError(f'camera_director.{key} deve ser positivo')
    if cfg['preferred_hold_seconds'] < cfg['min_hold_seconds']:
        raise ValueError('preferred_hold_seconds deve ser >= min_hold_seconds')
    if cfg['exit_confidence'] > cfg['enter_confidence']:
        raise ValueError('exit_confidence deve ser <= enter_confidence')
    if not 1 <= cfg['max_zoom_default'] <= cfg['max_zoom_hard'] <= 2:
        raise ValueError('Exigir 1 <= max_zoom_default <= max_zoom_hard <= 2')
    for key in ('normal_zoom', 'breathing_zoom', 'payoff_zoom'):
        if not 1 <= cfg[key] <= cfg['max_zoom_hard']:
            raise ValueError(f'camera_director.{key} fora dos limites de zoom')
    if cfg['lookahead_seconds'] > 5:
        raise ValueError('lookahead_seconds deve ser <= 5')
    limits = {'min_hold_seconds': 60, 'preferred_hold_seconds': 120,
              'switch_cooldown_seconds': 60, 'speaker_confirm_seconds': 10,
              'short_interruption_seconds': 10, 'movement_confirm_seconds': 10,
              'breathing_after_seconds': 600, 'reaction_seconds': 10,
              'reaction_cooldown_seconds': 600, 'quick_exchange_window_seconds': 60,
              'max_pan_speed': 1, 'max_pan_acceleration': 4, 'max_pan_jerk': 20,
              'max_zoom_speed': 1, 'max_zoom_acceleration': 4, 'max_zoom_jerk': 20,
              'output_width': 16384, 'output_height': 16384, 'quick_exchange_switches': 100,
              'min_sharpness': 100000}
    for key, maximum in limits.items():
        if cfg[key] > maximum:
            raise ValueError(f'camera_director.{key} excede {maximum}')
    if cfg['horizontal_deadzone'] > .3 or cfg['vertical_deadzone'] > .3:
        raise ValueError('Deadzone não pode exceder .3 do frame')
    if cfg['headroom'] > .2 or cfg['lead_room'] > .2:
        raise ValueError('Headroom/lead_room não podem exceder .2 do frame')
    return cfg
