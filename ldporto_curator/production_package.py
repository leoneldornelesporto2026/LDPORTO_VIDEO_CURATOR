"""Transactional imports into the existing V5 review/render workflow.

No curation, ASR, perception, source copying or approval happens at import time.
New projects are external; legacy state and renderer fingerprints are untouched.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from .episode_approval import file_hash, renderer_fingerprint
from .persisted_plan import project_lock
from .production_contract import read_production_archive, read_editorial_handoff
from .production_evidence import normalise_production_evidence, build_piece_camera
from .series_workflow import SeriesProject, OperationCancelled
from .utils import load_json, write_json, safe_name


def videos_folder():
    """Use Windows' redirected Known Folder, including localized installations."""
    if os.name == 'nt':
        import ctypes
        import uuid
        guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID('18989b1d-99b5-455b-841c-ab7c74e4ddfc').bytes_le)
        result = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result)) == 0:
            try:
                return Path(result.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(result)
    return Path.home() / 'Videos'


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _cancelled(cancel):
    if cancel and cancel.is_set():
        raise OperationCancelled('Importação cancelada; staging e resultados concluídos preservados')


def _outside_repository(path):
    root = Path(__file__).resolve().parent.parent
    path = Path(path).expanduser().absolute()
    for ancestor in (path, *path.parents):
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Destino com link/junction não permitido: ' + str(ancestor))
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError('Projetos de produção e artefatos pesados exigem destino fora do repositório')
    return path


def _probe(path):
    proc = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                          capture_output=True, text=True, timeout=60, check=True)
    document = json.loads(proc.stdout)
    video = next((s for s in document['streams'] if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('A mídia selecionada não possui vídeo')
    rate = video.get('avg_frame_rate', '0/1').split('/')
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
    return {'duration': float(document['format']['duration']), 'width': video['width'], 'height': video['height'],
            'fps': fps, 'video_codec': video.get('codec_name'),
            'audio_codecs': [s.get('codec_name') for s in document['streams'] if s.get('codec_type') == 'audio']}


def resolve_production_media(metadata, *, media_library=None, media_path=None, legacy_paths=(), cancel=None):
    """Associate only a fully rehashed, technically compatible original."""
    expected = metadata['sha256']
    library = Path(media_library or videos_folder() / 'LDPORTO_MEDIA_LIBRARY')
    candidates = []
    if library.is_dir():
        # Bounded manifest discovery, never a recursive scan of all user videos.
        for folder in list(library.iterdir())[:1000]:
            if folder.is_dir() and not folder.is_symlink():
                manifest = load_json(folder / 'media_manifest.json', {}) or {}
                if manifest.get('sha256', manifest.get('source_sha256')) == expected:
                    value = manifest.get('relative_path') or manifest.get('path') or manifest.get('media_path') or 'original.mp4'
                    value = Path(value)
                    candidates.append((value if value.is_absolute() else folder / value, 'media_library'))
    reference = metadata.get('source') or {}
    for value in (metadata.get('path'), metadata.get('source_path'), reference.get('path'), reference.get('local_path')):
        if value and Path(value).is_absolute():
            candidates.append((Path(value), 'manifest_reference'))
    candidates.extend((Path(path), 'associated_or_legacy') for path in legacy_paths if path)
    if media_path:
        candidates.insert(0, (Path(media_path), 'manual_selection'))
    seen, mismatches = set(), []
    for candidate, origin in candidates:
        _cancelled(cancel)
        if not candidate.is_file():
            continue
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        before = candidate.stat()
        actual = file_hash(candidate)
        if actual != expected:
            mismatches.append({'path': str(candidate), 'sha256': actual, 'expected': expected})
            if origin == 'manual_selection':
                raise ValueError('SHA256 da mídia selecionada diverge da fonte: ' + actual + ' ≠ ' + expected)
            continue
        technical = _probe(candidate)
        if any(metadata.get(k) and int(metadata[k]) != technical[k] for k in ('width', 'height')):
            raise ValueError('Resolução da mídia diverge do manifest verificado')
        if abs(float(metadata['duration']) - technical['duration']) > .25:
            raise ValueError('Duração da mídia diverge do manifest verificado')
        if metadata.get('fps') and abs(float(metadata['fps']) - technical['fps']) > .05:
            raise ValueError('FPS da mídia diverge do manifest verificado')
        after = candidate.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Mídia mudou durante a verificação')
        return {'path': str(candidate), 'sha256': actual, 'state': 'HASH_AND_TECHNICAL_VERIFIED',
                'technical': technical, 'origin': origin, 'bytes': after.st_size, 'mtime_ns': after.st_mtime_ns,
                'copied': False, 'downloaded': False}
    return {'path': None, 'sha256': expected, 'state': 'MEDIA_SELECTION_REQUIRED', 'technical': None,
            'mismatches': mismatches, 'copied': False, 'downloaded': False}


def caption_preflight(piece, evidence, *, directory=None):
    """Upstream review gates are authoritative; mechanical timing is insufficient."""
    declared = piece.get('caption_preflight') or piece.get('caption_plan') or {}
    if piece.get('assembly_disclosure_required'):
        return {'state': 'BLOCKED', 'renderable': False, 'reason': 'DISCONTIGUOUS_SOURCE_ASSEMBLY_UNSUPPORTED'}
    state = declared.get('status') or declared.get('state') or ''
    raw = piece.get('raw_proposal') or {}
    blockers = set(raw.get('blockers') or [])
    if blockers & {'human_audio_review_pending', 'source_transcript_uncertain', 'audio_review_required'}:
        return {'state': 'AUDIO_REVIEW_REQUIRED', 'renderable': False,
                'reason': 'UPSTREAM_STORY_AUDIO_REVIEW_PENDING', 'source_blockers': sorted(blockers)}
    if state in {'AUDIO_REVIEW_REQUIRED', 'ALIGNMENT_REVIEW_REQUIRED', 'BLOCKED'}:
        return {'state': state, 'renderable': False, 'reason': 'UPSTREAM_REVIEW_REQUIRED', 'declared': declared}
    if declared.get('allowed_caption_mode') == 'none' and state not in {'NO_SPEECH', 'INSTRUMENTAL'}:
        return {'state': 'ALIGNMENT_REVIEW_REQUIRED', 'renderable': False, 'reason': 'UPSTREAM_CAPTIONS_NOT_RELEASED', 'declared': declared}
    if state in {'NO_SPEECH', 'INSTRUMENTAL'}:
        proof = _non_speech_proof(piece, evidence, state)
        return {'state': state, 'renderable': proof is not None,
            'reason': None if proof else 'POSITIVE_NON_SPEECH_EVIDENCE_REQUIRED', 'evidence': proof, 'declared': declared}
    from .subtitle_presets import write_episode_subtitles
    def check(folder):
        try:
            result = write_episode_subtitles(evidence, piece, folder, preset=piece.get('subtitle_preset', 'LDP_REELS_KARAOKE'),
                overrides=piece.get('subtitle_overrides'), width=540, height=960)
            sync = result['sync']
            reliable = sync.get('renderable') is not False and sync.get('alignment') == 'word'
            phrase = sync.get('renderable') is not False and sync.get('alignment') in {'segment', 'mixed'} and declared.get('allow_phrase') is True
            if phrase:
                phrase = all(len(row.get('literal_text', '').split()) <= 18 and row['end'] - row['start'] <= 8
                    for row in sync.get('events', []) if row.get('method') != 'word')
            return {'state': 'ALIGNED_WORD' if reliable else 'PHRASE_ONLY' if phrase else 'ALIGNMENT_REVIEW_REQUIRED',
                'renderable': bool(reliable or phrase), 'mechanical_timing_only': True, 'human_audio_verified': False,
                'diagnostics': sync.get('diagnostics', []), 'reason': None if reliable or phrase else 'UNSAFE_OR_INCOMPLETE_ALIGNMENT'}
        except (ValueError, KeyError) as exc:
            return {'state': 'ALIGNMENT_REVIEW_REQUIRED', 'renderable': False, 'reason': str(exc)}
    if directory:
        return check(Path(directory))
    with tempfile.TemporaryDirectory(prefix='ldporto_caption_preflight_') as temporary:
        return check(Path(temporary))


def _non_speech_proof(piece, evidence, state):
    """Positive source-bound coverage, never an inference from missing ASR."""
    start, end = piece.get('source_start'), piece.get('source_end')
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)) or end <= start:
        return None
    if any(row.get('end', 0) > start and row.get('start', end) < end and
           str(row.get('text') or row.get('literal_text') or '').strip() for row in evidence.get('segments', [])):
        return None
    if any(row.get('end', 0) > start and row.get('start', end) < end for row in evidence.get('words', [])):
        return None
    records = evidence.get('audio_events') or (evidence.get('audio') or {}).get('events') or []
    rows, cursor = [], start
    expected = evidence.get('source', {}).get('sha256')
    for row in sorted(records, key=lambda r: r.get('start', -1)):
        if row.get('end', 0) <= start or row.get('start', end) >= end:
            continue
        values = [row.get(k) for k in ('start', 'end', 'confidence')]
        if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
                or row['start'] > cursor + 1e-7 or row['end'] <= row['start'] or not .95 <= row['confidence'] <= 1
                or not 0 <= row['start'] < row['end'] <= evidence.get('source', {}).get('duration', -1)
                or row.get('source_sha256') != expected or not isinstance(row.get('event_id'), str) or not row['event_id'].strip()
                or row.get('no_speech') is not True
                or row.get('category') != ('instrumental' if state == 'INSTRUMENTAL' else 'no_speech')):
            return None
        cursor = max(cursor, min(end, row['end']))
        rows.append(deepcopy(row))
    if cursor < end - 1e-7 or not rows or len({r['event_id'] for r in rows}) != len(rows):
        return None
    return {'source_sha256': expected, 'state': state, 'events': rows, 'start': start, 'end': end,
            'sha256': _digest(rows), 'claim': 'supplied_positive_evidence_pending_human_review'}


