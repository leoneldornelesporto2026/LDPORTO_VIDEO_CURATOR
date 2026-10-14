"""Local, resumable V5 project workflow. No models, downloads or Analyzer writes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
from types import SimpleNamespace

from .approval import file_hash
from .episode_approval import (episode_signature, record_episode_preview,
    approve_episode_preview, episode_approval_matches, renderer_fingerprint)
from .utils import load_json, write_json, safe_name, run


class OperationCancelled(RuntimeError):
    pass


def _canonical_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


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
        self.cfg, self.log = deepcopy(cfg or {}), log
        self.progress = progress or (lambda fraction, detail='': None)
        self.cancel = cancel
        self.plan = load_json(self.directory / 'series_index.json', {}) or {}
        self.evidence = load_json(self.directory / 'evidence.json', {}) or {}

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

    def episodes(self):
        return [*self.plan.get('episodes', []), *self.plan.get('extras', [])]

    def episode(self, episode_id):
        return next(e for e in self.episodes() if e['episode_id'] == episode_id)

    def folder(self, episode):
        group = 'EXTRAS_MELHORES_MOMENTOS' if episode.get('series_id') == 'EXTRAS_MELHORES_MOMENTOS' else 'serie_01'
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
        temporary.replace(path)
        write_json(self.directory / 'evidence.json', self.evidence)
        write_json(self.directory / 'source_manifest.json', self.evidence.get('source', {}))
        write_json(self.directory / 'evidence_availability.json', self.evidence.get('availability', {}))
        write_json(self.directory / 'story_map.json', self.plan.get('story_map', {}))
        self._playlist()

    def _playlist(self):
        rows = ['#EXTM3U']
        for episode in self.plan.get('episodes', []):
            media = (episode.get('final') or episode.get('preview') or {}).get('project_path')
            if media and (self.directory / media).is_file():
                rows += [f"#EXTINF:{episode['duration']},Parte {episode['order']}", media]
        (self.directory / 'SERIES_PLAYLIST_ORDER.m3u').write_text('\n'.join(rows)+'\n', encoding='utf-8')

    def edit(self, episode_id, **changes):
        from .series_planner import update_episode
        # Accepted controls must have a renderer. Reject unused model fields explicitly.
        unsupported = set(changes) & {'layout', 'zoom', 'subtitle_style'}
        if unsupported:
            raise ValueError('Use camera_mode/camera_keyframes ou subtitle_overrides para controles implementados: ' + ', '.join(sorted(unsupported)))
        revised = update_episode(self.plan, episode_id, self.evidence, **changes)
        episode = next(e for key in ('episodes','extras') for e in revised.get(key,[]) if e.get('revision_of') == episode_id)
        from .subtitle_presets import resolve_subtitle_preset
        resolve_subtitle_preset(episode.get('subtitle_preset','LDP_KARAOKE_VERDE'),episode.get('subtitle_overrides'))
        if episode.get('thumbnail_selection') not in {None,'CAPA_01','CAPA_02','CAPA_03'}:
            raise ValueError('Escolha uma das três capas geradas')
        self.signature(episode)  # Validate finite serialization/effect inputs before committing the edit.
        self.plan = revised
        self.save()
        return episode

    def reject(self, episode_id):
        episode = self.episode(episode_id)
        episode['state'] = episode['status'] = 'REJECTED'
        episode['human_approval'] = None
        self.plan.setdefault('audit_trail', []).append({'action': 'human_rejection', 'episode_id': episode_id})
        self.save()

    def reorder(self, episode_ids, *, confirm_invalidation=False):
        from .series_planner import reorder_episodes
        self.plan = reorder_episodes(self.plan, episode_ids, confirm_invalidation=confirm_invalidation)
        self.save()

    def split(self, episode_id, duration_preset=None, *, confirm_invalidation=False):
        from .series_planner import split_episode
        self.plan = split_episode(self.plan, episode_id, self.evidence, duration_preset,
                                  confirm_invalidation=confirm_invalidation)
        self.save()
        return self.plan

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
        return episode_signature(episode, self.evidence['source']['sha256'], self.cfg)

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
        if preview:
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
        width, height = (540, 960) if preview else (1080, 1920)
        subtitle = write_episode_subtitles(self.evidence, episode, directory,
            preset={'documentary':'LDP_DOCUMENTARIO'}.get(episode.get('subtitle_preset'), episode.get('subtitle_preset', 'LDP_KARAOKE_VERDE')),
            overrides=episode.get('subtitle_overrides'), width=width, height=height)
        if subtitle['sync'].get('needs_human_review'):
            self.log('Legenda exige revisão: ' + str(subtitle['sync'].get('diagnostics')))
        settings = deepcopy(self.cfg)
        settings.setdefault('render', {}).update({'preview_width': 540, 'preview_height': 960,
                                                  'final_width': 1080, 'final_height': 1920})
        title = episode.get('title_text') or (episode.get('title_options') or [''])[0]
        if isinstance(title, dict):
            title = title.get('text') or title.get('title') or ''
        clip = {**episode, 'clip_id': episode_id, 'title_text': title}
        card = create_episode_title_card(clip, directory, settings, preview=preview)
        # Thumbnails are materialized without changing the signed editorial plan.
        thumbnails = generate_thumbnail_choices(media, clip, directory / 'thumbnails',
            evidence=self.evidence, source_sha256=self.evidence['source']['sha256'],
            titles=[episode.get('thumbnail_title') or title]*3,
            overrides=episode.get('thumbnail_overrides')) if preview else None
        encoders = ['h264_nvenc', 'libx264'] if settings['render'].get('prefer_nvenc', True) and ffmpeg_has_nvenc() else ['libx264']
        partial = directory / ('ENCODING_' + name)
        for encoder in encoders:
            cmd, _, _ = _base_cmd(None, clip, media, partial, Path(subtitle['ass']), card, settings, preview, encoder)
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
        partial.replace(output)
        write_json(directory / 'RENDER_VALIDATION.json', validation)
        write_json(directory / 'camera_plan.json', episode['camera_plan'])
        write_json(directory / 'episode.json', episode)
        artifact = {'project_path': output.relative_to(self.directory).as_posix(), 'sha256': file_hash(output),
                    'review_folder': directory.relative_to(self.directory).as_posix(), 'plan_hash': signature,
                    'rendered_duration': validation['duration'], 'thumbnail_choices': thumbnails,
                    'subtitle_alignment': subtitle['sync']['alignment'],
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
                import shutil
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
