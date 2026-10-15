from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
import uuid

from .analysis_loader import find_analysis, load_bundle
from .approval import file_hash, record_preview, approve_preview, approval_matches
from .camera import build_camera_plan
from .curator import curate
from .persisted_plan import (PlanStore, DOCUMENT_TYPE, project_lock, render_fingerprint,
                             compare_settings, _atomic_json, _fingerprint, canonical, _differences,
                             StalePlanError)
from .render import render_clip
from .review import build_board, write_handoff
from .source_video import resolve_source, SourceUnavailable
from .thumbnails import create_assets
from .utils import load_json, write_json, youtube_id, safe_name, run


@lru_cache(maxsize=1)
def _ffmpeg_version():
    return run(['ffmpeg', '-version']).stdout.splitlines()[0]


def renderer_signature():
    folder = Path(__file__).parent
    return _fingerprint({'ffmpeg': _ffmpeg_version(), 'code': {
        name: file_hash(folder / name) for name in
        ('render.py', 'subtitles.py', 'title_card.py', 'subtitle_presets.py', 'title_presets.py')}})


class Pipeline:
    """CURAR creates a revision; the remaining buttons consume its frozen inputs."""

    def __init__(self, cfg, project_root: Path, log=print, progress=None):
        self.cfg = deepcopy(cfg)
        self.root = Path(project_root).resolve()
        self.log = log
        self.progress = progress or (lambda event: None)

    @property
    def curation_root(self):
        return Path(self.cfg['paths']['output_root']).resolve() / 'curation'

    def _emit(self, plan, step, label, fraction=0.0, detail='', status='running', operation_label='Processando...'):
        total = max(1, len(plan))
        frac = None if fraction is None else max(0.0, min(1.0, float(fraction)))
        overall = ((step - 1) + (frac or 0.0)) / total
        if status in {'done', 'completed'} and step >= total:
            overall = 1.0
        self.progress({'stage': f'{step}:{label}', 'label': label, 'step': step, 'total_steps': total,
                       'stage_fraction': frac, 'overall_fraction': max(0.0, min(1.0, overall)),
                       'detail': detail, 'status': status, 'plan': plan, 'operation_label': operation_label})

    def _state(self, doc, operation, reason=None):
        approved_revision = ((doc.get('approval_record') or {}).get('binding') or {}).get('plan_revision')
        event = {'event': 'plan_state', 'project_id': doc.get('project_id'),
                 'plan_revision': doc.get('plan_revision'), 'plan_fingerprint': doc.get('plan_signature'),
                 'approved_revision': approved_revision,
                 'operation': operation, 'approval_state': doc.get('approval_state', 'NO_PLAN'),
                 'invalidation_reason': reason or doc.get('invalidation_reason')}
        self.progress(event)
        self.log('PLANO ' + json.dumps(event, ensure_ascii=False, sort_keys=True))

    def _project_dir(self, source_input):
        target = youtube_id(source_input)
        if target and (self.curation_root / target / 'EDIT_DECISIONS.json').is_file():
            return self.curation_root / target
        # Bounded local lookup, never an Analyzer scan or model call.
        matches = []
        for pointer in self.curation_root.glob('*/EDIT_DECISIONS.json'):
            doc = load_json(pointer, {}) or {}
            aliases = doc.get('source_aliases', []) + [doc.get('source_input'), doc.get('video_id'),
                                                       (doc.get('source') or {}).get('url')]
            if str(source_input) in aliases:
                matches.append(pointer.parent)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError('Mais de um projeto corresponde à entrada; informe o ID do vídeo.')
        raise FileNotFoundError('SEM_PLANO: execute CURAR primeiro ou informe o ID do projeto salvo.')

    def _load(self, base, source_input, operation):
        store = PlanStore(base)
        old = load_json(store.pointer, {}) or {}
        if old.get('document_type') != DOCUMENT_TYPE:
            from .pipeline_recovery import recover_local_plan
            doc, bundle = recover_local_plan(base, self.cfg, source_input, self.root)
        else:
            try:
                doc, bundle = store.load(check_settings=False)
            except (ValueError, RuntimeError, FileNotFoundError) as error:
                invalid = deepcopy(old)
                invalid['approval_state'] = 'APPROVAL_INVALIDATED'
                self._state(invalid, operation, str(error))
                raise
        try:
            compare_settings(doc, self.cfg)
        except ValueError as error:
            invalid = deepcopy(doc)
            invalid['approval_state'] = 'APPROVAL_INVALIDATED'
            self._state(invalid, operation, str(error))
            raise
        if doc.get('approval_state') == 'BATCH_RENDERING':
            # Every caller holds project_lock. Successfully acquiring it proves
            # there is no compatible live worker still rendering this revision.
            doc = self._recover_batch_state(
                store, doc, operation, 'Lote interrompido antes de concluir; resultados completos não foram publicados.',
                interrupted=True)
        self._state(doc, operation)
        return store, doc, bundle

    def _verified_batch_artifacts(self, doc, artifacts):
        expected_root = (Path(self.cfg['paths']['output_root']).resolve() / 'renders'
                         / safe_name(doc['project_id']) / 'revisions' / doc['plan_revision'])
        verified = []
        for artifact in artifacts:
            path = Path(artifact.get('path', '')).resolve()
            if (artifact.get('plan_revision') != doc['plan_revision']
                    or not path.is_relative_to(expected_root) or not path.is_file()):
                continue
            try:
                matches = file_hash(path) == artifact.get('sha256')
            except OSError:
                matches = False
            if matches:
                verified.append({**deepcopy(artifact), 'sha256_verified': True})
        return verified

    def _recover_batch_state(self, store, doc, operation, message, *, artifacts=None, interrupted=False,
                             error_type=None):
        # Use the authoritative pointer, not an unsaved BATCH_COMPLETED mutation
        # or an old worker's cached results. Never write across a revision/version CAS.
        active, _ = store.load(check_settings=False)
        if (active['plan_revision'] != doc['plan_revision']
                or active['state_version'] != doc['state_version']):
            raise StalePlanError('Lote obsoleto: outra revisão ou estado está ativo; recuperação descartada.')
        attempt = active.get('active_batch') or {}
        partial = self._verified_batch_artifacts(
            active, artifacts if artifacts is not None else attempt.get('partial_artifacts', []))
        invalidation = None
        source_path = active.get('source_media_path')
        if source_path and Path(source_path).is_file() and active.get('source_media_sha256'):
            if file_hash(source_path) != active['source_media_sha256']:
                invalidation = 'source_media.sha256 mudou durante o lote; gere e revise nova prévia do original correto.'
        require_approval = self.cfg.get('safety', {}).get('require_first_test_approval_before_batch', True)
        if invalidation is None and require_approval and active.get('approval_record'):
            try:
                record, _ = self._validate_preview(active)
                folder = store.revision_dir(active)
                if (record != active['approval_record']
                        or not (folder / 'FIRST_TEST_APPROVED.flag').is_file()
                        or not approval_matches(folder, record['plan_signature'])
                        or load_json(folder / 'FIRST_TEST_APPROVED_V44.json', {}) != record):
                    raise ValueError('Registro de aprovação mudou durante o lote.')
            except (ValueError, OSError) as error:
                invalidation = str(error)
        if invalidation is not None:
            active.update(approval_state='APPROVAL_INVALIDATED', invalidation_reason=invalidation)
        elif require_approval and active.get('approval_record'):
            active.update(approval_state='TEST_APPROVED', invalidation_reason=None)
        else:
            active.update(approval_state='PLAN_READY', invalidation_reason=None)
        history = {'batch_id': attempt.get('batch_id'), 'plan_revision': active['plan_revision'],
                   'status': 'INTERRUPTED' if interrupted else 'FAILED', 'error': str(message),
                   'error_type': error_type, 'partial_artifacts': partial,
                   'approval_preserved': active['approval_state'] == 'TEST_APPROVED'}
        active.setdefault('batch_history', []).append(history)
        active['last_batch_error'] = {key: value for key, value in history.items() if key != 'partial_artifacts'}
        active['active_batch'] = None
        active = store.save_state(active)
        self._state(active, operation, invalidation or str(message))
        return active

    def read_state(self, source_input):
        base = self._project_dir(source_input)
        with project_lock(base):
            _, doc, _ = self._load(base, source_input, 'read')
            return doc

    def recover_legacy(self, source_input):
        base = self._project_dir(source_input)
        with project_lock(base):
            _, doc, bundle = self._load(base, source_input, 'recover')
            return bundle, deepcopy(doc['approved_clips']), base

    def revise_plan(self, source_input, decisions=None, render_config=None):
        """Explicit editing/configuration revision, using cached evidence without Qwen."""
        base = self._project_dir(source_input)
        with project_lock(base):
            store = PlanStore(base)
            old, bundle = store.load(check_settings=False)
            cfg = deepcopy(render_config if render_config is not None else self.cfg)
            selected = deepcopy(decisions if decisions is not None else old['approved_clips'])
            ids = [clip.get('clip_id') for clip in selected]
            if len(set(ids)) != len(ids) or any(not item or safe_name(item) != item for item in ids):
                raise ValueError('IDs de cortes devem ser únicos e seguros.')
            for clip in selected:
                start, end = float(clip['source_start']), float(clip['source_end'])
                if start < 0 or end <= start or abs(float(clip['duration']) - (end - start)) > .001:
                    raise ValueError('Timestamps/duration inválidos: ' + clip['clip_id'])
            doc, _ = store.create(bundle, selected, cfg, source_input)
            changed = _differences(old['approved_clips'], selected, 'clips')
            changed += _differences(old['render_settings'], doc['render_settings'], 'settings')
            doc.update(previous_revision=old['plan_revision'],
                       source_media_path=old.get('source_media_path'),
                       source_media_sha256=old.get('source_media_sha256'),
                       invalidation_reason='Edição explícita: ' + ', '.join(changed or ['nova revisão'])
                       + '; aprovada anteriormente: ' + old['plan_revision'] + '; ativa: ' + doc['plan_revision']
                       + '. Gere nova prévia e aprove; nova curadoria não é necessária.')
            doc = store.save_state(doc)
            write_handoff(bundle, selected, store.revision_dir(doc))
            self._state(doc, 'revise')
            return doc

    def _video(self, bundle, source_input, doc=None):
        paths = [self.cfg.get('source_media', {}).get('path'), source_input,
                 (doc or {}).get('source_media_path')]
        meta = bundle.analysis.get('metadata') or {}
        filename = (meta.get('source') or {}).get('filename') or meta.get('filename')
        if filename and Path(filename).name == filename:
            # Only known direct media references; no recursive Analyzer traversal.
            paths.extend([bundle.root / filename, bundle.root.parent / filename])
        cache = Path(self.cfg['paths']['source_cache'])
        paths.extend(sorted(cache.glob(f'{safe_name(bundle.video_id)}.*')))
        for item in paths:
            if not item:
                continue
            path = Path(item)
            if not path.is_file() or path.suffix.lower() not in {'.mp4', '.mkv', '.webm', '.mov'}:
                continue
            sha = file_hash(path)
            declared = meta.get('sha256')
            pinned = (doc or {}).get('source_media_sha256')
            if declared and sha != declared:
                raise ValueError('source_media.sha256 mudou: mídia não corresponde à análise original.')
            if pinned and sha != pinned:
                raise ValueError('source_media.sha256 mudou: gere nova revisão e prévia do original correto.')
            return path.resolve(), sha
        if self.cfg.get('source_media', {}).get('allow_download', False):
            # resolve_source sees only the cached revision, never an Analyzer root.
            frozen = deepcopy(bundle)
            frozen.root = self.curation_root / safe_name(bundle.video_id) / 'media_references'
            path = resolve_source(frozen, bundle.source.get('url') or source_input, self.cfg, self.log)
            sha = file_hash(path)
            if (doc or {}).get('source_media_sha256') not in {None, sha}:
                raise ValueError('source_media.sha256 mudou após o download; aprovação inválida.')
            return path, sha
        raise SourceUnavailable('Mídia original indisponível. Selecione o original ou autorize o download; '
                                'o plano persistido será reutilizado sem Qwen ou reprocessamento.')

    def _prepare_curation(self, source_input, plan, step_map, operation_label):
        from .second_curation_import import registered_input
        s = step_map
        self._emit(plan, s['analysis'], 'Localizando análise concluída', .05, source_input, operation_label=operation_label)
        imported = registered_input(self.root, source_input)
        ar = Path(imported['analysis_dir']) if imported else find_analysis(self.cfg['paths']['analysis_root'], source_input)
        self.log(f'Análise encontrada: {ar}')
        self._emit(plan, s['analysis'], 'Localizando análise concluída', 1., str(ar), operation_label=operation_label)
        bundle = load_bundle(ar)
        if imported and imported.get('decision_path'):
            bundle.second_decisions = load_json(imported['decision_path'], {})
        self._emit(plan, s['load'], 'Carregando dados existentes', 1., bundle.video_id, operation_label=operation_label)
        out = self.curation_root / safe_name(bundle.video_id)
        with project_lock(out):
            previous = load_json(out / 'EDIT_DECISIONS.json', {}) or {}
            decisions = curate(bundle, self.cfg, self.root, log=self.log)
            editorial_response = next((clip.get('phase2_ollama_meta') for clip in decisions
                                       if clip.get('phase2_ollama_meta', {}).get('editorial_response')), None)
            if editorial_response:
                bundle.review = deepcopy(bundle.review)
                bundle.review['curator_phase2_response'] = deepcopy(editorial_response)
            self.progress({'event': 'eta_context', 'metadata': bundle.analysis.get('metadata', {}),
                           'clips': decisions, 'operation': operation_label})
            self.progress({'event': 'curation_source', 'curation_source': decisions[0].get('curation_source', 'FIRST_PASS') if decisions else 'FIRST_PASS'})
            self._emit(plan, s['curate'], 'Aplicando curadoria', 1., f'{len(decisions)} cortes', operation_label=operation_label)
            ids = [item.get('clip_id') for item in decisions]
            if len(set(ids)) != len(ids) or any(not item or safe_name(item) != item for item in ids):
                raise ValueError('IDs de cortes devem ser únicos e seguros.')
            try:
                video, media_sha = self._video(bundle, source_input)
            except SourceUnavailable:
                video, media_sha = None, None
            work = out / 'planning' / uuid.uuid4().hex
            for index, clip in enumerate(decisions, 1):
                clip['camera_plan'] = build_camera_plan(bundle, clip, self.cfg)
                clip.setdefault('subtitle_plan', {'format': 'ASS', 'max_lines': 2, 'word_highlight': True})
                clip.setdefault('thumbnail_plan', {'opening_frame': True, 'best': True, 'clean': True})
                # Technical refinement is a planning decision. Freeze it here,
                # once, before any preview/approval; downstream never replans.
                if video is not None and self.cfg.get('camera', {}).get('v44_refinement', True):
                    from .final_camera import refine_clip
                    cd = work / 'clips' / clip['clip_id']
                    cd.mkdir(parents=True, exist_ok=True)
                    refine_clip(bundle, clip, video, cd, self.cfg)
                self._emit(plan, s['plans'], 'Congelando câmera e planos', index / max(1, len(decisions)),
                           f'corte {index}/{len(decisions)}', operation_label=operation_label)
            if video is not None and file_hash(video) != media_sha:
                raise ValueError('source_media.sha256 mudou durante a curadoria; nenhuma revisão publicada.')
            store = PlanStore(out)
            doc, frozen = store.create(bundle, decisions, self.cfg, source_input)
            doc.update(source_media_path=str(video) if video else None, source_media_sha256=media_sha,
                       planning_evidence=str(work.relative_to(out)) if work.exists() else None)
            if previous.get('plan_revision'):
                doc['previous_revision'] = previous['plan_revision']
                doc['invalidation_reason'] = ('Nova CURAR explícita criou outra revisão; a aprovação da revisão '
                                              + previous['plan_revision'] + ' permanece no histórico.')
            doc = store.save_state(doc)
            revision = store.revision_dir(doc)
            if editorial_response:
                _atomic_json(revision / 'EDITORIAL_RESPONSE.json', editorial_response)
            write_handoff(frozen, decisions, revision)
            report = ['# L.D.PORTO — CURATION REPORT', '', f'Projeto: {bundle.video_id}',
                      f'Revisão: {doc["plan_revision"]}', f'Cortes: {len(decisions)}',
                      'Aprovação humana do preview pendente.', '']
            for clip in decisions:
                report.extend([f'## #{clip["rank"]} {clip["clip_id"]} — {clip.get("title_text", "")}',
                               f'- {clip["source_start"]:.2f}s → {clip["source_end"]:.2f}s',
                               f'- Motivo: {clip.get("reason", "")}', ''])
            (revision / 'CURATION_REPORT.md').write_text('\n'.join(report), encoding='utf-8')
            self.log(f'Curadoria: {len(decisions)} cortes selecionados para revisão.')
            self._state(doc, 'curate')
            return frozen, deepcopy(decisions), out

    def curate_only(self, source_input):
        plan = ['Localizar análise', 'Carregar dados', 'Curadoria', 'Congelar planos', 'Salvar revisão']
        result = self._prepare_curation(source_input, plan, {'analysis': 1, 'load': 2, 'curate': 3, 'plans': 4}, 'Curando vídeo...')
        self._emit(plan, 5, 'Salvar revisão', 1., status='done')
        return result

    def _render_cfg(self, doc):
        cfg = deepcopy(doc['render_config'])
        # Routing may change without altering pixels. Effects always stay pinned.
        cfg['paths'] = deepcopy(self.cfg['paths'])
        return cfg

    def _binding(self, doc, clip_id, media_sha):
        return {'project_id': doc['project_id'], 'plan_revision': doc['plan_revision'],
                'source_fingerprint': doc['source_fingerprint'],
                'editorial_plan_fingerprint': doc['editorial_plan_fingerprint'],
                'source_media_sha256': media_sha,
                'preview_render_fingerprint': render_fingerprint(doc, clip_id, media_sha, renderer_signature())}

    def _validate_preview(self, doc, operation=None):
        try:
            return self._checked_preview(doc)
        except (ValueError, OSError) as error:
            invalid = deepcopy(doc)
            invalid['approval_state'] = 'APPROVAL_INVALIDATED'
            self._state(invalid, operation or 'validate', str(error))
            raise

    def _checked_preview(self, doc):
        record = doc.get('preview') or {}
        binding = record.get('binding') or {}
        expected = self._binding(doc, record.get('reviewed_clip_id'), doc.get('source_media_sha256'))
        if binding != expected:
            changed = [key for key in expected if expected.get(key) != binding.get(key)]
            raise ValueError('Identidade da prévia mudou: ' + ', '.join(changed) + '. Gere nova prévia.')
        path = Path(record.get('path', ''))
        if not path.is_file() or file_hash(path) != record.get('sha256'):
            raise ValueError('preview_media_sha256 mudou ou MP4 está ausente; gere nova prévia.')
        sidecar = Path(record.get('render_metadata_path', ''))
        if not sidecar.is_file() or file_hash(sidecar) != record.get('render_metadata_sha256'):
            raise ValueError('Configuração efetivamente renderizada mudou: render_metadata_sha256.')
        actual = load_json(sidecar, {}) or {}
        if actual.get('media_sha256') != record['sha256'] or not actual.get('preview'):
            raise ValueError('Metadados não identificam o MP4 de prévia aprovado.')
        clip = next(row for row in doc['approved_clips'] if row['clip_id'] == record['reviewed_clip_id'])
        cfg = doc['render_config']
        rendered = {'source_start': float(clip['source_start']), 'duration': float(clip['duration']),
                    'width': int(cfg['render'].get('preview_width', 540)),
                    'height': int(cfg['render'].get('preview_height', 960)),
                    'render_settings_fingerprint': _fingerprint(doc['render_settings'])}
        changed = [key for key, value in rendered.items() if canonical(actual.get(key)) != canonical(value)]
        if changed:
            raise ValueError('Configuração efetivamente renderizada mudou: ' + ', '.join(changed))
        if actual.get('encoder') not in {'libx264', 'h264_nvenc'}:
            raise ValueError('Encoder efetivamente renderizado não reconhecido.')
        return record, expected

    def test_one(self, source_input, rank=1):
        base = self._project_dir(source_input)
        with project_lock(base):
            store, doc, bundle = self._load(base, source_input, 'test')
            decisions = deepcopy(doc['approved_clips'])
            clip = next((row for row in decisions if row.get('rank') == int(rank)), None)
            if clip is None:
                raise ValueError(f'Rank {rank} não existe na revisão; nenhum corte foi substituído.')
            video, sha = self._video(bundle, source_input, doc)
            doc.update(source_media_path=str(video), source_media_sha256=sha)
            running = deepcopy(doc)
            running['approval_state'] = 'GENERATING_PREVIEW'
            self._state(running, 'test')
            run_id = uuid.uuid4().hex
            revision = store.revision_dir(doc)
            cd = revision / 'clips' / clip['clip_id'] / 'previews' / run_id
            cfg = self._render_cfg(doc)
            clip.setdefault('thumbnail_plan', {}).update(create_assets(bundle, clip, video, cd, cfg))
            write_json(cd / 'clip.json', clip)
            rd = Path(cfg['paths']['output_root']) / 'renders' / safe_name(bundle.video_id) / 'revisions' / doc['plan_revision'] / clip['clip_id'] / 'previews' / run_id
            mp4 = render_clip(bundle, clip, video, rd, cfg, preview=True, log=self.log,
                              progress=lambda f, d='': self._emit(['Gerar assets', 'Renderizar prévia', 'Salvar teste'], 2, 'Renderizar prévia', f, d))
            if file_hash(video) != sha:
                raise ValueError('source_media.sha256 mudou durante o render; prévia não vinculada.')
            binding = self._binding(doc, clip['clip_id'], sha)
            metadata = Path(str(mp4) + '.render.json')
            record = record_preview(revision, mp4, binding['preview_render_fingerprint'], clip['clip_id'], binding)
            record.update(render_metadata_path=str(metadata.resolve()), render_metadata_sha256=file_hash(metadata),
                          preview_media_sha256=record['sha256'])
            _atomic_json(revision / 'PREVIEW_REVIEW_V44.json', record)
            doc.update(preview=record, approval_record=None, approval_state='PREVIEW_READY', invalidation_reason=None)
            doc.setdefault('assets', {})[clip['clip_id']] = (cd / 'thumbnails/thumbnail_best.jpg').relative_to(revision).as_posix()
            doc = store.save_state(doc)
            build_board(decisions, revision, doc.get('assets'))
            self._state(doc, 'test')
            self.log(f'TESTE DE 1 CORTE PRONTO: {mp4}')
            self._emit(['Gerar assets', 'Renderizar prévia', 'Salvar teste'], 3, 'Salvar teste', 1., str(mp4), status='done')
            return mp4, base

    def approve_test(self, source_input):
        base = self._project_dir(source_input)
        with project_lock(base):
            store, doc, bundle = self._load(base, source_input, 'approve')
            if doc.get('approval_state') not in {'PREVIEW_READY', 'TEST_APPROVED'}:
                raise ValueError('Gere e revise uma prévia desta revisão antes de APROVAR TESTE.')
            record, binding = self._validate_preview(doc)
            disk = load_json(store.revision_dir(doc) / 'PREVIEW_REVIEW_V44.json', {})
            if disk != record:
                raise ValueError('Registro da prévia mudou: PREVIEW_REVIEW_V44.json.')
            approved = approve_preview(store.revision_dir(doc), record['plan_signature'], binding)
            doc.update(approval_record=approved, approval_state='TEST_APPROVED', invalidation_reason=None)
            doc = store.save_state(doc)
            self._state(doc, 'approve')
            self._emit(['Validar prévia', 'Registrar aprovação'], 2, 'Registrar aprovação', 1.,
                       'Revisão aprovada: ' + doc['plan_revision'], status='done')
            return base

    def render_all(self, source_input, preview=False):
        base = self._project_dir(source_input)
        with project_lock(base):
            store, doc, bundle = self._load(base, source_input, 'batch')
            if self.cfg.get('safety', {}).get('require_first_test_approval_before_batch', True):
                try:
                    if doc.get('approval_state') not in {'TEST_APPROVED', 'BATCH_RENDERING', 'BATCH_COMPLETED'} or not doc.get('approval_record'):
                        raise ValueError('Primeiro teste desta revisão não foi aprovado. Use TESTAR 1 CORTE, revise o MP4 e clique APROVAR TESTE.')
                    record, _ = self._checked_preview(doc)
                    if doc['approval_record'] != record:
                        raise ValueError('approval_record não corresponde à prévia da revisão ativa.')
                    folder = store.revision_dir(doc)
                    if not (folder / 'FIRST_TEST_APPROVED.flag').is_file() or not approval_matches(folder, record['plan_signature']):
                        raise ValueError('Registro persistido de aprovação ausente ou incompatível nesta revisão.')
                    if load_json(folder / 'FIRST_TEST_APPROVED_V44.json', {}) != doc['approval_record']:
                        raise ValueError('Registro de aprovação mudou: FIRST_TEST_APPROVED_V44.json.')
                except (ValueError, OSError) as error:
                    invalid = deepcopy(doc)
                    if doc.get('approval_record'):
                        invalid['approval_state'] = 'APPROVAL_INVALIDATED'
                    self._state(invalid, 'batch', str(error))
                    raise
            try:
                video, sha = self._video(bundle, source_input, doc)
            except ValueError as error:
                invalid = deepcopy(doc)
                invalid.update(approval_state='APPROVAL_INVALIDATED', invalidation_reason=str(error))
                invalid = store.save_state(invalid)
                self._state(invalid, 'batch', str(error))
                raise
            run_id = uuid.uuid4().hex
            doc.update(approval_state='BATCH_RENDERING', source_media_path=str(video), source_media_sha256=sha,
                       active_batch={'batch_id': run_id, 'partial_artifacts': [], 'preview': bool(preview)})
            doc = store.save_state(doc)
            self._state(doc, 'batch')
            decisions = deepcopy(doc['approved_clips'])
            cfg, revision = self._render_cfg(doc), store.revision_dir(doc)
            results, details = [], []
            plan = [f'Render corte {index}/{len(decisions)}' for index in range(1, len(decisions) + 1)] + ['Salvar lote']
            try:
                for index, clip in enumerate(decisions, 1):
                    cd = revision / 'clips' / clip['clip_id'] / 'batches' / run_id
                    clip.setdefault('thumbnail_plan', {}).update(create_assets(bundle, clip, video, cd, cfg))
                    write_json(cd / 'clip.json', clip)
                    doc.setdefault('assets', {})[clip['clip_id']] = (cd / 'thumbnails/thumbnail_best.jpg').relative_to(revision).as_posix()
                    rd = Path(cfg['paths']['output_root']) / 'renders' / safe_name(bundle.video_id) / 'revisions' / doc['plan_revision'] / clip['clip_id'] / 'batches' / run_id
                    mp4 = render_clip(bundle, clip, video, rd, cfg, preview=preview, log=self.log,
                                      progress=lambda f, d='', i=index: self._emit(plan, i, plan[i - 1], f, d))
                    if file_hash(video) != sha:
                        raise ValueError('source_media.sha256 mudou durante o lote; resultado não aprovado.')
                    results.append(mp4)
                    details.append({'path': str(mp4.resolve()), 'sha256': file_hash(mp4), 'clip_id': clip['clip_id'],
                                    'plan_revision': doc['plan_revision'], 'batch_id': run_id,
                                    'source_media_sha256': sha, 'render_validated': True})
                    doc['active_batch']['partial_artifacts'] = deepcopy(details)
                    doc = store.save_state(doc)
                build_board(decisions, revision, doc.get('assets'))
                write_handoff(bundle, decisions, revision)
                doc['results'].extend(details)
                doc.setdefault('batch_history', []).append({
                    'batch_id': run_id, 'plan_revision': doc['plan_revision'], 'status': 'COMPLETED',
                    'partial_artifacts': self._verified_batch_artifacts(doc, details)})
                doc.update(approval_state='BATCH_COMPLETED', active_batch=None, last_batch_error=None)
                doc = store.save_state(doc)
            except StalePlanError:
                # Outputs remain under their own revision/run for traceability;
                # an obsolete worker cannot restore approval or overwrite state.
                raise
            except Exception as error:
                try:
                    self._recover_batch_state(store, doc, 'batch', str(error), artifacts=details,
                                              error_type=type(error).__name__)
                except StalePlanError:
                    self.log('Recuperação do lote descartada: revisão ou estado obsoleto.')
                except Exception as recovery_error:
                    self.log('Estado do lote não pôde ser recuperado: ' + str(recovery_error))
                raise
            self._state(doc, 'batch')
            self._emit(plan, len(plan), 'Salvar lote', 1., f'{len(results)} arquivos', status='done')
            return results, base