def _stage(container, root, cancel):
    root.mkdir(parents=True, exist_ok=False)
    for name, payload in container['files'].items():
        _cancelled(cancel)
        target = root / name
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('Arquivo fora do staging')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write(payload)
    container['root'] = str(root)


def _companion(package, explicit):
    if explicit:
        return read_editorial_handoff(explicit, package['metadata']['sha256'], package['package_sha256'])
    root = videos_folder() / 'LDPORTO_VIDEO_ANALYZER'
    matches = []
    if root.is_dir():
        for folder in list(root.iterdir())[:500]:
            manifest = load_json(folder / 'PROJECT_MANIFEST.json', {}) if folder.is_dir() else {}
            if manifest and manifest.get('source_sha256') == package['metadata']['sha256'] and manifest.get('package_sha256') == package['package_sha256']:
                matches.append(folder)
    if len(matches) == 1:
        return read_editorial_handoff(matches[0], package['metadata']['sha256'], package['package_sha256'])
    if len(matches) > 1:
        raise ValueError('Vários dossiês vinculados; selecione explicitamente o handoff desejado')
    return None


def import_production_package(path, *, cfg=None, output_root=None, media_library=None,
        media_path=None, handoff_dir=None, log=print, progress=None, cancel=None):
    progress = progress or (lambda fraction, detail='': None)
    _cancelled(cancel)
    progress(.03, 'Validando contrato e hashes do pacote')
    package = read_production_archive(path)
    companion = _companion(package, handoff_dir) if package['format'] == 'ANALYZER_NATIVE' else None
    settings = deepcopy(cfg or {})
    settings.setdefault('render', {})
    # Pin only render inputs, excluding global infrastructure/AI settings.
    settings = {k: v for k, v in settings.items() if k in {'render', 'subtitles', 'title', 'output', 'camera', 'camera_v44', 'audio'}}
    settings['render'].setdefault('prefer_nvenc', False)
    root = _outside_repository(output_root or videos_folder() / 'LDPORTO_VIDEO_CURATOR')
    source_hash = package['metadata']['sha256']
    identity = _digest({'source': source_hash, 'package': package['package_sha256'],
        'handoff': companion['package_sha256'] if companion else None, 'settings': settings,
        'adapter': file_hash(Path(__file__)), 'visual_adapter': file_hash(Path(__file__).with_name('production_evidence.py'))})[:20]
    title = package.get('title') or (companion or {}).get('title') or 'Projeto_audiovisual'
    parent = root / (safe_name(title)[:60] + '__' + source_hash[:12])
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / 'revisions' / identity
    with project_lock(parent):
        if destination.is_dir():
            project = load_production_project(destination, log=log, progress=progress, cancel=cancel)
            reference = project.plan['production_import']['media_reference']
            if media_path or reference['state'] != 'HASH_AND_TECHNICAL_VERIFIED':
                reference = resolve_production_media(package['metadata'], media_library=media_library,
                    media_path=media_path, legacy_paths=[reference.get('path')], cancel=cancel)
                # Association is infrastructural, never a change to signed cfg.
                project.plan['production_import']['media_reference'] = reference
                project.plan['production_import']['summary']['source_path'] = reference['path']
                project.plan['production_import']['summary']['media_state'] = reference['state']
                project.save()
            return {'production_import': True, 'project': project, 'source_path': Path(reference['path']) if reference['path'] else None,
                    'summary': project.plan['production_import']['summary']}
        transaction = parent / '_staging' / (identity + '_' + uuid4().hex[:8])
        transaction.mkdir(parents=True, exist_ok=False)
        journal = {'schema': 'LDP_PRODUCTION_TRANSACTION_V1', 'state': 'STAGING', 'revision_id': identity,
            'destination': str(destination), 'source_sha256': source_hash, 'previous_projects_modified': False}
        write_json(transaction / 'TRANSACTION.json', journal)
        try:
            work = transaction / 'project'
            work.mkdir()
            _stage(package, work / 'inputs/package', cancel)
            if companion:
                _stage(companion, work / 'inputs/handoff', cancel)
            normalized = normalise_production_evidence(package, handoff=companion)
            progress(.35, 'Associando mídia original por SHA256')
            # Legacy paths are considered only when the recorded hash agrees.
            associated = []
            repository = Path(__file__).resolve().parent.parent
            for manifest_path in list((repository / 'output').glob('projects/*/*/source_manifest.json'))[:500]:
                manifest = load_json(manifest_path, {}) or {}
                if manifest.get('sha256', manifest.get('source_sha256')) == source_hash:
                    associated.extend(manifest.get(k) for k in ('path', 'source_path', 'local_path') if manifest.get(k))
            reference = resolve_production_media(package['metadata'], media_library=media_library,
                media_path=media_path, legacy_paths=associated, cancel=cancel)
            project = ProductionProject(work, settings, log=log, progress=progress, cancel=cancel)
            project.evidence = normalized['evidence']
            project.evidence.setdefault('availability', {})
            project.evidence['source'].update(sha256=source_hash, duration=package['metadata']['duration'])
            # Paths in the normalized index must refer to the committed revision.
            def relocate(value):
                if isinstance(value, str) and value.startswith(str(work)):
                    return str(destination) + value[len(str(work)):]
                if isinstance(value, dict):
                    return {k: relocate(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [relocate(v) for v in value]
                return value
            visual = relocate(normalized['visual_index'])
            write_json(work / 'visual_evidence_index.json', visual)
            episodes, piece_index = [], {}
            for i, piece in enumerate(normalized['pieces'], 1):
                _cancelled(cancel)
                episode = deepcopy(piece)
                episode.update(order=i, story_order=i, series_id=piece.get('series_id') or ('REELS' if piece['piece_kind'] == 'REEL' else 'STORIES'),
                    source_sha256=source_hash, title_text=piece.get('title') or '', internal_title=piece.get('title') or '',
                    subtitle_preset=piece.get('caption_plan', {}).get('preset', 'LDP_REELS_KARAOKE'),
                    subtitle_overrides=piece.get('caption_plan', {}).get('overrides', {}),
                    camera_mode=piece.get('camera_mode') or 'AUTO_CONSERVADOR',
                    audio=piece.get('audio_plan') or {'mode': 'original'}, state='PLANNED', status='PLANNED',
                    human_approval=None, duration_preset='auto_under_90',
                    production_origin_id=piece['episode_id'])
                episode['duration'] = episode['source_end'] - episode['source_start']
                episode['camera_plan'] = piece.get('camera_plan') or build_piece_camera(normalized['visual_index'], piece, package['metadata'], settings)
                gate = caption_preflight(episode, project.evidence)
                if episode['piece_kind'] != 'REEL' and episode['duration'] > 59.5:
                    gate = {'state': 'BLOCKED', 'renderable': False, 'reason': 'STORY_EXCEEDS_59_5_SECONDS'}
                episode['production_caption_gate'] = gate
                if gate['renderable'] and gate['state'] in {'NO_SPEECH', 'INSTRUMENTAL'}:
                    episode['subtitle_preset'] = 'SEM_LEGENDA'
                    episode['caption_revision'] = {'production_non_speech': gate['evidence']}
                piece_index[episode['production_origin_id']] = relocate(piece)
                episodes.append(episode)
                progress(.45 + .4 * i / max(1, len(normalized['pieces'])), 'Plano e bloqueios: ' + episode['episode_id'])
            summary = {'format': package['format'], 'source_sha256': source_hash, 'title': title,
                'declared_video_id': package['metadata'].get('video_id') or package['metadata'].get('source', {}).get('id'),
                'package_sha256': package['package_sha256'], 'revision_id': identity, 'project_path': str(destination),
                'source_path': reference['path'], 'media_state': reference['state'],
                'counts': {'reels': sum(e['piece_kind'] == 'REEL' for e in episodes),
                    'stories': sum(e['piece_kind'] != 'REEL' for e in episodes),
                    'series': len({e['series_id'] for e in episodes if e['piece_kind'] == 'STORY_PART'})},
                'caption_states': dict(Counter(e['production_caption_gate']['state'] for e in episodes)),
                'visual': normalized['summary'], 'blocked': sum(not e['production_caption_gate']['renderable'] for e in episodes),
                'approval_state': 'HUMAN_REVIEW_REQUIRED'}
            project.plan = {'schema_version': '5.2.0', 'plan_id': 'PRODUCTION_' + identity, 'source_sha256': source_hash,
                'status': 'REVIEW_REQUIRED', 'mode': 'SERIE_CRONOLOGICA', 'duration_preset': 'auto_under_90',
                'episodes': episodes, 'extras': [], 'story_map': {}, 'audit_trail': [{'action': 'import_production_package',
                    'automatic_curation': False, 'automatic_approval': False}],
                'production_import': {'schema': 'LDP_PRODUCTION_IMPORT_V1', 'revision_id': identity,
                    'package_sha256': package['package_sha256'], 'package_path': str(Path(path).resolve()),
                    'handoff_path': (companion or {}).get('path'), 'format': package['format'],
                    'import_options': {'output_root': str(root), 'media_library': str(media_library or videos_folder() / 'LDPORTO_MEDIA_LIBRARY'),
                        'handoff_dir': (companion or {}).get('path')},
                    'render_settings': settings, 'media_reference': reference, 'source_metadata': package['metadata'],
                    'summary': summary, 'piece_index': piece_index, 'renderer_fingerprint': renderer_fingerprint(),
                    'piece_index_sha256': _digest(piece_index),
                    'visual_index_sha256': file_hash(work / 'visual_evidence_index.json')}}
            project.save()
            project.plan['production_import']['evidence_sha256'] = file_hash(work / 'evidence.json')
            project.save()
            _cancelled(cancel)
            journal['state'] = 'VALIDATED'
            write_json(transaction / 'TRANSACTION.json', journal)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError('Revisão já existente; staging preservado')
            # Same-volume directory rename publishes the complete revision once.
            work.rename(destination)
            journal['state'] = 'COMMITTED'
            write_json(transaction / 'TRANSACTION.json', journal)
            project.directory = destination
            progress(1, 'Importado; revisão humana obrigatória')
            log('Projeto externo: ' + str(destination))
            return {'production_import': True, 'project': project,
                'source_path': Path(reference['path']) if reference['path'] else None, 'summary': summary}
        except Exception as exc:
            journal.update(state='INTERRUPTED' if isinstance(exc, OperationCancelled) else 'FAILED', error=str(exc),
                rollback='Nenhuma revisão anterior foi alterada; staging preservado para inspeção')
            write_json(transaction / 'TRANSACTION.json', journal)
            raise


class ProductionProject(SeriesProject):
    """Gates and locks around the existing renderer and immutable edit history."""
    @contextmanager
    def _operation(self):
        with project_lock(self.directory):
            if load_json(self.directory / 'series_index.json') != self.plan:
                raise ValueError('Projeto mudou em outra instância; reabra antes de continuar')
            yield

    def _gate(self, episode):
        origin = episode.get('production_origin_id')
        if not origin or origin not in self.plan['production_import']['piece_index']:
            raise ValueError('Peça derivada sem vínculo de origem; revisão de importação necessária')
        gate = episode.get('production_caption_gate') or {}
        piece = self.plan['production_import']['piece_index'][origin]
        raw = piece.get('raw_proposal') or {}
        if set(raw.get('blockers') or []) & {'human_audio_review_pending', 'source_transcript_uncertain', 'audio_review_required'}:
            raise ValueError('Peça bloqueada: AUDIO_REVIEW_REQUIRED: pendência explícita do Analyzer')
        if not gate.get('renderable'):
            raise ValueError('Peça bloqueada: ' + str(gate.get('state', 'BLOCKED')) + ': ' + str(gate.get('reason')))

    def _verify_caption_revision(self, episode):
        frozen = (episode.get('caption_revision') or {}).get('production_non_speech')
        if frozen:
            proof = _non_speech_proof(episode, self.evidence, frozen['state'])
            if proof != frozen or episode.get('subtitle_preset') != 'SEM_LEGENDA':
                raise ValueError('Evidência positiva de ausência de fala mudou; revisão necessária')
            return
        return super()._verify_caption_revision(episode)

    def prepare_caption_timeline(self, episode_id):
        episode = self.episode(episode_id)
        frozen = (episode.get('caption_revision') or {}).get('production_non_speech')
        if not frozen:
            return super().prepare_caption_timeline(episode_id)
        self._verify_caption_revision(episode)
        from .subtitle_presets import (write_episode_subtitles, resolve_subtitle_preset,
            _transcript_reference, canonical_timeline_hash, ENGINE_VERSION)
        start, end = episode['source_start'], episode['source_end']
        segments = sorted([r for r in self.evidence.get('segments', []) if r['end'] > start and r['start'] < end], key=lambda r: (r['start'], r['end']))
        canonical = {'engine_version': ENGINE_VERSION, 'source_start': start, 'source_end': end,
            'preset': resolve_subtitle_preset('SEM_LEGENDA', episode.get('subtitle_overrides')),
            'transcript_reference': _transcript_reference(segments, self.evidence.get('words', []), episode, self.evidence),
            'events': [], 'segments': [], 'diagnostics': [], 'canonical_timeline_sha256': canonical_timeline_hash([]),
            'positive_non_speech_evidence': frozen}
        directory = self.folder(episode) / self.signature(episode)[:16] / 'caption_plan'
        return write_episode_subtitles(self.evidence, episode, directory, preset='SEM_LEGENDA',
            overrides=episode.get('subtitle_overrides'), canonical_timeline=canonical, width=540, height=960)

    def render(self, episode_id, source_path, *, preview=True):
        with self._operation():
            self._gate(self.episode(episode_id))
            return super().render(episode_id, source_path, preview=preview)

    def approve(self, episode_id, **kwargs):
        with self._operation():
            self._gate(self.episode(episode_id))
            return super().approve(episode_id, **kwargs)

    def _editor_command(self, revised, action, *, explicit=(), details=None):
        old = {e['episode_id']: e for e in self.episodes()}
        for episode in [e for key in ('episodes', 'extras') for e in revised.get(key, [])]:
            parent = old.get(episode['episode_id']) or old.get(episode.get('revision_of'))
            if not parent:
                # A merge/split must never discard a blocked upstream origin.
                episode['production_caption_gate'] = {'state': 'BLOCKED', 'renderable': False, 'reason': 'DERIVED_ASSEMBLY_REQUIRES_REVIEW'}
                continue
            for field in ('production_origin_id', 'piece_kind', 'caption_preflight', 'caption_plan', 'raw_proposal', 'source_intervals', 'assembly_disclosure_required'):
                if field in parent:
                    episode[field] = deepcopy(parent[field])
            same_window = all(episode.get(k) == parent.get(k) for k in ('source_start', 'source_end'))
            same_camera = same_window and all(episode.get(k) == parent.get(k) for k in ('camera_mode', 'camera_keyframes'))
            if same_camera:
                episode['camera_plan'] = deepcopy(parent.get('camera_plan'))
            elif episode.get('camera_mode') == 'AUTO_CONSERVADOR':
                index = self._visual_index()
                episode['camera_plan'] = build_piece_camera(index, episode, self.plan['production_import']['source_metadata'], self.cfg)
            episode['production_caption_gate'] = caption_preflight(episode, self.evidence)
            if episode['production_caption_gate'].get('renderable') and episode['production_caption_gate']['state'] in {'NO_SPEECH', 'INSTRUMENTAL'}:
                episode['subtitle_preset'] = 'SEM_LEGENDA'
                episode['caption_revision'] = {'production_non_speech': episode['production_caption_gate']['evidence']}
            if episode.get('piece_kind') != 'REEL' and episode['duration'] > 59.5:
                episode['production_caption_gate'] = {'state': 'BLOCKED', 'renderable': False, 'reason': 'STORY_EXCEEDS_59_5_SECONDS'}
        return super()._editor_command(revised, action, explicit=explicit, details=details)

    def _visual_index(self):
        path = self.directory / 'visual_evidence_index.json'
        if file_hash(path) != self.plan['production_import']['visual_index_sha256']:
            raise ValueError('Índice visual mudou após importação')
        return load_json(path)

    def edit(self, episode_id, **changes):
        with self._operation():
            return super().edit(episode_id, **changes)

    def undo(self):
        with self._operation():
            return super().undo()

    def redo(self):
        with self._operation():
            return super().redo()

    def reject(self, episode_id):
        with self._operation():
            return super().reject(episode_id)

    def reorder(self, episode_ids, **kwargs):
        with self._operation():
            return super().reorder(episode_ids, **kwargs)

    def split(self, episode_id, *args, **kwargs):
        with self._operation():
            return super().split(episode_id, *args, **kwargs)

    def merge(self, episode_ids, *args, **kwargs):
        with self._operation():
            return super().merge(episode_ids, *args, **kwargs)

    def export(self):
        with self._operation():
            from .production_dossier import export_production_dossier
            from .full_handoff import export_handoff
            dossier = export_production_dossier(self)
            assets = {'REPORTS/DOSSIE_SEGUNDA_CURADORIA.pdf': Path(dossier['path'])}
            for item in self._visual_index().get('assets', {}).values():
                if item.get('path') and Path(item['path']).is_file():
                    path = Path(item['path'])
                    if file_hash(path) != item['sha256']:
                        raise ValueError('Asset visual mudou após importação')
                    assets['VISUAL_EVIDENCE/' + item['sha256'][:12] + '_' + path.name] = path
            return export_handoff(self.evidence, self.plan, self.directory / 'CHATGPT_HANDOFF', media_paths=assets)


def load_production_project(directory, *, log=print, progress=None, cancel=None):
    directory = _outside_repository(directory)
    plan = load_json(directory / 'series_index.json', {})
    imported = plan.get('production_import') or {}
    if imported.get('schema') != 'LDP_PRODUCTION_IMPORT_V1':
        raise ValueError('Projeto não contém uma importação de produção compatível')
    project = ProductionProject(directory, imported['render_settings'], log=log, progress=progress, cancel=cancel)
    if project.evidence.get('source', {}).get('sha256') != plan.get('source_sha256'):
        raise ValueError('Evidências e projeto pertencem a fontes diferentes')
    if imported.get('evidence_sha256') and file_hash(directory / 'evidence.json') != imported['evidence_sha256']:
        raise ValueError('Evidência mudou após importação; revisão preservada para inspeção')
    if imported.get('piece_index_sha256') and _digest(imported['piece_index']) != imported['piece_index_sha256']:
        raise ValueError('Vínculos de origem das peças mudaram após importação')
    project._visual_index()
    return project


def render_production_previews(project, media, *, log=print, progress=None, cancel=None):
    """Independent eligibility and failures; cancellation preserves finished rows."""
    rows = []
    for i, episode in enumerate(project.episodes()):
        _cancelled(cancel or project.cancel)
        row = {'episode_id': episode['episode_id']}
        gate = episode.get('production_caption_gate') or {}
        if not gate.get('renderable'):
            row.update(status='BLOCKED', reason=gate.get('reason'), caption_state=gate.get('state'))
        else:
            try:
                output = project.render(episode['episode_id'], media, preview=True)
                row.update(status='VALIDATED', path=str(output), sha256=file_hash(output), human_approved=False)
            except OperationCancelled:
                raise
            except Exception as exc:
                row.update(status='FAILED', reason=str(exc))
        rows.append(row)
        log(row['episode_id'] + ': ' + row['status'])
        if progress:
            progress((i + 1) / max(1, len(project.episodes())), row['status'])
    report = {'schema': 'LDP_PRODUCTION_BATCH_V1', 'rows': rows, 'counts': dict(Counter(row['status'] for row in rows))}
    directory = project.directory / 'batch_reports'
    write_json(directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid4().hex[:8] + '.json'), report)
    return report
