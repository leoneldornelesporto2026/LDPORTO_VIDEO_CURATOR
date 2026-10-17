"""Read-only, bounded production-package validation; no extraction or approval.

Editorial decisions are proposals. This adapter deliberately leaves rendering,
source association, staging and state commits to the existing project services.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
import zipfile

MAX_FILES = 5000
MAX_BYTES = 256 * 1024 ** 2
MAX_COMPRESSION_RATIO = 200
_SHA = re.compile(r'[a-f0-9]{64}')
_ALLOWED = {'.json', '.jsonl', '.md', '.txt', '.srt', '.ass', '.vtt', '.jpg',
            '.jpeg', '.png', '.webp', '.pdf', '.html', '.csv', '.zip', '.sha256'}
_MODES = {'crop': 'crop', 'full_frame_blur': 'full_frame_blur', 'split_screen': 'split_screen',
          'FULL_VERTICAL_9X16': 'crop', 'MEDIUM_SHOT': 'crop', 'INSTRUMENT_FOCUS': 'crop',
          'AUDIENCE_FOCUS': 'crop', 'SOURCE_FIT_BLUR': 'full_frame_blur',
          'SOURCE_PRESERVE': 'full_frame_blur', 'DUO_COMPOSITION': 'split_screen'}
_PART_FILES = ('editorial.json', 'source_segments.json', 'camera_timeline.json',
               'caption_plan.json', 'safe_areas.json', 'title_overlay.json')
_REEL_EXTRA = ('camera_keyframes.json', 'audio_plan.json', 'thumbnail_plan.json',
               'visual_evidence_refs.json')


def _fail(message):
    raise ValueError(message)


def _json(payload, name):
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            _fail('Nonfinite JSON: ' + name)
        return number
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                _fail('Duplicate JSON key: ' + name + ': ' + key)
            result[key] = value
        return result
    try:
        return json.loads(payload.decode('utf-8-sig'), object_pairs_hook=pairs,
                          parse_float=finite_float,
                          parse_constant=lambda value: _fail('Nonfinite JSON: ' + name))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid JSON: ' + name) from exc


def _number(value, label, low=0., high=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < low or high is not None and value > high):
        _fail('Invalid finite value: ' + label)
    return float(value)


def _sha(value, label):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        _fail('Invalid SHA256: ' + label)
    return value


def _relative(value, *, directory=False):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        _fail('Unsafe package path: ' + str(value))
    name = value[:-1] if directory and value.endswith('/') else value
    parts = name.split('/')
    if (not name or PurePosixPath(name).is_absolute() or unicodedata.normalize('NFC', name) != name
            or any(ord(c) < 32 or c in '<>"|?*' for c in name)
            or any(p in {'', '.', '..'} or p.endswith((' ', '.')) for p in parts)
            or any(re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in parts)):
        _fail('Unsafe/noncanonical package path: ' + value)
    return name


def _checked_path(value):
    path = Path(os.path.abspath(value))
    for node in (path, *path.parents):
        info = node.lstat()
        if node.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            _fail('Links/junctions not permitted: ' + str(node))
    return path.resolve(strict=True)


def _zip_members(archive):
    members = archive.infolist()
    if len(members) > MAX_FILES:
        _fail('Package exceeds file-count limit')
    seen, files, total = set(), {}, 0
    for member in members:
        name = _relative(member.filename, directory=member.is_dir())
        key = name.casefold()
        if key in seen:
            _fail('Duplicate/case-colliding package path: ' + name)
        seen.add(key)
        mode = stat.S_IFMT(member.external_attr >> 16)
        if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or member.flag_bits & 1:
            _fail('Linked, special or encrypted ZIP entry: ' + name)
        if member.is_dir():
            continue
        if Path(name).suffix.lower() not in _ALLOWED:
            _fail('Executable/unsupported package member: ' + name)
        total += member.file_size
        if total > MAX_BYTES or member.file_size > MAX_BYTES:
            _fail('Package exceeds unpacked-byte limit')
        if member.file_size > max(1, member.compress_size) * MAX_COMPRESSION_RATIO:
            _fail('Package exceeds compression-ratio limit: ' + name)
        files[name] = member
    folded = {name.casefold() for name in files}
    for name in files:
        if any(parent.as_posix().casefold() in folded for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
            _fail('File/directory collision: ' + name)
    return files


def _read_zip_files(archive, members):
    files = {}
    for name, member in members.items():
        payload = archive.read(member)
        if len(payload) != member.file_size:
            _fail('Package member changed: ' + name)
        files[name] = payload
    return files


def _manifest_files(files, manifest, excluded):
    rows = manifest.get('files')
    if not isinstance(rows, list):
        _fail('Manifest files list missing')
    listed, folded = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            _fail('Malformed manifest file record')
        name = _relative(row.get('path'))
        if name in excluded or name.casefold() in folded:
            _fail('Duplicate/self-referential manifest record: ' + name)
        folded.add(name.casefold())
        size = row.get('bytes')
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail('Invalid manifest byte count: ' + name)
        expected = _sha(row.get('sha256'), name)
        if name not in files or len(files[name]) != size or hashlib.sha256(files[name]).hexdigest() != expected:
            _fail('Manifest checksum/size mismatch: ' + name)
        listed[name] = row
    if set(listed) != set(files) - set(excluded):
        _fail('Manifest does not declare every package file')


def _metadata(value, expected_sha=None):
    if not isinstance(value, dict):
        _fail('Source metadata must be an object')
    result = deepcopy(value)
    result['sha256'] = _sha(value.get('source_sha256') or value.get('sha256'), 'source')
    if expected_sha and result['sha256'] != expected_sha:
        _fail('Source SHA256 mismatch')
    technical = value.get('technical') or value
    if not isinstance(technical, dict):
        _fail('Source technical metadata must be an object')
    result['duration'] = _number(technical.get('duration'), 'source.duration', .001)
    result['fps'] = _number(technical.get('fps'), 'source.fps', .001, 1000)
    for key in ('width', 'height'):
        field = technical.get(key)
        if isinstance(field, bool) or not isinstance(field, int) or field <= 0:
            _fail('Invalid source dimension: ' + key)
        result[key] = field
    return result


def _reject_approval(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (key in {'approved', 'human_approved', 'preview_approved', 'preview_approved_by_human',
                        'publication_ready', 'publication_approved'} and item is not False and item is not None
                    or key in {'approval', 'human_approval'} and item not in (None, False, {}, [])):
                _fail('Package cannot grant human approval: ' + key)
            _reject_approval(item)
    elif isinstance(value, list):
        for item in value:
            _reject_approval(item)


def _dossier(files, *, expected_source_sha256=None, expected_package_sha256=None):
    manifest = _json(files.get('PROJECT_MANIFEST.json', b'{}'), 'PROJECT_MANIFEST.json')
    if manifest.get('contract') != 'ldporto.project_dossier' or manifest.get('schema_version') != '1.0':
        _fail('Unsupported EDITORIAL_HANDOFF contract/version')
    _reject_approval({k: manifest[k] for k in ('preview_approved', 'publication_ready') if k in manifest})
    _manifest_files(files, manifest, {'PROJECT_MANIFEST.json'})
    source_sha = _sha(manifest.get('source_sha256'), 'PROJECT_MANIFEST.source_sha256')
    if expected_source_sha256 and source_sha != expected_source_sha256:
        _fail('Editorial handoff source SHA256 mismatch')
    package_sha = _sha(manifest.get('package_sha256'), 'PROJECT_MANIFEST.package_sha256')
    if expected_package_sha256 and package_sha != expected_package_sha256:
        _fail('Editorial handoff original package SHA256 mismatch')
    nested = files.get('06_SEGUNDA_CURADORIA/SECOND_CURATION_READY.zip')
    if nested is not None:
        if hashlib.sha256(nested).hexdigest() != package_sha:
            _fail('Editorial handoff nested package SHA256 mismatch')
        with zipfile.ZipFile(BytesIO(nested)) as archive:
            members = _zip_members(archive)
            if 'source/metadata.json' not in members or 'SECOND_CURATION_MANIFEST.json' not in members:
                _fail('Nested Analyzer package has no source identity')
            raw = archive.read(members['source/metadata.json'])
            nested_manifest = _json(archive.read(members['SECOND_CURATION_MANIFEST.json']), 'nested manifest')
            refs = [r for r in nested_manifest.get('files', []) if r.get('path') == 'source/metadata.json']
            if (len(refs) != 1 or refs[0].get('bytes') != len(raw)
                    or refs[0].get('sha256') != hashlib.sha256(raw).hexdigest()
                    or nested_manifest.get('source_hash') != source_sha):
                _fail('Nested source metadata checksum mismatch')
            metadata = _metadata(_json(raw, 'nested source/metadata.json'), source_sha)
    elif 'media_reference.json' in files:
        metadata = _metadata(_json(files['media_reference.json'], 'media_reference.json'), source_sha)
    else:
        _fail('Editorial handoff source technical metadata missing')
    if manifest.get('source_duration') != metadata['duration']:
        _fail('Editorial handoff source duration mismatch')
    return manifest, metadata


def _rows(value, key, label):
    rows = value if isinstance(value, list) else value.get(key) if isinstance(value, dict) else None
    if not isinstance(rows, list):
        _fail('Expected list: ' + label)
    return rows


def _window(row, duration, label):
    if not isinstance(row, dict):
        _fail('Interval must be an object: ' + label)
    start = _number(row.get('start', row.get('source_start')), label + '.start', 0, duration)
    end = _number(row.get('end', row.get('source_end')), label + '.end', 0, duration)
    if end <= start:
        _fail('Empty/reversed interval: ' + label)
    return start, end


def _regions(value):
    if isinstance(value, dict):
        if value.get('coordinate_space', 'normalized') != 'normalized':
            _fail('Safe areas must declare normalized coordinates')
        if any(key in value for key in ('x_start', 'x_end', 'y_start', 'y_end')):
            x0 = _number(value.get('x_start'), 'region.x_start', 0, 1)
            x1 = _number(value.get('x_end'), 'region.x_end', 0, 1)
            y0 = _number(value.get('y_start'), 'region.y_start', 0, 1)
            y1 = _number(value.get('y_end'), 'region.y_end', 0, 1)
            if x1 <= x0 or y1 <= y0:
                _fail('Reversed protected region')
        if 'bbox' in value:
            box = value['bbox']
            if value.get('bbox_format') != 'xyxy' or not isinstance(box, list) or len(box) != 4:
                _fail('Bounding boxes require explicit normalized xyxy format')
            _regions(dict(zip(('x_start', 'y_start', 'x_end', 'y_end'), box)))
        if 'x' in value or 'y' in value:
            x = _number(value.get('x'), 'region.x', 0, 1)
            y = _number(value.get('y'), 'region.y', 0, 1)
            width = _number(value.get('width'), 'region.width', .000001, 1)
            height = _number(value.get('height'), 'region.height', .000001, 1)
            if x + width > 1 + 1e-9 or y + height > 1 + 1e-9:
                _fail('Protected region exceeds source bounds')
        for item in value.values():
            if isinstance(item, (dict, list)):
                _regions(item)
    elif isinstance(value, list):
        for item in value:
            _regions(item)


def _camera(timeline, duration, keyframes):
    if not isinstance(timeline, dict) or timeline.get('timebase', 'clip_relative') != 'clip_relative':
        _fail('Camera timeline must use clip_relative timestamps')
    if timeline.get('coordinate_space', 'normalized') != 'normalized':
        _fail('Camera centers must use normalized coordinates')
    segments = _rows(timeline, 'segments', 'camera_timeline.segments')
    if not segments:
        _fail('Camera timeline has no segments')
    result, cursor = [], 0.
    for raw in segments:
        if not isinstance(raw, dict):
            _fail('Malformed camera segment')
        row = deepcopy(raw)
        start, end = _window(row, duration, 'camera segment')
        if abs(start - cursor) > 1e-6:
            _fail('Camera timeline gap/overlap: provide explicit wide fallback intervals')
        cursor = end
        mode = _MODES.get(row.get('mode'))
        if mode is None:
            _fail('Unsupported camera mode: ' + str(row.get('mode')))
        row.update(start=start, end=end, mode=mode)
        if mode == 'crop':
            for axis in ('x', 'y'):
                if 'center_' + axis not in row and not all('center_' + axis + suffix in row for suffix in ('_start', '_end')):
                    _fail('Crop requires measured center_' + axis + '; no coordinates are inferred')
            for key in ('center_x', 'center_y', 'center_x_start', 'center_x_end', 'center_y_start', 'center_y_end', 'subject_screen_y'):
                if key in row:
                    _number(row[key], key, 0, 1)
            for key in ('zoom', 'zoom_start', 'zoom_end'):
                if key in row:
                    _number(row[key], key, 1, 1.05 if key != 'zoom' else 1.13)
            if 'zoom_start' in row or 'zoom_end' in row:
                delay = _number(row.get('zoom_transition_start', 0), 'zoom delay', 0, end - start)
                length = _number(row.get('zoom_transition_duration', end - start), 'zoom duration', .001, end - start)
                if delay + length > end - start + 1e-6:
                    _fail('Zoom envelope exceeds its measured interval')
        if mode == 'split_screen':
            centers = row.get('split_centers_x')
            if not isinstance(centers, list) or len(centers) != 2:
                _fail('Duo composition requires two measured centers')
            for center in centers:
                _number(center, 'split center', 0, 1)
        result.append(row)
    if abs(cursor - duration) > 1e-6:
        _fail('Camera timeline must cover the complete piece with explicit fallbacks')
    previous = -1.
    for row in _rows(keyframes, 'keyframes', 'camera_keyframes'):
        time = _number(row.get('time'), 'keyframe.time', 0, duration)
        if time <= previous:
            _fail('Camera keyframes must be strictly ordered')
        previous = time
        for key in ('center_x', 'center_y'):
            _number(row.get(key), 'keyframe.' + key, 0, 1)
        if 'zoom' in row:
            _number(row['zoom'], 'keyframe.zoom', 1, 1.13)
    return {'mode': 'adaptive_timeline', 'segments': result}


def _evidence(value, metadata):
    if (not isinstance(value, dict) or not isinstance(value.get('source'), dict)
            or value['source'].get('sha256') != metadata['sha256']):
        _fail('Normalized evidence source SHA256 mismatch')
    source = value['source']
    for key in ('duration', 'width', 'height'):
        if source.get(key) != metadata[key]:
            _fail('Normalized evidence source technical mismatch: ' + key)
    segments, words = {}, {}
    for row in value.get('segments') or []:
        key = row.get('segment_id')
        if not isinstance(key, str) or not key or key in segments:
            _fail('Duplicate/missing source segment ID')
        _window(row, metadata['duration'], 'source segment')
        segments[key] = row
    for row in value.get('words') or []:
        key = row.get('word_id')
        if not isinstance(key, str) or not key or key in words or row.get('segment_id') not in segments:
            _fail('Duplicate/unresolved source word ID')
        start, end = _window(row, metadata['duration'], 'source word')
        segment = segments[row['segment_id']]
        if start < segment['start'] or end > segment['end']:
            _fail('Source word escapes its measured segment')
        words[key] = row
    candidates = set()
    for row in value.get('candidates') or []:
        identifier = row.get('candidate_id')
        if not isinstance(identifier, str) or not identifier or identifier in candidates:
            _fail('Duplicate/missing source candidate ID')
        _window(row, metadata['duration'], 'source candidate')
        candidates.add(identifier)
    return segments, words, candidates


def _asset_dependencies(document, files):
    """Asset references always name declared members, never host paths."""
    if isinstance(document, dict):
        for key, value in document.items():
            if key in {'asset_path', 'asset_ref', 'image_path', 'font_path', 'music_path', 'file_ref'} and value:
                if _relative(value) not in files:
                    _fail('Unresolved asset dependency: ' + value)
            elif key in {'asset_refs', 'file_refs'} and value:
                if not isinstance(value, list):
                    _fail('Asset reference list required')
                for item in value:
                    name = _relative(item if isinstance(item, str) else item.get('path'))
                    if name not in files:
                        _fail('Unresolved asset dependency: ' + name)
            if isinstance(value, (dict, list)):
                _asset_dependencies(value, files)
    elif isinstance(document, list):
        for item in document:
            _asset_dependencies(item, files)


def _piece(files, folder, kind, metadata, evidence, series=None, order=None):
    names = [*_PART_FILES, *(_REEL_EXTRA if kind == 'reel' else ())]
    missing = [name for name in names if folder + '/' + name not in files]
    if missing:
        _fail('Missing required ' + kind + ' files in ' + folder + ': ' + ', '.join(missing))
    docs = {name[:-5]: _json(files[folder + '/' + name], folder + '/' + name)
            for name in (*_PART_FILES, *_REEL_EXTRA) if folder + '/' + name in files}
    editorial = docs['editorial']
    if not isinstance(editorial, dict):
        _fail('Editorial record must be an object: ' + folder)
    _reject_approval(editorial)
    identifier = next((editorial.get(key) for key in ('piece_id', 'episode_id', 'clip_id', 'candidate_id') if editorial.get(key)), None)
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', identifier):
        _fail('Missing/unsafe piece ID: ' + folder)
    candidate_refs = editorial.get('candidate_ids') or ([editorial['candidate_id']] if editorial.get('candidate_id') else [])
    if not isinstance(candidate_refs, list) or not set(candidate_refs) <= evidence[2]:
        _fail('Unresolved source candidate IDs')
    if editorial.get('source_sha256', metadata['sha256']) != metadata['sha256']:
        _fail('Editorial piece source SHA256 mismatch')
    source_rows = _rows(docs['source_segments'], 'segments', folder + '/source_segments.json')
    if not source_rows:
        _fail('Piece has no source intervals')
    starts, ends = [], []
    for row in source_rows:
        start, end = _window(row, metadata['duration'], 'source interval')
        if ends and abs(start - ends[-1]) > 1e-6:
            _fail('UNSUPPORTED_SOURCE_EDIT: source intervals must be contiguous and ordered')
        starts.append(start); ends.append(end)
        refs = row.get('segment_ids') or ([row['segment_id']] if row.get('segment_id') else [])
        if not isinstance(refs, list) or not set(refs) <= evidence[0].keys():
            _fail('Unresolved source segment IDs')
        if any(evidence[0][ref]['start'] >= end or evidence[0][ref]['end'] <= start for ref in refs):
            _fail('Source segment reference does not overlap its source interval')
    duration = ends[-1] - starts[0]
    if kind == 'story' and duration > 59.5 + 1e-6:
        _fail('Story exceeds the installed 59.5-second encoding-safe limit')
    timeline = docs['camera_timeline']
    if not isinstance(timeline, dict):
        _fail('Camera timeline must be an object')
    for key in ('width', 'height'):
        if timeline.get('source_' + key, metadata[key]) != metadata[key]:
            _fail('Camera source dimensions mismatch: ' + key)
    camera = _camera(timeline, duration, docs.get('camera_keyframes', {'keyframes': []}))
    _regions(docs['safe_areas'])
    overlay = docs['title_overlay']
    if not isinstance(overlay, dict) or set(overlay) - {'text', 'enabled', 'duration', 'position_y'}:
        _fail('Title overlay contains controls unsupported by the installed renderer')
    if 'text' in overlay and (not isinstance(overlay['text'], str) or len(overlay['text']) > 240):
        _fail('Title overlay requires literal text up to 240 characters')
    if 'enabled' in overlay and not isinstance(overlay['enabled'], bool):
        _fail('Title overlay enabled must be boolean')
    if 'duration' in overlay:
        _number(overlay['duration'], 'title duration', .001, duration)
    if 'position_y' in overlay and abs(_number(overlay['position_y'], 'title position', 0, 1) - .13) > 1e-9:
        _fail('Installed title renderer supports only position_y=0.13; no overlay was silently relocated')
    caption = docs['caption_plan']
    if not isinstance(caption, dict):
        _fail('Caption plan must be an object')
    if not set(caption.get('word_ids') or []) <= evidence[1].keys():
        _fail('Caption references unknown source word IDs')
    for word_id in caption.get('word_ids') or []:
        original = evidence[1][word_id]
        if original['start'] < starts[0] or original['end'] > ends[-1]:
            _fail('Caption word lies outside its source interval')
    for word in caption.get('words') or []:
        original = evidence[1].get(word.get('word_id'))
        if original is None or any(word.get(key) != original.get(key) for key in ('segment_id', 'start', 'end', 'word') if key in word):
            _fail('Caption word text/timestamp differs from original evidence')
        if 'text' in word and word['text'] != original.get('word', original.get('text')):
            _fail('Caption literal text differs from original evidence')
        if original['start'] < starts[0] or original['end'] > ends[-1]:
            _fail('Caption word lies outside its source interval')
    for document in docs.values():
        _reject_approval(document)
        _asset_dependencies(document, files)
    for key in ('asset_refs', 'visual_evidence_refs', 'file_refs'):
        for ref in editorial.get(key) or []:
            name = _relative(ref)
            if name not in files:
                _fail('Unresolved piece asset reference: ' + name)
    visual = docs.get('visual_evidence_refs')
    if visual is not None:
        refs = _rows(visual, 'refs', 'visual_evidence_refs')
        for ref in refs:
            name = _relative(ref if isinstance(ref, str) else ref.get('path'))
            if name not in files:
                _fail('Unresolved visual evidence reference: ' + name)
    audio = docs.get('audio_plan') or {'mode': 'original'}
    if not isinstance(audio, dict) or audio.get('mode', 'original') not in {'original', 'normalize'}:
        _fail('Unsupported imported audio plan; original music is the default')
    if audio.get('music_path'):
        if _relative(audio['music_path']) not in files:
            _fail('Unresolved audio asset')
    return {'kind': kind, 'path': folder, 'piece_id': identifier, 'series_id': series, 'order': order,
            'source_start': starts[0], 'source_end': ends[-1], 'duration': duration,
            'camera_plan': camera, 'editorial': editorial, 'caption_plan': caption,
            'documents': docs, 'audio_plan': audio, 'human_approval': None,
            'state': 'HUMAN_REVIEW_REQUIRED'}


def _curator_ready(files):
    import jsonschema
    manifest = _json(files.get('manifest.json', b'{}'), 'manifest.json')
    schema = _json((Path(__file__).parent.parent / 'schemas/curator_ready_v1.schema.json').read_bytes(), 'curator_ready schema')
    try:
        jsonschema.validate(manifest, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError('CURATOR_READY manifest schema: ' + exc.message) from exc
    _reject_approval(manifest)
    _manifest_files(files, manifest, {'manifest.json', 'checksums.sha256'})
    checksums = files.get('checksums.sha256')
    if checksums is None:
        _fail('Missing checksums.sha256')
    checked = set()
    for line in checksums.decode('utf-8-sig').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64}) [ *](.+)', line)
        if not match:
            _fail('Malformed checksums.sha256 line')
        name = _relative(match[2])
        if name == 'checksums.sha256' or name in checked or name not in files or hashlib.sha256(files[name]).hexdigest() != match[1]:
            _fail('Invalid/duplicate checksum reference: ' + name)
        checked.add(name)
    if checked != set(files) - {'checksums.sha256'}:
        _fail('checksums.sha256 must include every file except itself, including manifest.json')
    for name in ('media_reference.json', 'editorial_revision.json', 'evidence/evidence.json'):
        if name not in files:
            _fail('Missing required CURATOR_READY file: ' + name)
    metadata = _metadata(_json(files['media_reference.json'], 'media_reference.json'), manifest['source_sha256'])
    revision = _json(files['editorial_revision.json'], 'editorial_revision.json')
    if (not isinstance(revision, dict) or revision.get('provider') not in {'manual_json', 'ChatGPT'}
            or revision.get('state') != 'HUMAN_REVIEW_REQUIRED'):
        _fail('Editorial revision must identify its provider and HUMAN_REVIEW_REQUIRED state')
    _reject_approval(revision)
    if revision.get('source_sha256', metadata['sha256']) != metadata['sha256']:
        _fail('Editorial revision source SHA256 mismatch')
    evidence_document = _json(files['evidence/evidence.json'], 'evidence/evidence.json')
    evidence = _evidence(evidence_document, metadata)
    pieces, folders, identifiers, series_ids = [], set(), set(), set()
    for entry in manifest['reels']:
        folder = _relative(entry['path'])
        if not folder.startswith('REELS/'):
            _fail('Reel folder must stay under REELS')
        pieces.append(_piece(files, folder, 'reel', metadata, evidence))
    for entry in manifest['stories']:
        folder = _relative(entry['path'])
        if not folder.startswith('STORIES/') or folder + '/series_manifest.json' not in files:
            _fail('Story series manifest missing/outside STORIES')
        series = _json(files[folder + '/series_manifest.json'], folder + '/series_manifest.json')
        sid = series.get('series_id')
        if not isinstance(sid, str) or not sid or sid in series_ids:
            _fail('Missing/duplicate series ID')
        series_ids.add(sid)
        parts = series.get('parts')
        if not isinstance(parts, list) or not parts:
            _fail('Empty story series')
        for order, part in enumerate(parts, 1):
            relative = _relative(part.get('path'))
            pieces.append(_piece(files, folder + '/' + relative, 'story', metadata, evidence, sid, order))
    if not pieces:
        _fail('CURATOR_READY has no Reels or Stories')
    for piece in pieces:
        if piece['path'] in folders or piece['piece_id'] in identifiers:
            _fail('Duplicate production piece folder/ID')
        folders.add(piece['path']); identifiers.add(piece['piece_id'])
    return manifest, metadata, pieces, evidence_document


def read_production_archive(path):
    """Validate one ZIP without extracting, running models, or changing state."""
    path = _checked_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES + 32 * 1024 ** 2:
        _fail('Archive missing/above compressed-byte limit')
    before = path.stat()
    with zipfile.ZipFile(path) as archive:
        members = _zip_members(archive)
        if sum(name in members for name in ('SECOND_CURATION_MANIFEST.json', 'PROJECT_MANIFEST.json', 'manifest.json')) > 1:
            _fail('Ambiguous production package: multiple format manifests')
        if 'SECOND_CURATION_MANIFEST.json' in members:
            native = True
            files = None
        else:
            native = False
            files = _read_zip_files(archive, members)
    if native:
        from .second_curation_import import read_package
        package = read_package(path)
        metadata = _metadata(_json(package['files']['source/metadata.json'], 'source/metadata.json'))
        _json(package['files']['SECOND_CURATION_MANIFEST.json'], 'SECOND_CURATION_MANIFEST.json')
        _json(package['files']['editorial/candidate_catalog.json'], 'editorial/candidate_catalog.json')
        result = {'format': 'ANALYZER_NATIVE', 'files': package['files'],
                  'manifest': package['manifest'], 'metadata': metadata,
                  'package_sha256': package['package_sha256']}
    else:
        if 'PROJECT_MANIFEST.json' in files:
            manifest, metadata = _dossier(files)
            result = {'format': 'EDITORIAL_HANDOFF', 'manifest': manifest, 'metadata': metadata,
                      'source_package_sha256': manifest['package_sha256']}
        elif 'manifest.json' in files:
            manifest, metadata, pieces, evidence = _curator_ready(files)
            result = {'format': 'CURATOR_READY', 'manifest': manifest, 'metadata': metadata,
                      'pieces': pieces, 'evidence': evidence}
        else:
            _fail('Unrecognized production package format')
        with path.open('rb') as stream:
            result['package_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        result['files'] = files
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        _fail('Archive changed during validation')
    result.update(path=str(path), title=result['manifest'].get('title') or result['metadata'].get('source', {}).get('title'),
                  human_approval=None, publication_ready=False)
    return result


def read_editorial_handoff(path, expected_source_sha256=None, expected_package_sha256=None):
    """Validate the exported PROJECT_MANIFEST directory, without following links."""
    root = _checked_path(path)
    if not root.is_dir():
        _fail('Editorial handoff must be an existing directory')
    paths, total, folded = {}, 0, set()
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in directories:
            _checked_path(Path(directory) / name)
        for name in names:
            file = _checked_path(Path(directory) / name)
            relative = _relative(file.relative_to(root).as_posix())
            if relative.casefold() in folded or Path(relative).suffix.lower() not in _ALLOWED:
                _fail('Duplicate/unsupported handoff path: ' + relative)
            folded.add(relative.casefold())
            size = file.stat().st_size
            total += size
            if len(paths) >= MAX_FILES or total > MAX_BYTES:
                _fail('Editorial handoff exceeds file/byte limits')
            paths[relative] = (file, size)
    files = {}
    for name, (file, size) in paths.items():
        payload = file.read_bytes()
        if len(payload) != size or file.stat().st_size != size:
            _fail('Editorial handoff changed during validation: ' + name)
        files[name] = payload
    manifest, metadata = _dossier(files, expected_source_sha256=expected_source_sha256,
                                  expected_package_sha256=expected_package_sha256)
    return {'format': 'EDITORIAL_HANDOFF', 'files': files, 'manifest': manifest,
            'metadata': metadata, 'title': manifest.get('title'), 'path': str(root),
            'package_sha256': hashlib.sha256(files['PROJECT_MANIFEST.json']).hexdigest(),
            'source_package_sha256': manifest['package_sha256'],
            'human_approval': None, 'publication_ready': False}
