"""Immutable inputs and atomic state for the existing four-button Pipeline.

Only explicit curation creates a revision. Preview/approval/batch operations load
its cached AnalysisBundle and update state through a revision/version CAS.
Numbers use nine decimal places; integral floats and integers are equivalent.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import uuid

from .analysis_loader import AnalysisBundle


SCHEMA_VERSION = '5.2.0'
DOCUMENT_TYPE = 'PERSISTED_PIPELINE_PLAN'
_VOLATILE = {
    'diagnostics', 'reason', 'confidence', 'detection_confidence', 'needs_review',
    'observed_at', 'created_at', 'updated_at', 'generated_at', 'started_at',
    'finished_at', 'runtime_seconds', 'elapsed_seconds', 'cache_hit', 'status',
    'measurement_limits', 'root', 'origin_root',
}
_CAMERA_FIELDS = {
    'mode', 'normalized_center_x', 'normalized_center_y', 'split_centers_x',
    'segments', 'crop', 'crop_x', 'crop_y', 'crop_width', 'crop_height',
    'rotation', 'keyframes',
}
_SEGMENT_FIELDS = {
    'start', 'end', 'mode', 'center_x', 'center_y', 'center_x_start',
    'center_x_end', 'center_y_start', 'center_y_end', 'zoom', 'motion_follow',
    'motion_easing', 'subject_screen_y', 'split_centers_x', 'graphics_policy',
    'graphics_regions', 'panel_source_height', 'crop', 'crop_x', 'crop_y',
    'crop_width', 'crop_height', 'rotation', 'keyframes',
    'zoom_start', 'zoom_end', 'zoom_transition_start', 'zoom_transition_duration', 'zoom_easing',
}
_REGION_FIELDS = {'persistent', 'x_start', 'x_end', 'y_start', 'y_end'}
_CLIP_FIELDS = {
    'clip_id', 'rank', 'source_start', 'source_end', 'duration', 'title_text',
    'title_style', 'title_duration', 'subtitle_plan', 'subtitle_preset',
    'subtitle_overrides', 'audio', 'audio_plan', 'audio_mode', 'audio_settings',
    'crop', 'video', 'video_settings', 'speed', 'playback_rate',
}
_SETTINGS = ('render', 'subtitles', 'title', 'output', 'camera', 'camera_v44', 'audio')
_LEGACY_FILES = (
    'EDIT_DECISIONS.json', 'PREVIEW_REVIEW_V44.json',
    'FIRST_TEST_APPROVED_V44.json', 'FIRST_TEST_APPROVED.flag',
    'CHATGPT_HANDOFF.json', 'CHATGPT_HANDOFF.md', 'CURATION_REPORT.md',
)


class StalePlanError(RuntimeError):
    """A worker attempted to publish state for obsolete inputs/version."""


def canonical(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('O plano contém número não finito')
        number = round(value, 9)
        return int(number) if number.is_integer() else number
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError('Chaves do plano devem ser strings')
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    raise ValueError(f'Tipo não serializável no plano: {type(value).__name__}')


def _json_bytes(value):
    return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':')).encode('utf-8')


def _fingerprint(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _semantic(value):
    """Remove bookkeeping and locations; retain transcript/timings/media IDs."""
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items()
                if key not in _VOLATILE and key not in {'path', 'filename', 'file'}
                and not key.endswith(('_path', '_filepath', '_directory'))}
    if isinstance(value, (list, tuple)):
        return [_semantic(item) for item in value]
    return value


def render_settings(cfg):
    """Pin effects, excluding paths, model options and editorial-selection knobs."""
    result = {}
    for section in _SETTINGS:
        settings = cfg.get(section)
        if settings is not None:
            result[section] = _semantic(settings)
            # A font's contents affect rendering; moving identical bytes does not.
            if isinstance(settings, dict) and settings.get('font_path'):
                path = Path(settings['font_path'])
                result[section]['font_file_sha256'] = _file_hash(path) if path.is_file() else None
    return canonical(result)


def _camera_projection(plan):
    if not isinstance(plan, dict):
        return plan
    result = {key: plan[key] for key in _CAMERA_FIELDS if key in plan and key != 'segments'}
    if 'segments' in plan:
        result['segments'] = []
        for segment in plan.get('segments') or []:
            row = {key: segment[key] for key in _SEGMENT_FIELDS
                   if key in segment and key != 'graphics_regions'}
            if 'graphics_regions' in segment:
                row['graphics_regions'] = [
                    {key: region[key] for key in _REGION_FIELDS if key in region}
                    for region in segment.get('graphics_regions') or []
                ]
            result['segments'].append(row)
    return _semantic(result)


def _editorial_projection(decisions):
    rows = []
    for decision in decisions:
        row = {key: _semantic(decision[key]) for key in _CLIP_FIELDS if key in decision}
        row['camera_plan'] = _camera_projection(decision.get('camera_plan'))
        # Content hashes bind any optional music/effect file without binding its location.
        if (decision.get('audio') or {}).get('music_path'):
            from .media_effects import effect_input_fingerprints
            effects = effect_input_fingerprints(decision)
            row['effect_inputs'] = _semantic(effects)
        rows.append(row)
    return canonical(rows)


def editorial_fingerprint(decisions):
    """All clips in order, including duration/title duration and every camera."""
    return _fingerprint(_editorial_projection(decisions))


def _bundle_data(bundle):
    data = {}
    dictionaries = {'analysis', 'insights', 'review', 'second_package', 'second_decisions'}
    for field in fields(AnalysisBundle):
        default = {} if field.name in dictionaries else []
        if field.name == 'root':
            default = ''
        elif field.name == 'video_id':
            default = ''
        data[field.name] = deepcopy(getattr(bundle, field.name, default))
    data['root'] = str(data['root'])
    return data


def _source_projection(bundle):
    data = _semantic(_bundle_data(bundle))
    data.setdefault('analysis', {}).setdefault('metadata', {}).setdefault('sha256', None)
    return canonical(data)


def source_fingerprint(bundle):
    return _fingerprint(_source_projection(bundle))


def render_fingerprint(doc, clip_id, media_sha256, renderer_signature):
    if not any(row.get('clip_id') == clip_id for row in doc.get('approved_clips', [])):
        raise ValueError(f'Clip não pertence à revisão ativa: {clip_id}')
    return _fingerprint({
        'project_id': doc['project_id'], 'plan_revision': doc['plan_revision'],
        'source_fingerprint': doc['source_fingerprint'],
        'editorial_plan_fingerprint': doc['editorial_plan_fingerprint'],
        'render_settings': doc['render_settings'], 'clip_id': clip_id,
        'source_media_sha256': media_sha256, 'renderer_signature': renderer_signature,
    })


def _differences(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            location = f'{path}.{key}' if path else key
            if key not in before or key not in after:
                result.append(location)
            else:
                result.extend(_differences(before[key], after[key], location))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = [path + '.length'] if len(before) != len(after) else []
        for index, (left, right) in enumerate(zip(before, after)):
            result.extend(_differences(left, right, f'{path}[{index}]'))
        return result
    return [] if _json_bytes(before) == _json_bytes(after) else [path]


def compare_settings(pinned, cfg):
    pinned = pinned.get('render_settings', pinned)
    changed = _differences(canonical(pinned), render_settings(cfg))
    if changed:
        raise ValueError('Configuração de render mudou: ' + ', '.join(changed)
                         + '. Gere e aprove uma nova prévia com uma revisão explícita.')
    return []


def _read_json(path):
    try:
        with Path(path).open('r', encoding='utf-8-sig') as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f'Arquivo do plano ausente ou inválido: {Path(path).name}') from error


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(canonical(data), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True  # Unknown lock owner is never treated as dead.
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # INVALID_PARAMETER means no such PID.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _new_lock(path, owner):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(owner, handle)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _exclusive_lock(base_dir, name):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    reclaim = path.with_name(path.name + '.reclaim')
    owner = {'pid': os.getpid(), 'token': uuid.uuid4().hex}
    if reclaim.exists():
        recovery_owner = _read_json(reclaim)
        if _pid_alive(recovery_owner.get('pid')):
            raise RuntimeError('Outra operação está recuperando o bloqueio deste projeto')
        # A process may have died while recovering another stale lock. Only its
        # unchanged token and proven dead PID authorize removing this guard.
        if reclaim.exists() and _read_json(reclaim) == recovery_owner:
            try:
                reclaim.unlink()
            except FileNotFoundError:
                pass
    try:
        _new_lock(path, owner)
    except FileExistsError:
        record = _read_json(path)
        if _pid_alive(record.get('pid')):
            raise RuntimeError('Outra operação está em execução neste projeto') from None
        try:
            _new_lock(reclaim, owner)
        except FileExistsError:
            raise RuntimeError('Outra operação está recuperando o bloqueio deste projeto') from None
        try:
            if _read_json(path) != record or _pid_alive(record.get('pid')):
                raise RuntimeError('Bloqueio mudou durante a recuperação; tente novamente')
            path.unlink()
            _new_lock(path, owner)
        finally:
            if reclaim.exists() and _read_json(reclaim) == owner:
                reclaim.unlink()
    try:
        yield owner
    finally:
        if path.exists() and _read_json(path) == owner:
            path.unlink()


@contextmanager
def project_lock(base_dir):
    """One whole Pipeline operation per project; a live PID is never displaced."""
    with _exclusive_lock(base_dir, '.PLAN_OPERATION.lock') as owner:
        yield owner


class PlanStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir).resolve()
        self.pointer = self.base_dir / 'EDIT_DECISIONS.json'

    def revision_dir(self, doc):
        revision = str(doc.get('plan_revision', ''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', revision):
            raise ValueError('Identificador da revisão inválido')
        folder = (self.base_dir / 'revisions' / revision).resolve()
        if not folder.is_relative_to(self.base_dir):
            raise ValueError('Pasta da revisão fora do projeto')
        return folder

    def _reference(self, doc, key, expected_name):
        expected = self.revision_dir(doc) / expected_name
        value = doc.get(key, '')
        if not isinstance(value, str) or Path(value).is_absolute():
            raise ValueError(f'Referência do plano inválida: {key}')
        actual = (self.base_dir / value).resolve()
        if actual != expected or not actual.is_relative_to(self.base_dir):
            raise ValueError(f'Referência do plano inválida: {key}')
        return actual

    def _validate(self, doc):
        if doc.get('document_type') != DOCUMENT_TYPE or doc.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Plano legado: recupere os dados e gere uma revisão persistida antes do preview')
        input_path = self._reference(doc, 'plan_inputs', 'PLAN_INPUTS.json')
        snapshot_path = self._reference(doc, 'analysis_snapshot', 'ANALYSIS_SNAPSHOT.json')
        if _file_hash(input_path) != doc.get('plan_inputs_sha256'):
            raise ValueError('Entradas imutáveis da revisão mudaram: PLAN_INPUTS.json')
        inputs = _read_json(input_path)
        if _file_hash(snapshot_path) != doc.get('analysis_snapshot_sha256'):
            raise ValueError('Snapshot da análise mudou: ANALYSIS_SNAPSHOT.json')
        snapshot = _read_json(snapshot_path)
        raw_bundle = deepcopy(snapshot['bundle'])
        raw_bundle['root'] = self.revision_dir(doc)
        bundle = AnalysisBundle(**raw_bundle)
        expected = {
            'project_id': doc.get('project_id'), 'plan_revision': doc.get('plan_revision'),
            'source_fingerprint': source_fingerprint(bundle),
            'editorial_projection': _editorial_projection(doc.get('approved_clips', [])),
            'render_settings': render_settings(doc.get('render_config', {})),
        }
        frozen = {key: inputs.get(key) for key in expected}
        changes = _differences(frozen, expected)
        checks = {
            'video_id': doc.get('project_id'),
            'source_fingerprint': inputs.get('source_fingerprint'),
            'editorial_plan_fingerprint': _fingerprint(inputs.get('editorial_projection')),
            'render_settings': inputs.get('render_settings'),
            'plan_signature': inputs.get('plan_signature'),
        }
        changes.extend(_differences(checks, {key: doc.get(key) for key in checks}))
        if changes:
            raise StalePlanError('Entradas da revisão mudaram: ' + ', '.join(changes)
                                 + '. Crie uma nova revisão e revise outra prévia.')
        return bundle

    def create(self, bundle, decisions, cfg, source_input):
        # Validate numeric inputs before writing any revision or replacing a pointer.
        projection = _editorial_projection(decisions)
        source_data = _source_projection(bundle)
        settings = render_settings(cfg)
        snapshot = {'schema_version': SCHEMA_VERSION, 'bundle': _bundle_data(bundle)}
        canonical(snapshot)
        with _exclusive_lock(self.base_dir, '.PLAN_STATE.lock'):
            revision = uuid.uuid4().hex
            document = {
                'schema_version': SCHEMA_VERSION, 'document_type': DOCUMENT_TYPE,
                'project_id': bundle.video_id, 'video_id': bundle.video_id,
                'plan_revision': revision, 'source': deepcopy(bundle.source),
                'source_input': str(source_input),
                'source_aliases': sorted({str(source_input), str(bundle.video_id),
                                          str(bundle.source.get('url') or '')} - {''}),
                'approved_clips': deepcopy(decisions), 'render_config': deepcopy(cfg),
                'render_settings': settings, 'source_fingerprint': _fingerprint(source_data),
                'editorial_plan_fingerprint': _fingerprint(projection),
                'analysis_origin_fingerprint': _fingerprint(_semantic(bundle.analysis)),
                'approval_state': 'PLAN_READY', 'approval_record': None,
                'preview': None, 'results': [], 'state_version': 0,
            }
            document['plan_signature'] = _fingerprint({
                key: document[key] for key in
                ('source_fingerprint', 'editorial_plan_fingerprint', 'render_settings')
            })
            inputs = {
                'schema_version': SCHEMA_VERSION, 'project_id': bundle.video_id,
                'plan_revision': revision, 'source_fingerprint': document['source_fingerprint'],
                'source_projection': source_data, 'editorial_projection': projection,
                'render_settings': settings, 'plan_signature': document['plan_signature'],
            }
            directory = self.revision_dir(document)
            directory.mkdir(parents=True, exist_ok=False)
            archive = directory / 'legacy_archive'
            for name in _LEGACY_FILES:
                original = self.base_dir / name
                if original.is_file():
                    archive.mkdir(exist_ok=True)
                    shutil.copy2(original, archive / name)
            for key, name, data in (
                ('analysis_snapshot', 'ANALYSIS_SNAPSHOT.json', snapshot),
                ('plan_inputs', 'PLAN_INPUTS.json', inputs),
            ):
                path = directory / name
                _atomic_json(path, data)
                document[key] = path.relative_to(self.base_dir).as_posix()
                document[key + '_sha256'] = _file_hash(path)
            cached = self._validate(document)
            self._write_state(document)
            _atomic_json(self.pointer, document)  # Publish only after inputs/history exist.
        return deepcopy(document), cached

    def load(self, cfg=None, check_settings=True):
        if not self.pointer.is_file():
            raise FileNotFoundError('Nenhum plano persistido. Execute CURAR primeiro.')
        document = _read_json(self.pointer)
        bundle = self._validate(document)
        if cfg is not None and check_settings:
            compare_settings(document, cfg)
        return document, bundle

    def _write_state(self, document):
        directory = self.revision_dir(document)
        version = int(document['state_version'])
        history = directory / 'states' / f'{version:08d}_{uuid.uuid4().hex}.json'
        _atomic_json(history, document)
        _atomic_json(directory / 'STATE.json', document)

    def save_state(self, doc, expected_revision=None):
        with _exclusive_lock(self.base_dir, '.PLAN_STATE.lock'):
            active = _read_json(self.pointer)
            expected_revision = expected_revision or doc.get('plan_revision')
            if active.get('plan_revision') != expected_revision or doc.get('plan_revision') != expected_revision:
                raise StalePlanError('Revisão obsoleta: aprovada/em operação '
                                     + str(expected_revision) + '; ativa '
                                     + str(active.get('plan_revision')))
            if active.get('state_version') != doc.get('state_version'):
                raise StalePlanError('Resultado obsoleto: o estado desta revisão já foi atualizado')
            self._validate(active)
            self._validate(doc)
            for key in ('source_fingerprint', 'editorial_plan_fingerprint', 'plan_signature',
                        'analysis_snapshot_sha256', 'plan_inputs_sha256'):
                if doc.get(key) != active.get(key):
                    raise StalePlanError(f'Fingerprint da revisão mudou: {key}')
            saved = deepcopy(doc)
            saved['state_version'] = int(active['state_version']) + 1
            self._write_state(saved)
            _atomic_json(self.pointer, saved)
            return saved
