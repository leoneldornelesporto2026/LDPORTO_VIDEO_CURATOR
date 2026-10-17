"""Searchable review PDF from persisted evidence, without inference or approval.

Uses the PDF standard fonts and embeds verified JPEG evidence unchanged. Other
images stay explicit file/hash references. Existing PDFs are never overwritten.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import textwrap
from uuid import uuid4

_REPOSITORY = Path(__file__).resolve().parent.parent
_MAX_IMAGE_BYTES = 25 * 1024 ** 2
_MAX_EMBEDDED_BYTES = 48 * 1024 ** 2
_MAX_IMAGES = 12


def _external_path(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.exists():
            mode = parent.lstat()
            if parent.is_symlink() or getattr(mode, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                raise ValueError('Dossier destination cannot contain links/junctions')
    path = path.resolve()
    if path.is_relative_to(_REPOSITORY):
        raise ValueError('Production dossier must be written outside the repository')
    return path


def _time(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return 'not declared'
    hours, seconds = divmod(max(0., value), 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{int(hours):02}:{int(minutes):02}:{seconds:06.3f}'


def _value(value):
    if value is None or value == '':
        return 'not declared'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return str(value)


def _camera_lines(piece):
    camera = piece.get('camera_plan') or {}
    rows = camera.get('segments') or []
    if not rows:
        return ['Camera plan: ' + _value(camera.get('mode')) + ' (no declared intervals)']
    result = ['Camera plan: clip-relative seconds; proposed geometry, not an approved render.']
    for row in rows:
        details = []
        for key in ('center_x', 'center_y', 'center_x_start', 'center_x_end', 'center_y_start',
                    'center_y_end', 'zoom', 'zoom_start', 'zoom_end', 'zoom_transition_start',
                    'zoom_transition_duration', 'split_centers_x', 'reason', 'decision_id'):
            if key in row:
                details.append(key + '=' + _value(row[key]))
        result.append(f"  {_time(row.get('start'))} - {_time(row.get('end'))}: "
                      + _value(row.get('mode')) + '; ' + '; '.join(details))
    return result


def _document_lines(plan, evidence):
    imported = plan.get('production_import') or {}
    summary = imported.get('summary') or {}
    metadata = imported.get('source_metadata') or evidence.get('source') or {}
    source = evidence.get('source') or {}
    media = imported.get('media_reference') or {}
    pieces = [*plan.get('episodes', []), *plan.get('extras', [])]
    lines = ['L.D.PORTO VIDEO CURATOR - DOSSIE SEGUNDA CURADORIA',
        'Persisted proposals and source evidence. Human review remains required.',
        'No new inference, audio validation, visual inspection or approval is claimed by this export.',
        '', 'IDENTITY AND PROVENANCE',
        'Title: ' + _value(summary.get('title') or metadata.get('title') or source.get('title')),
        'Video ID (declared): ' + _value(summary.get('declared_video_id') or metadata.get('video_id') or source.get('id')),
        'Source SHA256: ' + _value(plan.get('source_sha256') or metadata.get('sha256') or source.get('sha256')),
        'Package SHA256: ' + _value(imported.get('package_sha256')),
        'Revision: ' + _value(imported.get('revision_id') or plan.get('plan_id')),
        'Input format: ' + _value(imported.get('format')),
        'Media association: ' + _value(media.get('state')),
        'Original media path (reference only): ' + _value(media.get('path')),
        f"Source technical data: duration={_value(metadata.get('duration'))} s; "
        f"{_value(metadata.get('width'))}x{_value(metadata.get('height'))}; fps={_value(metadata.get('fps'))}",
        'Approval state: ' + _value(summary.get('approval_state') or 'HUMAN_REVIEW_REQUIRED'),
        'Counts: ' + _value(summary.get('counts') or {'pieces': len(pieces)}),
        'Caption states: ' + _value(summary.get('caption_states')),
        'Visual evidence summary: ' + _value(summary.get('visual')),
        'Evidence availability: ' + _value(evidence.get('availability')),
        'Provenance: ' + _value(evidence.get('provenance')), '', 'CANDIDATES / PIECES']
    segments = evidence.get('segments') or []
    for number, piece in enumerate(pieces, 1):
        start, end = piece.get('source_start'), piece.get('source_end')
        lines.extend(['', f"{number}. {_value(piece.get('episode_id'))} | {_value(piece.get('piece_kind'))}",
            'Origin/candidate: ' + _value(piece.get('production_origin_id') or piece.get('candidate_id')),
            'Series/order: ' + _value(piece.get('series_id')) + ' / ' + _value(piece.get('order')),
            f'Source window: {_time(start)} - {_time(end)}; duration={_value(piece.get("duration"))} s',
            'Source intervals: ' + _value(piece.get('source_intervals')),
            'Title (literal proposal): ' + _value(piece.get('title_text') or piece.get('title') or piece.get('internal_title')),
            'Caption gate: ' + _value(piece.get('production_caption_gate') or piece.get('caption_preflight')),
            'Review flags: ' + _value(piece.get('risk_flags') or []),
            'Audio plan: ' + _value(piece.get('audio') or piece.get('audio_plan')),
            'Human approval record: ' + ('present in loaded state; not granted by this document' if piece.get('human_approval') else 'absent'),
            *_camera_lines(piece),
            'Literal source transcript (unmodified text; source segment boundaries may exceed this cut):'])
        matches = [row for row in segments if isinstance(start, (int, float)) and isinstance(end, (int, float))
                   and row.get('start', end) < end and row.get('end', start) > start]
        if not matches:
            lines.append('  No supplied source transcript for this interval. No speech invented.')
        for row in matches:
            lines.extend(['  ' + _value(row.get('segment_id')) + ' [' + _time(row.get('start'))
                          + ' - ' + _time(row.get('end')) + ']', '  ' + _value(row.get('text'))])
    return lines


def _jpeg_size(payload):
    if not payload.startswith(b'\xff\xd8'):
        return None
    position = 2
    while position + 4 <= len(payload):
        if payload[position] != 0xff:
            return None
        while position < len(payload) and payload[position] == 0xff:
            position += 1
        if position >= len(payload):
            return None
        marker = payload[position]; position += 1
        if marker in {0xd8, 0xd9} or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(payload[position:position + 2], 'big')
        if length < 2 or position + length > len(payload):
            return None
        if marker in {0xc0, 0xc1, 0xc2}:
            if length < 8:
                return None
            precision, height, width, components = struct.unpack('>BHHB', payload[position + 2:position + 8])
            if precision == 8 and components in {1, 3} and 0 < width * height <= 100_000_000:
                return width, height, components
            return None
        if marker == 0xda:
            return None
        position += length
    return None


def _visual_evidence(project, directory):
    index = project._visual_index() if hasattr(project, '_visual_index') else {}
    assets, frames = index.get('assets') or {}, index.get('frames') or []
    lines = ['', 'REAL VISUAL EVIDENCE REFERENCES',
        'File hashes and timestamps identify supplied evidence; they do not establish continuous scene verification.',
        'Contact sheets remain contact sheets, not individually decoded source frames.',
        'Frames declared: ' + str(len(frames)) + '; image assets declared: ' + str(len(assets))]
    for row in frames:
        lines.append('Frame: ' + _value(row.get('frame_sample_id') or row.get('frame_id'))
            + '; source=' + _time(row.get('time', row.get('timestamp')))
            + '; kind=' + _value(row.get('asset_kind'))
            + '; refs=' + _value(row.get('asset_refs') or row.get('asset_paths') or row.get('path')))
    images, total = [], 0
    for name, asset in sorted(assets.items()):
        declared = asset.get('path')
        lines.append('Asset: ' + name + '; SHA256=' + _value(asset.get('sha256'))
                     + '; bytes=' + _value(asset.get('bytes')) + '; path=' + _value(declared))
        if not declared:
            lines.append('  Not embedded: original file path not available in persisted index.')
            continue
        target = _external_path(declared)
        if not target.is_relative_to(directory):
            raise ValueError('Dossier image reference must stay inside the external project')
        if not target.is_file():
            lines.append('  Not embedded: declared file is currently missing.')
            continue
        size = target.stat().st_size
        if size > _MAX_IMAGE_BYTES:
            lines.append('  Not embedded: image byte limit exceeded.')
            continue
        payload = target.read_bytes()
        if len(payload) != asset.get('bytes') or hashlib.sha256(payload).hexdigest() != asset.get('sha256'):
            raise ValueError('Dossier image no longer matches verified evidence: ' + name)
        dimensions = _jpeg_size(payload)
        if not dimensions or len(images) >= _MAX_IMAGES or total + len(payload) > _MAX_EMBEDDED_BYTES:
            lines.append('  Verified file/hash reference only; not embedded (format or overview limit).')
            continue
        total += len(payload)
        images.append((name, asset['sha256'], payload, dimensions))
    return lines, images, len(frames), len(assets)


def _pdf(lines, images):
    """Minimal standard-font PDF; streams stay uncompressed and searchable."""
    replacements = 0
    encoded_lines = []
    for line in lines:
        clean = ''.join(c if ord(c) >= 32 or c == '\t' else ' ' for c in str(line)).replace('\t', '    ')
        replacements += sum(1 for c in clean if not _encodable(c))
        encoded_lines.extend(textwrap.wrap(clean, 98, replace_whitespace=False, drop_whitespace=False) or [''])
    if replacements:
        encoded_lines.extend(['', f'Encoding limitation: {replacements} unsupported characters replaced with ? in this PDF.',
            'UTF-8 source JSON remains authoritative for exact Unicode transcription.'])
    objects = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    pages = []
    def add(payload):
        objects.append(payload)
        return len(objects)
    def stream(payload, dictionary=''):
        return (f'<< {dictionary} /Length {len(payload)} >>\nstream\n'.encode() + payload + b'\nendstream')
    def literal(value):
        return value.encode('cp1252', errors='replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
    chunks = [encoded_lines[i:i + 58] for i in range(0, len(encoded_lines), 58)]
    for i, chunk in enumerate(chunks, 1):
        commands = [b'BT /F1 9 Tf 12 TL 40 800 Td']
        for line in chunk:
            commands.append(b'(' + literal(line) + b') Tj T*')
        commands.extend([b'ET', f'BT /F1 8 Tf 40 25 Td (Text page {i}) Tj ET'.encode()])
        content = add(stream(b'\n'.join(commands)))
        pages.append(add(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>'.encode()))
    for name, sha, payload, (width, height, components) in images:
        image = add(stream(payload, f'/Type /XObject /Subtype /Image /Width {width} /Height {height} '
                           + f'/ColorSpace /Device{"RGB" if components == 3 else "Gray"} /BitsPerComponent 8 /Filter /DCTDecode'))
        scale = min(515 / width, 650 / height)
        w, h = width * scale, height * scale
        title = literal('Real supplied image: ' + name)
        content = add(stream(b'BT /F1 9 Tf 40 804 Td (' + title + b') Tj ET\n'
            + b'BT /F1 8 Tf 40 787 Td (SHA256: ' + sha.encode() + b') Tj ET\n'
            + b'BT /F1 8 Tf 40 770 Td (Overview evidence; no visual conclusion is asserted.) Tj ET\n'
            + f'q {w:.4f} 0 0 {h:.4f} 40 {750 - h:.4f} cm /Im1 Do Q'.encode()))
        pages.append(add(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> /XObject << /Im1 {image} 0 R >> >> /Contents {content} 0 R >>'.encode()))
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(pages)} /Kids ['.encode() + b' '.join(f'{p} 0 R'.encode() for p in pages) + b'] >>'
    result = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for i, payload in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f'{i} 0 obj\n'.encode() + payload + b'\nendobj\n')
    start = len(result)
    result.extend(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(result), replacements, len(pages)


def _encodable(character):
    try:
        character.encode('cp1252')
        return True
    except UnicodeEncodeError:
        return False


def export_production_dossier(project):
    """Export one immutable external PDF; never render, save or approve a piece.

    Returns path, SHA256, bytes, page/image counts and explicit encoding limits.
    Repeating the same export reuses identical bytes; a changed plan creates a
    separately named PDF while preserving all earlier reports.
    """
    directory = _external_path(project.directory)
    if not directory.is_dir():
        raise ValueError('External production project directory is missing')
    plan, evidence = deepcopy(project.plan), deepcopy(project.evidence)
    visual_lines, images, frame_count, asset_count = _visual_evidence(project, directory)
    payload, replacements, pages = _pdf(_document_lines(plan, evidence) + visual_lines, images)
    if project.plan != plan or project.evidence != evidence:
        raise ValueError('Project changed while preparing dossier; retry with current revision')
    digest = hashlib.sha256(payload).hexdigest()
    folder = _external_path(directory / '04_RELATORIOS')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('DOSSIE_SEGUNDA_CURADORIA_' + digest[:20] + '.pdf')
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing dossier filename has different bytes; no overwrite performed')
    else:
        pending = folder / ('.dossier_' + uuid4().hex + '.pending')
        with pending.open('xb') as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(pending, target)
        except FileExistsError:
            if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError('Concurrent dossier publication differs; pending preserved')
        pending.unlink()
    return {'path': str(target), 'sha256': digest, 'bytes': len(payload), 'format': 'PDF',
            'searchable': True, 'pages': pages, 'encoding': 'WinAnsiEncoding/Helvetica',
            'unicode_replacements': replacements, 'source_json_is_unicode_authority': True,
            'frames_referenced': frame_count, 'assets_referenced': asset_count,
            'images_embedded': len(images), 'new_inference_executed': False,
            'automatic_approval': False}
