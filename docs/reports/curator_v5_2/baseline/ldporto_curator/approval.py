"""Approval binds the reviewed preview to its current edit plan."""
import hashlib
import json
from pathlib import Path
from .utils import load_json, write_json


def file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def plan_signature(decisions, cfg, reviewed_clip_id=None):
    rows = [{k: row.get(k) for k in ('clip_id', 'source_start', 'source_end', 'title_text', 'title_style', 'curation_source')} for row in decisions]
    for row, original in zip(rows, decisions):
        if reviewed_clip_id is None or original['clip_id'] == reviewed_clip_id:
            row['camera_plan'] = original.get('camera_plan')
            row['subtitle_plan'] = original.get('subtitle_plan')
    settings = {k: cfg.get(k) for k in ('render', 'subtitles', 'title', 'output', 'camera', 'camera_v44', 'micro_perception')}
    settings['subtitle_renderer_fingerprint'] = file_hash(Path(__file__).with_name('subtitles.py'))
    settings['title_renderer_fingerprint'] = file_hash(Path(__file__).with_name('title_card.py'))
    settings['renderer_fingerprint'] = file_hash(Path(__file__).with_name('render.py'))
    return hashlib.sha256(json.dumps({'clips': rows, 'settings': settings}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_preview(folder, path, signature, reviewed_clip_id=None):
    path = Path(path).resolve()
    write_json(Path(folder) / 'PREVIEW_REVIEW_V44.json', {'plan_signature': signature, 'path': str(path), 'sha256': file_hash(path), 'reviewed_clip_id': reviewed_clip_id})


def approve_preview(folder, signature):
    folder = Path(folder)
    record = load_json(folder / 'PREVIEW_REVIEW_V44.json', {}) or {}
    if record.get('plan_signature') != signature or not Path(record.get('path', '')).is_file():
        raise ValueError('Gere e revise o preview do plano atual antes de aprovar')
    if file_hash(record['path']) != record.get('sha256'):
        raise ValueError('Preview mudou após a validação; gere um novo teste')
    write_json(folder / 'FIRST_TEST_APPROVED_V44.json', record)
    (folder / 'FIRST_TEST_APPROVED.flag').write_text('approved\n', encoding='utf-8')


def approval_matches(folder, signature):
    record = load_json(Path(folder) / 'FIRST_TEST_APPROVED_V44.json', {}) or {}
    return bool(record.get('plan_signature') == signature and Path(record.get('path', '')).is_file()
                and file_hash(record['path']) == record.get('sha256'))
