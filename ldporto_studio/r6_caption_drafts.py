"""Source-SRT caption drafts for human review, never verified R57 final captions.

Only use literal ASR cues already present in the source-hashed Analyzer R6 ZIP.
Clip boundaries are explicitly selected Reels and source-duration Story proposals.
Cues are intersected, clipped and rebased to clip-local timestamps without
inventing text or pretending that ASR alignment/audio has been reviewed.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
from zipfile import ZipFile

from .analyzer_inbox import inspect_delivery
from .core import fingerprint, json_bytes, sha256_bytes, sha256_file
from .r6_r57_bridge import prepare_r57_bridge
from .workspace import application_root

VERSION = 'ldporto-r6-caption-drafts-1.0'
SOURCE_MEMBER = 'transcript/transcript.srt'
MAX_SRT_BYTES = 8 * 1024 * 1024
MAX_CUES = 20000
SRT_RANGE = re.compile(
    r'^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*'
    r'(\d{2}):(\d{2}):(\d{2}),(\d{3})(?:\s+.*)?$'
)


def _ms(parts):
    h, m, s, ms = map(int, parts)
    if m > 59 or s > 59:
        raise ValueError('Timestamp SRT inválido')
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _stamp(ms):
    if ms < 0:
        raise ValueError('Timestamp negativo')
    h, remain = divmod(ms, 3600000)
    minute, remain = divmod(remain, 60000)
    sec, milli = divmod(remain, 1000)
    return f'{h:02d}:{minute:02d}:{sec:02d},{milli:03d}'


def _ass_stamp(ms):
    total_cs = (ms + 5) // 10
    hour, rem = divmod(total_cs, 360000)
    minute, rem = divmod(rem, 6000)
    second, cs = divmod(rem, 100)
    return f'{hour}:{minute:02d}:{second:02d}.{cs:02d}'


def parse_original_srt(raw, source_duration_ms):
    if not raw or len(raw) > MAX_SRT_BYTES:
        raise ValueError('SRT original ausente ou fora do limite')
    try:
        text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeDecodeError as exc:
        raise ValueError('SRT original não é UTF-8') from exc
    if '\x00' in text:
        raise ValueError('SRT contém NUL')
    if not text.strip():
        return []
    chunks = re.split(r'\n[ \t]*\n', text.strip())
    if len(chunks) > MAX_CUES:
        raise ValueError('Transcrição excede máximo de legendas')
    parsed = []
    for index, chunk in enumerate(chunks, 1):
        lines = chunk.split('\n')
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2:
            raise ValueError('Bloco SRT incompleto: ' + str(index))
        found = SRT_RANGE.fullmatch(lines[0].strip())
        if not found:
            raise ValueError('Intervalo SRT inválido: ' + str(index))
        start, end = _ms(found.groups()[:4]), _ms(found.groups()[4:])
        if not 0 <= start < end <= source_duration_ms + 1000:
            raise ValueError('Intervalo SRT fora do vídeo: ' + str(index))
        spoken = '\n'.join(lines[1:]).strip()
        if not spoken:
            raise ValueError('Legenda original sem texto: ' + str(index))
        if len(spoken) > 4000:
            raise ValueError('Texto SRT excessivo: ' + str(index))
        parsed.append((start, end, spoken))
    if not parsed:
        raise ValueError('SRT original não contém legendas')
    return parsed


def _render_srt(entries):
    return ('\n\n'.join(
        f'{i}\n{_stamp(start)} --> {_stamp(end)}\n{text}'
        for i, (start, end, text) in enumerate(entries, 1)
    ) + '\n').encode('utf-8')


def _render_ass(entries):
    header = (
        '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
        'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
        'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        'Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,'
        '&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,70,1\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )
    lines = []
    for start, end, spoken in entries:
        literal = (spoken.replace('\\', r'\\')
                   .replace('{', r'\{').replace('}', r'\}')
                   .replace('\n', r'\N'))
        lines.append(
            f'Dialogue: 0,{_ass_stamp(start)},{_ass_stamp(end)},'
            f'Default,,0,0,0,,{literal}\n'
        )
    return (header + ''.join(lines)).encode('utf-8')


def prepare_caption_drafts(inbox, draft, story_proposal):
    """Return real ASR-derived editable captions as bytes; never save by default."""
    bridge = prepare_r57_bridge(inbox, draft, story_proposal_path=story_proposal)
    inspected = inspect_delivery(inbox)
    provenance = bridge['provenance']
    if inspected['zip_sha256'] != provenance['source_zip_sha256']:
        raise ValueError('ZIP R6 alterado desde a seleção')
    source = Path(inspected['package_path'])
    source_duration_ms = round(provenance['source_duration_seconds'] * 1000)
    original = None
    with ZipFile(source) as archive:
        if SOURCE_MEMBER in archive.namelist():
            manifest = json.loads(archive.read('SECOND_CURATION_MANIFEST.json'))
            declared = {r['path']:r for r in manifest.get('files', [])
                        if isinstance(r, dict) and isinstance(r.get('path'), str)}
            info = archive.getinfo(SOURCE_MEMBER)
            if not 0 < info.file_size <= MAX_SRT_BYTES:
                raise ValueError('SRT R6 acima do limite')
            entry = declared.get(SOURCE_MEMBER)
            if not isinstance(entry, dict) or entry.get('bytes') != info.file_size:
                raise ValueError('SRT não declarado corretamente no manifesto R6')
            original = archive.read(SOURCE_MEMBER)
            if sha256_bytes(original) != entry.get('sha256'):
                raise ValueError('SRT R6 diverge do manifesto')
    clips = [('reels', c) for c in bridge['r57_reel_slots']]
    clips += [('stories', c) for c in bridge['r57_story_boundary_proposals']]
    captions = []
    files = {}
    source_srt_sha = sha256_bytes(original) if original is not None else None
    cues = parse_original_srt(original, source_duration_ms) if original is not None else []
    for kind, row in clips:
        start_ms = round(row['source_start'] * 1000)
        end_ms = round(row['source_end'] * 1000)
        if start_ms < 0 or end_ms <= start_ms or end_ms > source_duration_ms + 3:
            raise ValueError('Corte fora dos limites originais')
        entries = []
        partial = 0
        for a, b, text in cues:
            left, right = max(a, start_ms), min(b, end_ms)
            if left >= right:
                continue
            if left != a or right != b:
                partial += 1
            entries.append((left - start_ms, right - start_ms, text))
        prefix = kind + '/' + row['id']
        status = ('ASR_DRAFT_WITH_CUES_REVIEW_REQUIRED' if entries
                  else 'NO_ORIGINAL_ASR_CUES_FOR_CLIP')
        if entries:
            files[prefix + '/captions_unverified.srt'] = _render_srt(entries)
            files[prefix + '/captions_unverified.ass'] = _render_ass(entries)
        captions.append({
            'id': row['id'], 'kind': kind, 'start': row['source_start'],
            'end': row['source_end'], 'status': status,
            'cue_count': len(entries), 'boundary_clipped_cues': partial,
            'has_caption_draft': bool(entries),
            'source_asr_sha256': source_srt_sha,
            'caption_alignment_verified': False, 'human_approved': False,
            'requires_manual_audio_and_text_review': True,
        })
    if sha256_file(source) != inspected['zip_sha256']:
        raise ValueError('ZIP original alterado durante leitura das legendas')
    report = {
        'schema_version': VERSION,
        'status': ('DRAFT_ASR_NEEDS_HUMAN_REVIEW' if cues else
                   'SOURCE_SRT_EMPTY_OR_NO_CUES' if original is not None else
                   'SOURCE_SRT_NOT_PRESENT'),
        'source': dict(provenance),
        'original_srt_member': SOURCE_MEMBER,
        'original_srt_sha256': source_srt_sha,
        'original_cue_count': len(cues),
        'clips': captions,
        'clips_total': len(captions),
        'clips_with_draft': sum(x['has_caption_draft'] for x in captions),
        'clips_without_cues': sum(not x['has_caption_draft'] for x in captions),
        'output_files': [
            {'path': name, 'sha256': sha256_bytes(data), 'bytes': len(data)}
            for name, data in sorted(files.items())
        ],
        'source_preserved': True, 'ASR_corrected': False,
        'captions_verified': False, 'r57_import_ready': False,
        'human_approved': False, 'publication_ready': False,
    }
    return files, report


def export_caption_drafts(inbox, draft, story_proposal, destination_root=None):
    """Explicit, idempotent save of unverified ASR clip drafts, never empty captions."""
    files, report = prepare_caption_drafts(inbox, draft, story_proposal)
    if not files:
        raise ValueError('Nenhuma legenda SRT de origem sobreposta aos cortes')
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    input_dir = Path(inbox).expanduser().resolve()
    if root == input_dir or root.is_relative_to(input_dir) or input_dir.is_relative_to(root):
        raise ValueError('Destino sobrepõe entrada R6')
    folder = root / report['source']['source_sha256'][:16] / (
        'CAPTIONS_R6_DRAFT_' + fingerprint(report)[:20])
    def check_existing():
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError('Pasta anterior de legendas inválida')
        manifest_file = folder / 'CAPTION_DRAFT_MANIFEST.json'
        if not manifest_file.is_file() or manifest_file.is_symlink():
            raise ValueError('Manifesto anterior ausente ou inseguro')
        if json.loads(manifest_file.read_text(encoding='utf-8')) != report:
            raise ValueError('Manifesto anterior diverge')
        expected = {'CAPTION_DRAFT_MANIFEST.json'} | set(files)
        descendants = list(folder.rglob('*'))
        if any(p.is_symlink() or (
                getattr(p.lstat(), 'st_file_attributes', 0) &
                getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
        ) for p in descendants):
            raise ValueError('Link/junction inesperado na saída de legendas')
        actual = {p.relative_to(folder).as_posix()
                  for p in descendants if p.is_file()}
        if actual != expected:
            raise ValueError('Arquivos da pasta anterior divergentes')
        for name, data in files.items():
            current = folder / name
            if (current.is_symlink() or not current.is_file()
                    or sha256_file(current) != sha256_bytes(data)):
                raise ValueError('Legenda previamente salva foi modificada: ' + name)
        return folder
    if folder.exists():
        return check_existing()
    folder.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.asr-draft-', dir=folder.parent))
    published = False
    try:
        for name, data in files.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (stage / 'CAPTION_DRAFT_MANIFEST.json').write_bytes(json_bytes(report))
        if folder.exists():
            return check_existing()
        stage.rename(folder)
        published = True
        return check_existing()
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
