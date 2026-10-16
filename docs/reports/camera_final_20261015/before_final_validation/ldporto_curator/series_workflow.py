"""Local, resumable V5 project workflow. No models, downloads or Analyzer writes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
from types import SimpleNamespace
from uuid import uuid4

from .approval import file_hash
from .episode_approval import (episode_signature, record_episode_preview,
    approve_episode_preview, episode_approval_matches, renderer_fingerprint)
from .utils import load_json, write_json, safe_name, run


class OperationCancelled(RuntimeError):
    pass


def _canonical_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _transcript_fingerprint(evidence, episode):
    start, end = episode['source_start'], episode['source_end']
    rows = {}
    for key in ('segments', 'captions', 'words'):
        rows[key] = [row for row in evidence.get(key, [])
                     if float(row.get('end', row.get('source_end', 0))) > start
                     and float(row.get('start', row.get('source_start', 0))) < end]
    return _canonical_hash({'source_sha256': evidence.get('source', {}).get('sha256'),
                            'provenance': evidence.get('provenance', {}), 'transcript': rows})


def _caption_editorial_inputs(episode):
    runtime = {'state', 'status', 'preview', 'final', 'approval', 'human_approval',
        'history', 'approval_history', 'artifact_history', 'caption_revision', 'caption_timeline',
        'preview_duration', 'rendered_duration', 'duration_rendered', 'render_validation',
        'duration_verified_by_ffprobe', 'encoding_tolerance_seconds', 'plan_hash'}
    return {key: value for key, value in episode.items() if key not in runtime}


def _inside_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError('Arquivo congelado ausente ou fora do projeto: ' + str(relative))
    return path


def _validate_episode_window(episode):
    values = [episode.get(key) for key in ('source_start', 'source_end', 'duration')]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError('Janela e duração do episódio devem ser finitas')
    start, end, duration = values
    if start < 0 or end <= start or abs((end - start) - duration) > 1e-7:
        raise ValueError('Duração diverge da janela original congelada')
    is_story = str(episode.get('duration_preset', '')).startswith('story') or episode.get('duration_max_seconds') == 60
    if is_story and duration > 60:
        raise ValueError('Story excede 60 segundos; revise os limites sem cortar a fala automaticamente')


def _verified_supplemental_words(manifest_path, evidence):
    """Read existing, source-linked word records for entirely missing segments.

    This is evidence recovery, never ASR, inference or timestamp interpolation.
    Every declared file is rehashed before its selected records are accepted.
    """
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path, {})
    expected_source = evidence.get('source', {}).get('sha256')
    if (manifest.get('schema') != 'LDP_SUPPLEMENTAL_WORD_EVIDENCE_V1'
            or manifest.get('source_sha256') != expected_source):
        raise ValueError('Manifesto de palavras suplementares incompatível com o SHA256 da fonte')
    documents, references = {}, {}
    for name in ('word_file', 'transcript_segments_file', 'source_manifest_file', 'source_identity_file'):
        reference = manifest.get(name) or {}
        candidate = Path(reference.get('path', ''))
        if not candidate.is_absolute():
            candidate = manifest_path.parent / candidate
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError('Arquivo de evidência suplementar ausente ou link: ' + name)
        path = candidate.resolve()
        digest = file_hash(path)
        if digest != reference.get('sha256'):
            raise ValueError('SHA256 da evidência suplementar diverge: ' + name)
        document = load_json(path)
        if document is None:
            raise ValueError('JSON de evidência suplementar inválido: ' + name)
        documents[name] = document
        references[name] = {'path': str(path), 'sha256': digest}
    if documents['source_manifest_file'].get('video_sha256') != expected_source:
        raise ValueError('Manifesto do Analyzer pertence a outra fonte')
    cache = documents['source_identity_file']
    if cache.get('source_hash') != expected_source:
        raise ValueError('Cache ASR pertence a outra fonte SHA256')
    if not {'words.json', 'transcript_segments.json'} <= set(documents['source_manifest_file'].get('files', [])):
        raise ValueError('Manifesto do Analyzer não declara as evidências de palavras/segmentos')
    raw = (cache.get('data') or {}).get('words')
    original_words, original_segments = documents['word_file'], documents['transcript_segments_file']
    if not all(isinstance(rows, list) for rows in (raw, original_words, original_segments)):
        raise ValueError('Contrato de palavras suplementares inválido')
    segment_ids = manifest.get('segment_ids')
    if (not isinstance(segment_ids, list) or not segment_ids
            or len(segment_ids) != len(set(segment_ids)) or not all(isinstance(sid, str) for sid in segment_ids)):
        raise ValueError('Segmentos suplementares inválidos')
    current_segments = evidence.get('segments') or evidence.get('captions') or []
    existing = evidence.get('words') or []
    existing_ids = {row.get('word_id') for row in existing}
    selected = []
    from .subtitle_presets import _align_words
    for sid in segment_ids:
        targets = [row for row in current_segments if row.get('segment_id', row.get('id')) == sid]
        origins = [row for row in original_segments if row.get('segment_id', row.get('id')) == sid]
        if len(targets) != 1 or len(origins) != 1:
            raise ValueError('Segmento suplementar ausente ou ambíguo: ' + sid)
        target, origin = targets[0], origins[0]
        if any(target.get(key) != origin.get(key) for key in ('start', 'end', 'text')):
            raise ValueError('Texto ou janela do segmento suplementar diverge do original: ' + sid)
        if target.get('words') or any(row.get('segment_id') == sid or
            (float(row.get('end', 0)) > target['start'] and float(row.get('start', 0)) < target['end'])
            for row in existing):
            raise ValueError('Suplementação permitida somente para segmento sem palavras: ' + sid)
        words = [row for row in original_words if row.get('segment_id') == sid]
        words.sort(key=lambda row: (row.get('start', 0), row.get('end', 0)))
        ids = [row.get('word_id') for row in words]
        if not words or ids != origin.get('word_ids') or len(ids) != len(set(ids)) or set(ids) & existing_ids:
            raise ValueError('IDs suplementares não correspondem ao segmento original: ' + sid)
        aligned, reason = _align_words(target, words)
        if reason or len(aligned) != len(words):
            raise ValueError('Alinhamento suplementar incompleto/inconsistente: ' + sid)
        def raw_key(row):
            return (row.get('word', row.get('text')), row.get('start'), row.get('end'), row.get('hypothesis_id'))
        for word in words:
            if sum(raw_key(row) == raw_key(word) for row in raw) != 1:
                raise ValueError('Palavra suplementar sem correspondência exata no cache ASR: ' + str(word.get('word_id')))
        selected.extend(deepcopy(words))
        existing_ids.update(ids)
    audit = {'schema': 'LDP_SUPPLEMENTAL_WORD_EVIDENCE_AUDIT_V1',
        'manifest': {'path': str(manifest_path), 'sha256': file_hash(manifest_path)},
        'source_sha256': expected_source, 'segment_ids': segment_ids, 'files': references,
        'added_word_ids': [word['word_id'] for word in selected], 'new_asr_executed': False,
        'literal_transcript_modified': False, 'timestamps_invented': False,
        'audio_review_status': 'NEEDS_HUMAN_AUDIO_REVIEW'}
    return selected, audit


def conservative_camera(evidence, episode, cfg):
    """Reuse V4 geometry; speculative active-speaker and critical visuals never crop."""
    duration = episode['source_end'] - episode['source_start']
    fallback = {'mode': 'full_frame_blur', 'visual_source': 'fallback',
        'requested_mode': episode.get('camera_mode', 'SOURCE_PRESERVE'),
        'reason': 'Preservar composição original; foco seguro não comprovado',
        'speaker_identity': 'unverified', 'crop_safe': False,
        'segments': [{'start': 0.0, 'end': duration, 'mode': 'full_frame_blur',
                      'confidence_source': 'fallback'}]}
    requested = episode.get('camera_mode', 'SOURCE_PRESERVE')
    requested = {'source_preserve': 'SOURCE_PRESERVE'}.get(requested, requested)
    if requested == 'SOURCE_PRESERVE':
        return fallback
    if requested not in {'AUTO_CONSERVADOR', 'FOCO_PESSOA', 'DOIS_PARTICIPANTES', 'MANUAL_KEYFRAMES'}:
        raise ValueError('Modo de câmera desconhecido')
    rows = [r for r in evidence.get('timeline', []) if r.get('end', 0) > episode['source_start']
            and r.get('start', math.inf) < episode['source_end']]
    visual_rows = rows + [r for r in evidence.get('scenes', []) if r.get('end', 0) > episode['source_start']
                          and r.get('start', math.inf) < episode['source_end']]
    visual_rows += [r for r in evidence.get('frame_samples', []) if episode['source_start'] <= r.get('time',r.get('timestamp',math.inf)) <= episode['source_end']]
    sensitive = ('map', 'mapa', 'cockpit', 'instrument', 'diagram', 'grafico', 'gráfico', 'slide', 'screen', 'tela', 'ocr')
    risk = any(row.get('crop_risk') in {'high','critical'} or row.get('critical_content') is True or
               row.get('critical_text') is True for row in visual_rows)
    risk = risk or 'critical_visuals_need_source_preservation' in episode.get('risk_flags', [])
    if risk or any(any(token in str(row).casefold() for token in sensitive) for row in visual_rows):
        return {**fallback, 'reason': 'Mapa/texto/tela/instrumentos: preservar fonte para revisão'}
    if requested == 'MANUAL_KEYFRAMES':
        points = episode.get('camera_keyframes') or []
        if not points:
            return {**fallback, 'reason': 'Nenhum keyframe manual fornecido'}
        segments = []
        for i, point in enumerate(points):
            t, x, y, zoom = (float(point.get(k, v)) for k, v in
                             [('time', 0), ('x', .5), ('y', .5), ('zoom', 1)])
            if not all(math.isfinite(v) for v in (t, x, y, zoom)) or not (0 <= t < duration and 0 <= x <= 1 and 0 <= y <= 1 and 1 <= zoom <= 1.13):
                raise ValueError('Keyframe fora dos limites físicos')
            if i and t <= float(points[i-1]['time']):
                raise ValueError('Keyframes devem seguir ordem temporal')
            following = points[i+1] if i+1 < len(points) else point
            end = float(following['time']) if i+1 < len(points) else duration
            dt = max(.001, end-t)
            x1, y1 = float(following.get('x', x)), float(following.get('y', y))
            if abs(x1-x)/dt > .18 or abs(y1-y)/dt > .12:
                raise ValueError('Movimento manual excede velocidade segura')
            segments.append({'start': t if i else 0, 'end': end, 'mode': 'crop',
                'motion_follow': True, 'motion_easing': 'smoothstep', 'zoom': zoom,
                'center_x_start': x, 'center_x_end': x1, 'center_y_start': y,
                'center_y_end': y1, 'subject_screen_y': .5, 'confidence_source': 'manual'})
        return {'mode': 'adaptive_timeline', 'segments': segments, 'visual_source': 'manual',
                'crop_safe': 'needs_human_review', 'requested_mode': requested}
    # Coarse face labels are insufficient. Require interval coverage and safe geometry.
    cursor = episode['source_start']
    for row in sorted(rows, key=lambda r: r.get('start', 0)):
        positions = row.get('people_positions') or []
        if row['start'] > cursor + .1 or not positions or not all(p.get('safe_crop_possible') is True for p in positions):
            return fallback
        cursor = max(cursor, row['end'])
    if not rows or cursor < episode['source_end']-.1:
        return fallback
    from .camera import build_camera_plan
    bundle = SimpleNamespace(**{key: evidence.get(key, []) for key in
        ('timeline', 'scenes', 'people_observations', 'frame_samples', 'speaker_person_mapping',
         'questions_answers', 'captions', 'segments', 'words', 'director')})
    settings = deepcopy(cfg)
    settings.setdefault('camera', {}).update({'question_focus_heuristic': False, 'speaker_aware': True})
    result = build_camera_plan(bundle, episode, settings)
    for segment in result.get('segments', []):
        if segment.get('mode') == 'crop' and not segment.get('speaker_evidence'):
            # Single observed face is allowed as a visual focus, never as a named speaker.
            if requested == 'FOCO_PESSOA' or segment.get('reason') not in {'single_detection', 'single_face'}:
                return fallback
        if requested == 'DOIS_PARTICIPANTES' and segment.get('mode') != 'split_screen':
            return fallback
        segment['confidence_source'] = 'analyzer_geometry'
    result.update({'requested_mode': requested, 'speaker_identity': 'unverified', 'crop_safe': 'needs_human_review'})
    return result


def _encode(cmd, duration, progress, cancel):
    """Read both streams without pipe deadlock; allow safe cancellation of FFmpeg only."""
    from .render import _ffmpeg_progress_fraction
    cmd = [cmd[0], '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats', *cmd[1:]]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    events, errors = queue.Queue(), []
    def read(pipe, is_error):
        for line in pipe:
            if is_error:
                errors.append(line)
            else:
                events.put(line)
        events.put(None if not is_error else '')
    threads = [threading.Thread(target=read, args=(process.stdout, False), daemon=True),
               threading.Thread(target=read, args=(process.stderr, True), daemon=True)]
    for thread in threads:
        thread.start()
    try:
        while process.poll() is None:
            if cancel and cancel.is_set():
                process.terminate()
                process.wait(timeout=10)
                raise OperationCancelled('Operação cancelada; artefatos concluídos preservados')
            try:
                line = events.get(timeout=.2)
            except queue.Empty:
                continue
            if line and line.startswith('out_time_us='):
                value = _ffmpeg_progress_fraction(line.split('=', 1)[1], duration)
                if value is not None:
                    progress(value, 'Encode')
        for thread in threads:
            thread.join(timeout=5)
        return process.returncode, ''.join(errors)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def validate_episode_media(path, width, height, expected_duration):
    from .render import validate_output
    validate_output(Path(path), width, height)
    probe = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]).stdout)
    streams = probe['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    audio = next(s for s in streams if s['codec_type'] == 'audio')
    actual = float(probe['format']['duration'])
    if abs(actual-expected_duration) > .15 or video['codec_name'] != 'h264' or audio['codec_name'] != 'aac':
        raise ValueError('Duração ou codecs do MP4 diferem do plano')
    if abs(float(video.get('start_time', 0))-float(audio.get('start_time', 0))) > .12:
        raise ValueError('Streams A/V desalinhados')
    import cv2
    cap = cv2.VideoCapture(str(path))
    samples = []
    try:
        for fraction in (.1, .5, .9):
            cap.set(cv2.CAP_PROP_POS_MSEC, expected_duration*fraction*1000)
            ok, frame = cap.read()
            if not ok:
                raise ValueError('Frame amostrado não decodificável')
            mean = float(frame.mean())
            if mean < 1:
                raise ValueError('Frame amostrado preto')
            samples.append({'time': expected_duration*fraction, 'mean_brightness': mean, 'decodable': True})
    finally:
        cap.release()
    return {'status': 'validated', 'duration': actual, 'expected_duration': expected_duration,
            'width': width, 'height': height, 'video_codec': video['codec_name'],
            'audio_codec': audio['codec_name'], 'samples': samples,
            'visual_human_review': 'pending', 'audio_human_review': 'pending'}


class SeriesProject:
    def __init__(self, directory, cfg=None, log=print, progress=None, cancel=None):
        self.directory = Path(directory).resolve()
        if (self.directory / 'CAMERA_REVISION_INCOMPLETE.json').exists():
            raise ValueError('Revisão de câmera incompleta preservada; crie outra revisão a partir da origem')
        self.cfg, self.log = deepcopy(cfg or {}), log
        self.progress = progress or (lambda fraction, detail='': None)
        self.cancel = cancel
        self.plan = load_json(self.directory / 'series_index.json', {}) or {}
        self.evidence = load_json(self.directory / 'evidence.json', {}) or {}
        if cfg is None and self.plan.get('caption_revision'):
            self.cfg = deepcopy(self.plan['caption_revision']['render_settings'])

    def derive_camera_revision(self, destination, *, micro_by_episode, episode_ids=None):
        """Create an unapproved camera-only fork from existing visual evidence."""
        from .camera_revision import derive_camera_revision
        return derive_camera_revision(self, destination, micro_by_episode=micro_by_episode,
                                      episode_ids=episode_ids)

    def derive_caption_revision(self, destination, *, episode_ids=None, word_evidence=None,
                                subtitle_preset=None, subtitle_overrides=None, _defer_save=False):
        """Fork frozen captions without changing any file in the parent project.

        IDs, editorial decisions and camera plans are copied literally. Historical
        media stays in the parent; titles and thumbnail assets are copied by hash.
        Optional caption styling is validated and applied only to the selected
        copies before their inputs are frozen. Replacing a preset also replaces
        its old overrides; overrides alone amend the existing selected style.
        No transcription, curation, model call, encode or approval runs here.
        """
        destination = Path(destination).resolve()
        if destination.exists() or destination.is_relative_to(self.directory):
            raise ValueError('A revisão derivada exige uma nova pasta fora do projeto original')
        parent_index = _inside_file(self.directory, 'series_index.json')
        if load_json(parent_index) != self.plan:
            raise ValueError('Plano em memória diverge da revisão persistida; recarregue o projeto')
        selected = set(episode_ids) if episode_ids is not None else {e['episode_id'] for e in self.episodes()}
        known = {e['episode_id'] for e in self.episodes()}
        if not selected or not selected <= known:
            raise ValueError('Seleção de episódios inválida para revisão de legendas')
        styles = {}
        if subtitle_preset is not None or subtitle_overrides is not None:
            from .subtitle_presets import resolve_subtitle_preset
            for episode in self.episodes():
                if episode['episode_id'] not in selected:
                    continue
                preset = deepcopy(subtitle_preset if subtitle_preset is not None
                                  else episode.get('subtitle_preset', 'LDP_CLEAN'))
                overrides = ({} if subtitle_preset is not None
                             else deepcopy(episode.get('subtitle_overrides') or {}))
                overrides.update(deepcopy(subtitle_overrides or {}))
                styles[episode['episode_id']] = {'preset': preset, 'overrides': overrides,
                    'resolved': resolve_subtitle_preset(preset, overrides)}
        parent_files = {name: file_hash(_inside_file(self.directory, name))
                        for name in ('series_index.json', 'evidence.json', 'source_manifest.json')}
        evidence_disk = load_json(self.directory / 'evidence.json')
        if evidence_disk != self.evidence or self.plan.get('source_sha256') != self.evidence['source']['sha256']:
            raise ValueError('Evidência ou identidade SHA256 diverge do plano persistido')
        supplemental, enrichment = _verified_supplemental_words(word_evidence, self.evidence) if word_evidence else ([], None)
        assets = {}
        for episode in self.episodes():
            if episode['episode_id'] not in selected:
                continue
            _validate_episode_window(episode)
            if not episode.get('camera_plan'):
                raise ValueError('A revisão de legendas exige o plano de câmera já congelado')
            preview = episode.get('preview') or {}
            if not preview.get('review_folder'):
                raise ValueError('A revisão derivada exige uma prévia anterior com assets verificáveis')
            review = _inside_file(self.directory, Path(preview['review_folder']) / 'PREVIEW_REVIEW_V5.json')
            record = load_json(review, {})
            if record.get('sha256') != preview.get('sha256') or record.get('plan_signature') != preview.get('plan_hash'):
                raise ValueError('Registro da prévia histórica diverge do plano')
            source_folder = review.parent
            historical_media = _inside_file(source_folder, record.get('path', ''))
            if file_hash(historical_media) != record.get('sha256'):
                raise ValueError('SHA256 do MP4 histórico diverge do registro; original preservado')
            approved_assets = {row['path']: row['sha256'] for row in record.get('assets', [])}
            frozen = []
            files = [path for path in source_folder.rglob('*') if path.is_file()
                     and (path.relative_to(source_folder).parts[0] == 'thumbnails'
                          or path.name in {'title_card_preview.png', 'TITLE_LAYOUT.json'})]
            for path in sorted(files):
                relative = path.relative_to(source_folder).as_posix()
                digest = file_hash(_inside_file(source_folder, relative))
                if approved_assets.get(relative) != digest:
                    raise ValueError('Asset histórico sem hash válido: ' + relative)
                frozen.append({'source_path': str(path), 'path': relative, 'sha256': digest})
            if not frozen:
                raise ValueError('Assets históricos ausentes; nenhuma revisão foi criada')
            assets[episode['episode_id']] = {'files': frozen,
                'thumbnail_choices': deepcopy(preview.get('thumbnail_choices')),
                'parent_review_folder': str(source_folder), 'parent_preview_record_sha256': file_hash(review)}

        derived = type(self)(destination, self.cfg, log=self.log, progress=self.progress, cancel=self.cancel)
        derived.plan, derived.evidence = deepcopy(self.plan), deepcopy(self.evidence)
        if supplemental:
            derived.evidence.setdefault('words', []).extend(supplemental)
            derived.evidence['words'].sort(key=lambda row: (float(row['start']), float(row['end']), row.get('word_id', '')))
            derived.evidence.setdefault('provenance', {})['supplemental_word_evidence'] = deepcopy(enrichment)
        revision_id = uuid4().hex
        revision = {'schema': 'LDP_CAPTION_REVISION_V1', 'revision_id': revision_id,
            'parent_project': str(self.directory), 'parent_files': parent_files,
            'source_sha256': self.evidence['source']['sha256'], 'renderer_fingerprint': renderer_fingerprint(),
            'render_settings': deepcopy(self.cfg), 'approval_required': True,
            'audio_review_status': 'NEEDS_HUMAN_AUDIO_REVIEW', 'editorial_decisions_recomputed': False}
        if enrichment:
            revision['evidence_enrichment'] = enrichment
        if styles:
            revision['caption_styles'] = deepcopy(styles)
        derived.plan['caption_revision'] = revision
        derived.plan['parent_plan_id'] = self.plan.get('plan_id')
        derived.plan['plan_id'] = str(self.plan.get('plan_id', 'PLAN')) + '_CAPTIONS_' + revision_id[:12]
        for key in ('episodes', 'extras'):
            derived.plan[key] = [episode for episode in derived.plan.get(key, []) if episode['episode_id'] in selected]
        from .editing_history import invalidate_episode
        for episode in derived.episodes():
            identifier = episode['episode_id']
            invalidate_episode(episode, reason='derived_word_aligned_caption_revision')
            # A parent timeline belongs to its old frozen style/render engine.
            # Its files and references remain intact in the parent snapshot.
            episode.pop('caption_timeline', None)
            if identifier in styles:
                episode['subtitle_preset'] = deepcopy(styles[identifier]['preset'])
                episode['subtitle_overrides'] = deepcopy(styles[identifier]['overrides'])
            for row in episode.get('artifact_history', []):
                row.setdefault('source_project', str(self.directory))
            frozen = deepcopy(assets[identifier])
            for item in frozen['files']:
                item['project_path'] = (Path('caption_assets') / safe_name(identifier) / item['path']).as_posix()
            episode['caption_revision'] = {'revision_id': revision_id, 'revision_of': identifier,
                'parent_project': str(self.directory), 'parent_files': parent_files,
                'transcript_sha256': _transcript_fingerprint(derived.evidence, episode),
                'camera_plan_sha256': _canonical_hash(episode['camera_plan']), 'frozen_camera': True,
                'frozen_assets': frozen, 'frozen_episode_sha256': _canonical_hash(_caption_editorial_inputs(episode))}
            episode['caption_revision']['supplemental_word_ids'] = [word['word_id'] for word in supplemental
                if word['end'] > episode['source_start'] and word['start'] < episode['source_end']]
        derived.plan['status'], derived.plan['human_approval'] = 'REVIEW_REQUIRED', None
        derived.plan.setdefault('audit_trail', []).append({'action': 'derive_caption_revision',
            'revision_id': revision_id, 'parent_files': parent_files,
            'episode_ids': [e['episode_id'] for e in derived.episodes()], 'automatic_approval': False})
        # All source validation precedes destination creation. Parent files are read only.
        destination.mkdir(parents=True, exist_ok=False)
        if _defer_save:
            write_json(destination / 'CAMERA_REVISION_INCOMPLETE.json',
                       {'schema': 'LDP_CAMERA_REVISION_PENDING_V1', 'parent_project': str(self.directory)})
        for name in parent_files:
            target = destination / 'parent_snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.directory / name, target)
            if file_hash(target) != parent_files[name]:
                raise ValueError('Hash divergente ao preservar snapshot original')
        if (self.directory / 'editing_history').is_dir():
            shutil.copytree(self.directory / 'editing_history', destination / 'editing_history')
        for episode in derived.episodes():
            for item in episode['caption_revision']['frozen_assets']['files']:
                target = destination / item['project_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item['source_path'], target)
                if file_hash(target) != item['sha256']:
                    raise ValueError('Hash divergente ao preservar título/capa')
        if not _defer_save:
            derived.save()
        return derived

    def _verify_caption_revision(self, episode):
        frozen = episode.get('caption_revision')
        if not frozen:
            return
        revision = self.plan.get('caption_revision') or {}
        if revision.get('renderer_fingerprint') != renderer_fingerprint():
            raise ValueError('Motor mudou após congelar a revisão; crie outra revisão derivada')
        if revision.get('render_settings') != self.cfg:
            raise ValueError('Configuração diverge da revisão congelada')
        if frozen.get('frozen_episode_sha256') != _canonical_hash(_caption_editorial_inputs(episode)):
            raise ValueError('Decisão editorial ou câmera mudou após congelar a revisão')
        if frozen.get('transcript_sha256') != _transcript_fingerprint(self.evidence, episode):
            raise ValueError('Transcrição diverge da revisão congelada')
        if frozen.get('caption_timeline_sha256'):
            reference = episode.get('caption_timeline') or {}
            if _canonical_hash(reference) != frozen['caption_timeline_sha256']:
                raise ValueError('Timeline de legendas diverge da revisão de câmera congelada')
            for key in ('ass', 'srt', 'sync_metadata'):
                if file_hash(_inside_file(self.directory, reference[key])) != reference['hashes'][key]:
                    raise ValueError('Legenda congelada mudou; revisão preservada')
        for item in frozen['frozen_assets']['files']:
            if file_hash(_inside_file(self.directory, item['project_path'])) != item['sha256']:
                raise ValueError('Asset congelado mudou; revisão preservada para inspeção')

    def prepare_caption_timeline(self, episode_id):
        """Materialize ASS/SRT plus one frozen canonical timeline, without encoding."""
        from .subtitle_presets import write_episode_subtitles
        episode = self.episode(episode_id)
        _validate_episode_window(episode)
        self._verify_caption_revision(episode)
        reference = episode.get('caption_timeline')
        if reference:
            paths = {key: _inside_file(self.directory, reference[key]) for key in ('ass', 'srt', 'sync_metadata')}
            if any(file_hash(paths[key]) != reference['hashes'][key] for key in paths):
                raise ValueError('Timeline congelada mudou; crie outra revisão')
            return {**{key: str(path) for key, path in paths.items()}, 'sync': load_json(paths['sync_metadata']),
                    'preset': load_json(paths['sync_metadata'])['preset']}
        directory = self.folder(episode) / self.signature(episode)[:16] / 'caption_plan'
        if directory.exists():
            raise ValueError('Pasta de timeline existente sem registro; preservada para inspeção')
        result = write_episode_subtitles(self.evidence, episode, directory,
            preset=episode.get('subtitle_preset', 'LDP_CLEAN'), overrides=episode.get('subtitle_overrides'), width=540, height=960)
        episode['caption_timeline'] = {key: Path(result[key]).relative_to(self.directory).as_posix()
                                       for key in ('ass', 'srt', 'sync_metadata')}
        episode['caption_timeline']['hashes'] = {key: file_hash(Path(result[key])) for key in ('ass', 'srt', 'sync_metadata')}
        episode['caption_timeline']['canonical_timeline_sha256'] = result['sync'].get('canonical_timeline_sha256')
        self.save()
        return result

    @classmethod
    def create(cls, evidence, output_root, cfg=None, duration_preset='auto_under_90', mode='SERIE_CRONOLOGICA', **kwargs):
        from .series_planner import plan_series
        plan = plan_series(evidence, duration_preset, mode)
        identity = _canonical_hash({'evidence': evidence, 'preset': duration_preset, 'mode': mode,
            'planner': file_hash(Path(__file__).with_name('series_planner.py'))})[:12]
        source = evidence['source']
        directory = Path(output_root) / 'projects' / safe_name(source.get('video_id') or source.get('id') or source['sha256'][:12]) / identity
        project = cls(directory, cfg, **kwargs)
        if not project.plan:
            project.evidence, project.plan = evidence, plan
            project.plan.setdefault('provenance', {})['curator'] = {'version': '5.1.0',
                'planner_sha256': file_hash(Path(__file__).with_name('series_planner.py')),
                'renderer_fingerprint': renderer_fingerprint()}
            project.save()
        return project

    @classmethod
    def create_stories(cls, evidence, story_document, output_root, cfg=None, **kwargs):
        """Create a separate, review-only project for the ChatGPT story proposals.

        This never modifies an existing V4 Reel project or an approved V5 plan.
        """
        from .story_import import plan_reviewed_stories
        plan = plan_reviewed_stories(evidence, story_document)
        identity = _canonical_hash({'source_sha256': evidence['source']['sha256'],
            'story_plan_id': plan['plan_id'], 'workflow': 'stories_review_v2'})[:16]
        source = evidence['source']
        directory = (Path(output_root) / 'projects' /
            safe_name(source.get('video_id') or source.get('id') or source['sha256'][:12]) /
            ('stories_' + identity))
        project = cls(directory, cfg, **kwargs)
        if project.plan:
            if project.plan.get('plan_id') != plan['plan_id'] or project.evidence.get('source', {}).get('sha256') != source['sha256']:
                raise ValueError('Projeto de Stories existente diverge das evidências; nenhum dado foi substituído')
        else:
            project.evidence, project.plan = evidence, plan
            # New projects adopt the established Reel look. Reopening an
            # existing Stories project above preserves every saved decision.
            for episode in project.episodes():
                episode['subtitle_preset'] = 'LDP_REELS_KARAOKE'
            project.save()
        return project

    def episodes(self):
        return [*self.plan.get('episodes', []), *self.plan.get('extras', [])]

    def episode(self, episode_id):
        episode = next((e for e in self.episodes() if e['episode_id'] == episode_id), None)
        if episode is None:
            raise ValueError('Episódio não encontrado; atualize a seleção após editar/desfazer')
        return episode

    @property
    def can_undo(self):
        from .editing_history import history_for
        return history_for(self.plan)['cursor'] > 0

    @property
    def can_redo(self):
        from .editing_history import history_for
        history = history_for(self.plan)
        return history['cursor'] < len(history['entries'])

    def history_status(self):
        from .editing_history import history_for
        history = history_for(self.plan)
        return {'cursor': history['cursor'], 'commands': len(history['entries']),
                'can_undo': self.can_undo, 'can_redo': self.can_redo,
                'undo_action': history['entries'][history['cursor'] - 1]['action'] if self.can_undo else None,
                'redo_action': history['entries'][history['cursor']]['action'] if self.can_redo else None}

    def _commit_plan(self, revised):
        """Commit plan and history cursor together; keep memory unchanged on failure."""
        previous = self.plan
        json.dumps(revised, ensure_ascii=False, allow_nan=False)
        self.plan = revised
        try:
            self.save()
        except Exception:
            self.plan = previous
            raise

    def _editor_command(self, revised, action, *, explicit=(), details=None):
        from .editing_history import affected_ids, invalidate_plan, append_command
        ids = [episode['episode_id'] for key in ('episodes', 'extras') for episode in revised.get(key, [])]
        if len(ids) != len(set(ids)):
            raise ValueError('A edição produziria uma proposta duplicada já presente no projeto')
        identifiers = affected_ids(self.plan, revised, explicit)
        invalidate_plan(revised, self.plan, identifiers, reason='editor_' + action)
        for episode in [e for key in ('episodes', 'extras') for e in revised.get(key, [])]:
            if episode['episode_id'] in identifiers:
                self.signature(episode)
        append_command(self.directory, self.plan, revised, action=action,
                       identifiers=identifiers, details=details)
        self._commit_plan(revised)
        return self.plan

    def undo(self):
        from .editing_history import restore_command
        self._commit_plan(restore_command(self.directory, self.plan))
        return self.plan

    def redo(self):
        from .editing_history import restore_command
        self._commit_plan(restore_command(self.directory, self.plan, redo=True))
        return self.plan

    def folder(self, episode):
        series_id = episode.get('series_id', 'SERIE_01')
        group = ('EXTRAS_MELHORES_MOMENTOS' if series_id == 'EXTRAS_MELHORES_MOMENTOS'
                 else 'serie_01' if series_id == 'SERIE_01'
                 else 'serie_' + safe_name(series_id).lower())
        # Stable identity survives reordering; number is maintained by playlist/index.
        return self.directory / group / (f"{episode['story_order']:03d}_" + safe_name(episode['episode_id']))

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'series_index.json'
        if path.exists():
            old = path.read_bytes()
            history = self.directory / 'revisions' / (hashlib.sha256(old).hexdigest()[:16] + '.json')
            if not history.exists():
                history.parent.mkdir(parents=True, exist_ok=True)
                history.write_bytes(old)
        temporary = path.with_suffix('.pending.json')
        write_json(temporary, self.plan)
        write_json(self.directory / 'evidence.json', self.evidence)
        write_json(self.directory / 'source_manifest.json', self.evidence.get('source', {}))
        write_json(self.directory / 'evidence_availability.json', self.evidence.get('availability', {}))
        write_json(self.directory / 'story_map.json', self.plan.get('story_map', {}))
        self._playlist()
        # series_index.json is authoritative. Its command cursor and plan cross
        # the commit boundary in one atomic replace, after derived files.
        temporary.replace(path)

    def _playlist(self):
        rows = ['#EXTM3U']
        for episode in self.plan.get('episodes', []):
            media = (episode.get('final') or episode.get('preview') or {}).get('project_path')
            if media and (self.directory / media).is_file():
                rows += [f"#EXTINF:{episode['duration']},Parte {episode['order']}", media]
        (self.directory / 'SERIES_PLAYLIST_ORDER.m3u').write_text('\n'.join(rows)+'\n', encoding='utf-8')

    def edit(self, episode_id, **changes):
        from .series_planner import update_episode
        self.episode(episode_id)
        # Accepted controls must have a renderer. Reject unused model fields explicitly.
        unsupported = set(changes) & {'layout', 'zoom', 'subtitle_style'}
        if unsupported:
            raise ValueError('Use camera_mode/camera_keyframes ou subtitle_overrides para controles implementados: ' + ', '.join(sorted(unsupported)))
        revised = update_episode(self.plan, episode_id, self.evidence, **changes)
        episode = next(e for key in ('episodes','extras') for e in revised.get(key,[]) if e.get('revision_of') == episode_id)
        from .subtitle_presets import resolve_subtitle_preset
        resolve_subtitle_preset(episode.get('subtitle_preset','LDP_KARAOKE_VERDE'),episode.get('subtitle_overrides'))
        if episode.get('thumbnail_selection') not in {None, 'CAPA_01', 'CAPA_02', 'CAPA_03', 'CAPA_04', 'CAPA_05'}:
            raise ValueError('Escolha uma das cinco capas disponíveis')
        self.signature(episode)  # Validate finite serialization/effect inputs before committing the edit.
        self._editor_command(revised, 'edit', explicit=(episode_id, episode['episode_id']),
                             details={'episode_id': episode_id, 'changes': deepcopy(changes)})
        return self.episode(episode['episode_id'])

    def reject(self, episode_id):
        self.episode(episode_id)
        revised = deepcopy(self.plan)
        episode = next(e for key in ('episodes', 'extras') for e in revised.get(key, [])
                       if e['episode_id'] == episode_id)
        episode['state'] = episode['status'] = 'REJECTED'
        episode['human_approval'] = None
        revised.setdefault('audit_trail', []).append({'action': 'human_rejection', 'episode_id': episode_id})
        self._editor_command(revised, 'reject', explicit=(episode_id,))
        return self.episode(episode_id)

    def reorder(self, episode_ids, *, confirm_invalidation=False):
        from .series_planner import reorder_episodes
        revised = reorder_episodes(self.plan, episode_ids, confirm_invalidation=confirm_invalidation)
        if list(episode_ids) == [e['episode_id'] for e in self.plan.get('episodes', [])]:
            return self.plan
        return self._editor_command(revised, 'reorder', details={'episode_ids': list(episode_ids)})

    def split(self, episode_id, duration_preset=None, *, confirm_invalidation=False):
        from .series_planner import split_episode
        revised = split_episode(self.plan, episode_id, self.evidence, duration_preset,
                                confirm_invalidation=confirm_invalidation)
        identifiers = [e['episode_id'] for key in ('episodes', 'extras') for e in revised.get(key, [])
                       if e.get('revision_of') == episode_id]
        return self._editor_command(revised, 'split', explicit=(episode_id, *identifiers),
                                    details={'episode_id': episode_id, 'duration_preset': duration_preset})

    def merge(self, episode_ids, duration_preset=None, *, confirm_invalidation=False):
        from .series_planner import merge_episodes
        revised = merge_episodes(self.plan, episode_ids, self.evidence, duration_preset,
                                 confirm_invalidation=confirm_invalidation)
        return self._editor_command(revised, 'merge', explicit=episode_ids,
                                    details={'episode_ids': list(episode_ids), 'duration_preset': duration_preset})

    def export(self):
        from .full_handoff import export_handoff
        assets = {}
        for episode in self.episodes():
            for kind in ('preview', 'final'):
                folder = episode.get(kind, {}).get('review_folder')
                if folder:
                    origin = (self.directory / folder).resolve()
                    if not origin.is_relative_to(self.directory):
                        raise ValueError('Artefato fora do projeto')
                    for file in origin.rglob('*'):
                        if file.is_file() and not file.is_symlink() and file.suffix.lower() in {'.ass','.srt','.json','.png','.jpg'}:
                            assets['media/' + file.relative_to(self.directory).as_posix()] = file
        return export_handoff(self.evidence, self.plan, self.directory / 'CHATGPT_HANDOFF', media_paths=assets)

    def _media(self, source_path):
        path = Path(source_path)
        expected = self.evidence['source'].get('sha256')
        if not path.is_file() or not expected or file_hash(path) != expected:
            raise ValueError('Mídia original ausente ou SHA256 diferente da análise')
        return path.resolve()

    def signature(self, episode):
        self._verify_caption_revision(episode)
        return episode_signature(episode, self.evidence['source']['sha256'], self.cfg,
            transcript_fingerprint=_transcript_fingerprint(self.evidence, episode))

    def render(self, episode_id, source_path, *, preview=True):
        from .subtitle_presets import write_episode_subtitles
        from .thumbnail_presets import generate_thumbnail_choices
        from .render import _base_cmd, ffmpeg_has_nvenc
        from .title_presets import create_episode_title_card
        from .media_effects import extend_render_command
        if self.cancel and self.cancel.is_set():
            raise OperationCancelled('Operação cancelada')
        media = self._media(source_path)
        episode = self.episode(episode_id)
        _validate_episode_window(episode)
        self._verify_caption_revision(episode)
        if episode.get('state') == 'REJECTED' or episode.get('status') == 'REJECTED':
            raise ValueError('Episódio rejeitado')
        approval_folder = episode.get('preview', {}).get('review_folder')
        if not preview:
            if not approval_folder or not episode_approval_matches(self.directory / approval_folder, self.signature(episode)):
                raise ValueError('Episódio requer aprovação humana do preview atual')
            approved = load_json(self.directory / approval_folder / 'PREVIEW_APPROVED_V5.json', {})
            if episode.get('duration_within_target') is False and not approved.get('duration_deviation_accepted'):
                raise ValueError('Desvio de duração exige aceitação explícita')
        # Camera is a rendering input. Resolve it before signing the preview.
        if preview and not episode.get('camera_plan'):
            episode['camera_plan'] = conservative_camera(self.evidence, episode, self.cfg)
        signature = self.signature(episode)
        directory = self.folder(episode) / signature[:16] / ('preview' if preview else 'final')
        directory.mkdir(parents=True, exist_ok=True)
        name = 'PREVIEW_540x960.mp4' if preview else 'FINAL_1080x1920.mp4'
        output = directory / name
        if output.is_file():
            previous = episode.get('preview' if preview else 'final') or {}
            if previous.get('plan_hash') != signature or previous.get('sha256') != file_hash(output):
                raise ValueError('MP4 existente sem registro válido ou alterado; preservado para inspeção. Crie uma nova revisão do episódio.')
            validate_episode_media(output, 540 if preview else 1080, 960 if preview else 1920, episode['duration'])
            self.log('MP4 existente revalidado e preservado.')
            return output
        if any(directory.iterdir()):
            raise ValueError('Tentativa anterior incompleta preservada; crie uma nova revisão do episódio')
        with (directory / 'RENDER_ATTEMPT.json').open('x', encoding='utf-8') as receipt:
            json.dump({'episode_id': episode_id, 'plan_signature': signature, 'approved': False}, receipt)
        width, height = (540, 960) if preview else (1080, 1920)
        canonical = None
        if preview and episode.get('caption_revision'):
            canonical = self.prepare_caption_timeline(episode_id)['sync']
        elif not preview:
            canonical = load_json(_inside_file(self.directory,
                Path(approval_folder) / 'SUBTITLE_SYNC.json'), {})
            if not canonical.get('canonical_timeline_sha256'):
                raise ValueError('Prévia sem timeline canônica; gere e revise outra prévia')
        subtitle = write_episode_subtitles(self.evidence, episode, directory,
            preset={'documentary':'LDP_DOCUMENTARIO'}.get(episode.get('subtitle_preset'), episode.get('subtitle_preset', 'LDP_KARAOKE_VERDE')),
            overrides=episode.get('subtitle_overrides'), width=width, height=height, canonical_timeline=canonical)
        if subtitle['sync'].get('renderable') is False:
            raise ValueError('Legenda não cabe na área segura; timeline preservada para revisão humana')
        if canonical and subtitle['sync'].get('canonical_timeline_sha256') != canonical.get('canonical_timeline_sha256'):
            raise ValueError('Timeline de legenda diverge da prévia/revisão congelada')
        if subtitle['sync'].get('needs_human_review'):
            self.log('Legenda exige revisão: ' + str(subtitle['sync'].get('diagnostics')))
        settings = deepcopy(self.cfg)
        settings.setdefault('render', {}).update({'preview_width': 540, 'preview_height': 960,
                                                  'final_width': 1080, 'final_height': 1920})
        title = episode.get('title_text') or (episode.get('title_options') or [''])[0]
        if isinstance(title, dict):
            title = title.get('text') or title.get('title') or ''
        clip = {**episode, 'clip_id': episode_id, 'title_text': title}
        clip.setdefault('title_duration', 5.0)
        frozen_assets = (episode.get('caption_revision') or {}).get('frozen_assets')
        if preview and frozen_assets:
            for item in frozen_assets['files']:
                target = directory / item['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and file_hash(target) != item['sha256']:
                    raise ValueError('Asset existente diverge da revisão congelada')
                if not target.exists():
                    shutil.copy2(_inside_file(self.directory, item['project_path']), target)
            title_asset = directory / 'title_card_preview.png'
            card = title_asset if title_asset.is_file() else None
        else:
            card = create_episode_title_card(clip, directory, settings, preview=preview)
        # Thumbnails are materialized without changing the signed editorial plan.
        thumbnail_options = dict(episode.get('thumbnail_overrides') or {})
        if 'frame_count' not in thumbnail_options:
            legacy_count = len(thumbnail_options.get('frame_times') or thumbnail_options.get('layouts') or [])
            thumbnail_options['frame_count'] = 3 if legacy_count == 3 else 5
        if preview and frozen_assets:
            thumbnails = deepcopy(frozen_assets['thumbnail_choices'])
            if thumbnails:
                thumbnails['manifest'] = str(directory / 'thumbnails' / 'THUMBNAIL_CHOICES.json')
        else:
            thumbnails = generate_thumbnail_choices(media, clip, directory / 'thumbnails',
                evidence=self.evidence, source_sha256=self.evidence['source']['sha256'],
                titles=[episode.get('thumbnail_title') or title],
                overrides=thumbnail_options) if preview else None
        encoders = ['h264_nvenc', 'libx264'] if settings['render'].get('prefer_nvenc', True) and ffmpeg_has_nvenc() else ['libx264']
        for encoder in encoders:
            partial = directory / ('ENCODING_' + uuid4().hex + '_' + name)
            cmd, _, _ = _base_cmd(None, clip, media, partial, Path(subtitle['ass']), card, settings, preview, encoder)
            cmd = ['-n' if arg == '-y' else arg for arg in cmd]
            cmd = extend_render_command(cmd, episode, width, height, episode['duration'], directory)
            cmd[-1:-1] = ['-threads', '2', '-filter_complex_threads', '2']
            self.log(f'{episode_id}: {encoder}; fonte SHA256 validada; câmera {clip["camera_plan"]["mode"]}')
            write_json(directory / 'RENDER_RUN.json', {'encoder':encoder, 'source_sha256':self.evidence['source']['sha256'],
                'source_start':episode['source_start'], 'source_end':episode['source_end'], 'duration':episode['duration'],
                'width':width,'height':height,'camera_mode':clip['camera_plan']['mode'],
                'renderer_fingerprint':renderer_fingerprint(),'output':name,'preview':preview})
            code, error = _encode(cmd, episode['duration'], self.progress, self.cancel)
            if code == 0:
                break
            self.log('Encode falhou; fallback disponível: ' + error[-500:])
        else:
            raise RuntimeError('FFmpeg falhou: ' + error[-2000:])
        validation = validate_episode_media(partial, width, height, episode['duration'])
        # Exclusive publication: never replace a concurrent or historical MP4.
        os.link(partial, output)
        partial.unlink()
        write_json(directory / 'RENDER_VALIDATION.json', validation)
        write_json(directory / 'camera_plan.json', episode['camera_plan'])
        write_json(directory / 'episode.json', episode)
        artifact = {'project_path': output.relative_to(self.directory).as_posix(), 'sha256': file_hash(output),
                    'review_folder': directory.relative_to(self.directory).as_posix(), 'plan_hash': signature,
                    'rendered_duration': validation['duration'], 'thumbnail_choices': thumbnails,
                    'subtitle_alignment': subtitle['sync']['alignment'],
                    'canonical_timeline_sha256': subtitle['sync'].get('canonical_timeline_sha256'),
                    'subtitle_needs_review': subtitle['sync'].get('needs_human_review',False),
                    'subtitle_diagnostics': subtitle['sync'].get('diagnostics',[])}
        if preview:
            assets = [Path(subtitle[k]) for k in ('ass', 'srt', 'sync_metadata')]
            assets += [directory / 'camera_plan.json']
            if card:
                assets.append(card)
                assets.append(directory / 'TITLE_LAYOUT.json')
            if (directory / 'WATERMARK.png').exists():
                assets.append(directory / 'WATERMARK.png')
            if thumbnails:
                assets += list((directory / 'thumbnails').rglob('*.png'))
                assets += list((directory / 'thumbnails').rglob('*.json'))
            record_episode_preview(directory, output, signature, validation, assets)
            episode['preview'] = artifact
            episode['state'] = episode['status'] = 'PREVIEW_READY'
            episode['preview_duration'] = validation['duration']
        else:
            choices = episode.get('preview', {}).get('thumbnail_choices', {}).get('choices', [])
            selected = episode.get('thumbnail_selection') or 'CAPA_01'
            choice = next((c for c in choices if c['choice_id'] == selected), None)
            if choice:
                cover = self.directory / approval_folder / 'thumbnails' / choice['file']
                if file_hash(cover) != choice['sha256']:
                    raise ValueError('Capa selecionada mudou depois da revisão')
                shutil.copy2(cover, directory / 'CAPA_SELECIONADA.png')
            episode['final'] = artifact
            episode['state'] = episode['status'] = 'FINAL_RENDERED'
            episode['rendered_duration'] = validation['duration']
        episode['duration_verified_by_ffprobe'] = True
        episode['encoding_tolerance_seconds'] = .15
        self.save()
        self.progress(1, 'MP4 validado; inspeção humana pendente' if preview else 'Final validado')
        return output

    def approve(self, episode_id, *, human_reviewed=False, duration_deviation_accepted=False):
        episode = self.episode(episode_id)
        if episode.get('status') == 'REJECTED':
            raise ValueError('Episódio rejeitado; revise e gere outro preview antes de aprovar')
        directory = episode.get('preview', {}).get('review_folder')
        if not directory:
            raise ValueError('Gere e assista ao preview antes de aprovar')
        record = approve_episode_preview(self.directory / directory, self.signature(episode),
            human_reviewed=human_reviewed, duration_deviation_accepted=duration_deviation_accepted)
        episode['approval'] = record
        episode['human_approval'] = record
        episode['state'] = episode['status'] = 'PREVIEW_APPROVED'
        self.save()
        return record

    def render_approved(self, source_path):
        outputs = []
        for episode in self.episodes():
            if self.cancel and self.cancel.is_set():
                raise OperationCancelled('Lote cancelado; finais concluídos preservados')
            if episode.get('status') == 'REJECTED':
                continue
            directory = episode.get('preview', {}).get('review_folder')
            if directory and episode_approval_matches(self.directory / directory, self.signature(episode)):
                outputs.append(self.render(episode['episode_id'], source_path, preview=False))
        if not outputs:
            raise ValueError('Nenhum episódio possui aprovação válida do preview atual')
        return outputs
