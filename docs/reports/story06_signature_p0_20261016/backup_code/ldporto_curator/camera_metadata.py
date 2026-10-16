"""Read-only binding of saved visual measurements to their source revision."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat


_SHA = re.compile(r'^[a-fA-F0-9]{64}$')
_TOLERANCE = .6
_ADDED = {'source_sha256', 'metadata_provenance'}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('Invalid expected source SHA256 for existing camera metadata')
    return value.lower()


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _checked_file(path):
    """Reject symbolic links, junctions and other Windows reparse points."""
    path = _absolute(path)
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except OSError as exc:
            raise ValueError('Existing camera metadata path is missing: ' + str(item)) from exc
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise ValueError('Existing camera metadata cannot use links or junctions: ' + str(item))
    if not path.is_file():
        raise ValueError('Existing camera metadata must reference a regular file: ' + str(path))
    return path


def _read(path):
    path = _checked_file(path)
    data = path.read_bytes()
    try:
        value = json.loads(data.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid existing camera metadata JSON: ' + str(path)) from exc
    if not isinstance(value, dict):
        raise ValueError('Existing camera metadata JSON must be an object: ' + str(path))
    return path, value, _digest(data)


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError('Invalid finite camera metadata time: ' + label)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid finite camera metadata time: ' + label) from exc
    if not math.isfinite(number):
        raise ValueError('Invalid finite camera metadata time: ' + label)
    return number


def _planning_parts(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Source camera plan has no planning_evidence binding')
    normalized = value.replace('\\', '/')
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or PureWindowsPath(value).drive or ':' in normalized or '..' in relative.parts or not relative.parts:
        raise ValueError('Source camera planning_evidence must stay inside its project')
    return relative.parts


def _bound_clip(path, plan_path, plan):
    parts = _planning_parts(plan.get('planning_evidence'))
    for clip in plan.get('approved_clips') or []:
        if not isinstance(clip, dict):
            continue
        identifier = clip.get('clip_id')
        if (not isinstance(identifier, str) or not identifier or identifier in {'.','..'}
                or '/' in identifier or '\\' in identifier or ':' in identifier):
            continue
        expected = _absolute(plan_path.parent.joinpath(*parts, 'clips', identifier, 'clip_micro_perception.json'))
        if path == expected:
            return clip
    raise ValueError('Existing camera metadata is not the exact clip path bound by planning_evidence')


def _validate_times(micro, clip):
    start = _finite(clip.get('source_start'), 'source_start')
    end = _finite(clip.get('source_end'), 'source_end')
    if start < 0 or end <= start:
        raise ValueError('Invalid source clip interval for existing camera metadata')
    def inside(value, label):
        time = _finite(value, label)
        if not start-_TOLERANCE <= time <= end+_TOLERANCE:
            raise ValueError('Existing camera metadata time is outside the bound source clip: ' + label)
        return time
    observations = micro.get('observations') or []
    regions = micro.get('visual_focus_regions') or []
    if not isinstance(observations, list) or not isinstance(regions, list):
        raise ValueError('Existing camera observations and visual regions must be lists')
    if observations or 'sampled_start' in micro or 'sampled_end' in micro:
        first = inside(micro.get('sampled_start'), 'sampled_start')
        last = inside(micro.get('sampled_end'), 'sampled_end')
        if last < first:
            raise ValueError('Existing camera sampled interval is reversed')
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError('Invalid existing camera observation')
        inside(observation.get('time'), 'observations['+str(index)+'].time')
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError('Invalid existing camera visual region')
        first, last = inside(region.get('start'), 'visual region start'), inside(region.get('end'), 'visual region end')
        if last <= first:
            raise ValueError('Existing camera visual region interval is reversed')
        for sample in region.get('samples') or []:
            if not isinstance(sample, dict):
                raise ValueError('Invalid existing camera visual sample')
            inside(sample.get('observed_at'), 'visual sample observed_at')


def load_existing_camera_metadata(path, expected_source_sha256, source_plan=None):
    """Load the exact measured clip referenced by a source-matched saved plan.

    Only JSON files are read. The original media is neither opened nor hashed.
    Returned provenance freezes hashes of both input files for later verification.
    """
    expected_sha = _sha(expected_source_sha256)
    path, micro, metadata_sha = _read(path)
    if source_plan is None:
        source_plan = next((parent/'EDIT_DECISIONS.json' for parent in path.parents
                            if (parent/'EDIT_DECISIONS.json').exists()), None)
        if source_plan is None:
            raise ValueError('Existing camera metadata has no ancestral EDIT_DECISIONS.json')
    plan_path, plan, plan_sha = _read(source_plan)
    if plan_path.name != 'EDIT_DECISIONS.json':
        raise ValueError('Existing camera source plan must be EDIT_DECISIONS.json')
    if _sha(plan.get('source_media_sha256')) != expected_sha:
        raise ValueError('Existing camera metadata belongs to a different source SHA256')
    if 'source_sha256' in micro and _sha(micro['source_sha256']) != expected_sha:
        raise ValueError('Existing camera payload source SHA256 differs from its bound plan')
    clip = _bound_clip(path, plan_path, plan)
    _validate_times(micro, clip)
    result = deepcopy(micro)
    result['source_sha256'] = expected_sha
    result['metadata_provenance'] = {'path':str(path), 'sha256':metadata_sha,
        'source_plan_path':str(plan_path), 'source_plan_sha256':plan_sha}
    return result


def verify_existing_camera_metadata(micro, expected_sha):
    """Rehash files and recheck source/path/times before consuming saved evidence."""
    expected_sha = _sha(expected_sha)
    if micro == {}:
        return {}
    if not isinstance(micro, dict) or _sha(micro.get('source_sha256')) != expected_sha:
        raise ValueError('Existing camera metadata source SHA256 is not verified')
    provenance = micro.get('metadata_provenance')
    if not isinstance(provenance, dict):
        raise ValueError('Existing camera metadata provenance is required')
    if not provenance.get('path') or not provenance.get('source_plan_path'):
        raise ValueError('Existing camera metadata provenance paths are required')
    loaded = load_existing_camera_metadata(provenance['path'], expected_sha,
                                          source_plan=provenance['source_plan_path'])
    if loaded['metadata_provenance'] != provenance:
        raise ValueError('Existing camera metadata or source plan SHA256 changed')
    if {key:value for key,value in loaded.items() if key not in _ADDED} != {
            key:value for key,value in micro.items() if key not in _ADDED}:
        raise ValueError('Existing camera metadata payload changed after verification')
    return deepcopy(loaded)
