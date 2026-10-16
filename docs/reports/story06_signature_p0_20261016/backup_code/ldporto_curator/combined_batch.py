"""One-click Reels + sentence-bounded Story workflow.

The Reel first-test approval never substitutes for each Story preview approval.
All visual decisions are frozen in a separate V5 Stories project, and repeated
runs reuse identical verified previews/finals rather than re-running Qwen.
"""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import hashlib
import json

from .approval import file_hash
from .utils import youtube_id, load_json, write_json, safe_name
from .episode_approval import episode_approval_matches
from .story_import import MAX_STORY_SECONDS


def _candidate_package(root, cfg, video_id, expected_sha):
    analysis_dir = Path(cfg['paths']['analysis_root']).resolve()
    folders = [analysis_dir.parent / 'pacotes_para_enviar', root / 'pacotes_para_enviar']
    # The original Analyzer archive is needed for verified segment boundaries.
    # Never accept a different YouTube download or stale analysis heuristically.
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob('SECOND_CURATION*.zip'), reverse=True)[:200]:
            if video_id not in path.name or not path.is_file():
                continue
            from .second_curation_import import read_package
            try:
                package = read_package(path)
            except (ValueError, KeyError, OSError, EOFError, json.JSONDecodeError):
                continue
            if package['metadata'].get('sha256') == expected_sha:
                return path
    raise FileNotFoundError(
        'ZIP original do Analyzer não localizado em pacotes_para_enviar. '
        'Preserve o ZIP original e importe os Stories na V5.2 antes do lote; '
        'nenhuma frase será estimada ou cortada por duração.')


def prepare_stories(pipeline, source_input):
    """Verify existing approved Reel source, then get/create separate Story project."""
    from .evidence_source import load_evidence
    from .series_workflow import SeriesProject

    state = pipeline.read_state(source_input)
    video_id = state.get('project_id') or youtube_id(source_input)
    if not video_id or not isinstance(video_id, str):
        raise ValueError('Projeto de origem sem identificador verificável')
    media_hash = state.get('source_media_sha256')
    media_path = state.get('source_media_path')
    if not isinstance(media_hash, str) or not isinstance(media_path, str) or not Path(media_path).is_file():
        raise ValueError('Selecione a mídia original no Curator; sem SHA256 não será gerado Story')
    if file_hash(Path(media_path)) != media_hash:
        raise ValueError('Mídia original mudou: SHA256 difere do plano aprovado')
    story_file = (pipeline.root / 'docs' / 'second_curation' / safe_name(video_id) /
                  'STORIES_SEQUENCIAIS_REVISAR.json')
    if not story_file.is_file():
        raise FileNotFoundError('Stories da segunda curadoria ausentes: ' + str(story_file))
    story_doc = json.loads(story_file.read_text(encoding='utf-8-sig'))

    output_root = Path(pipeline.cfg['paths']['output_root']).resolve()
    projects = output_root / 'projects' / safe_name(video_id)
    matches = []
    # Reuse a Story project already reviewed via V5.2. The source hash and
    # plan ID still have to match the current Story proposal.
    from .story_import import plan_reviewed_stories
    if projects.is_dir():
        for index in projects.glob('stories_*/series_index.json'):
            plan = load_json(index, {}) or {}
            if plan.get('source_sha256') == media_hash and plan.get('methodology') == 'verified_story_sentence_boundaries_v2':
                matches.append(index.parent)

    if matches:
        if len(matches) != 1:
            raise ValueError('Existem múltiplas revisões Stories: escolha uma na V5.2; preservadas sem alterações')
        project = SeriesProject(matches[0], pipeline.cfg, log=pipeline.log)
        if project.plan.get('source_sha256') != media_hash:
            raise ValueError('Fonte dos Stories difere do Reel')
        # Review the *signed* current proposal rather than blindly using old project.
        current = plan_reviewed_stories(project.evidence, story_doc)
        if project.plan.get('plan_id') != current['plan_id']:
            raise ValueError('Proposta de Stories mudou; importe uma nova revisão V5.2 explicitamente')
    else:
        archive = _candidate_package(pipeline.root, pipeline.cfg, video_id, media_hash)
        evidence = load_evidence(archive)
        if evidence['source']['sha256'] != media_hash:
            raise ValueError('ZIP não corresponde ao SHA256 da mídia selecionada')
        project = SeriesProject.create_stories(evidence, story_doc, output_root,
                                               pipeline.cfg, log=pipeline.log)
    return project, Path(media_path).resolve(), state


def reel_batch_complete(pipeline, source_input):
    """Skip already-finished Reels only if every final is still hash-verified."""
    state = pipeline.read_state(source_input)
    if state.get('approval_state') != 'BATCH_COMPLETED':
        return False
    revision = state.get('plan_revision')
    clips = {c['clip_id'] for c in state.get('approved_clips', [])}
    if not clips:
        return False
    results = state.get('results') or []
    verified = set()
    output_root = Path(pipeline.cfg['paths']['output_root']).resolve() / 'renders'
    for row in results:
        path = Path(row.get('path') or '').resolve()
        if (row.get('plan_revision') == revision and row.get('clip_id') in clips
                and path.is_relative_to(output_root) and path.is_file()
                and file_hash(path) == row.get('sha256')):
            verified.add(row['clip_id'])
    return verified == clips


def _story_record(episode, path, *, status):
    return {'series_id': episode['series_id'], 'part': episode['order'],
            'part_label': episode.get('episode_part_label'), 'episode_id': episode['episode_id'],
            'source_start': episode['source_start'], 'source_end': episode['source_end'],
            'duration_seconds': episode['duration'], 'title': episode.get('title_text'),
            'boundary_quality': episode.get('boundary_quality'), 'status': status,
            'file': str(path), 'sha256': file_hash(path),
            'needs_audio_review': 'source_audio_needs_review' in episode.get('risk_flags', []),
            'publication_ready': False}


# This derived revision was generated independently, because the original
# episode never acquired a valid preview. It is NOT an approval or replacement
# of the original project's frozen evidence. The combined batch references its
# verified preview as a review-only artifact.
_STORY06_ID = 'PROP_f5106b486d19e3c2e8be43ca'


def _verified_recovered_preview(project, episode, source_path, *, explicit_revision=None):
    """Return a SHA-verified, read-only standalone preview for Story 6.

    Fail closed on ambiguous revisions, stale source/parent, changed camera,
    unsupported formats or altered assets. Never merge unsigned word records
    into the original SeriesProject or claim human approval.
    """
    from .series_workflow import SeriesProject, _canonical_hash

    if episode.get('episode_id') != _STORY06_ID:
        return None
    base = project.directory.parent.resolve()
    if explicit_revision is not None:
        candidates = [Path(explicit_revision).resolve()]
    else:
        candidates = sorted(base.glob('story06_caption_recovered_*/series_index.json'))
        candidates = [p.parent for p in candidates]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError('Há múltiplas revisões recuperadas do Story 6; escolha a revisão explicitamente via script de retomada. Nada foi alterado.')
    directory = candidates[0]
    if (directory == project.directory or not directory.is_relative_to(base)
            or directory.is_symlink() or not directory.is_dir()):
        raise ValueError('Revisão recuperada fora da pasta confiável do projeto')
    saved = SeriesProject(directory, log=project.log)
    recovery = saved.plan.get('story06_recovery') or {}
    if (recovery.get('schema') != 'LDP_STORY06_UNPREVIEWED_RECOVERY_V1'
            or Path(recovery.get('parent_project', '/')).resolve() != project.directory
            or saved.plan.get('parent_plan_id') != project.plan.get('plan_id')
            or recovery.get('approved') is not False or recovery.get('qwen_executed') is not False
            or recovery.get('camera_provenance') not in {
                'new_conservative_camera_not_historically_approved',
                'original_unapproved_camera_copied'}):
        raise ValueError('Revisão de Story 6 sem vínculo/proveniência congelada verificável')
    expected_source = project.evidence.get('source', {}).get('sha256')
    if (saved.evidence.get('source', {}).get('sha256') != expected_source
            or saved.plan.get('source_sha256') != expected_source
            or recovery.get('source_sha256') != expected_source
            or file_hash(Path(source_path)) != expected_source):
        raise ValueError('Fonte SHA256 da revisão recuperada diverge do Analyzer')
    parents = recovery.get('parent_hashes') or {}
    # series_index.json legitimately changes after each preview as states and
    # review paths are saved; identity and immutable editorial fields are
    # verified below. Only the evidential files must remain byte-identical.
    for name in ('evidence.json', 'source_manifest.json'):
        file = (project.directory / name).resolve()
        if (file.is_symlink() or not file.is_file() or
                parents.get(name) != file_hash(file)):
            raise ValueError('Evidência pai mudou após recuperar o Story 6 (' + name + '). Revisão bloqueada.')
    index = (project.directory / 'series_index.json')
    if index.is_symlink() or not index.is_file():
        raise ValueError('Índice atual dos Stories ausente ou inseguro')
    if len(saved.episodes()) != 1:
        raise ValueError('Recuperação deveria conter somente Story 6')
    child = saved.episode(_STORY06_ID)
    for key in ('episode_id','source_start','source_end','duration','series_id','order','title_text'):
        if child.get(key) != episode.get(key):
            raise ValueError('Decisão editorial do Story 6 difere da revisão original: ' + key)
    if _canonical_hash(child.get('camera_plan')) != recovery.get('camera_sha256'):
        raise ValueError('Câmera do Story 6 foi alterada após recuperação')
    supplemental = set(recovery.get('added_word_ids') or [])
    if not supplemental or len(supplemental) != len(recovery.get('added_word_ids') or []):
        raise ValueError('Recuperação de palavras inválida')
    parent_ids = {w.get('word_id') for w in project.evidence.get('words', [])}
    child_ids = {w.get('word_id') for w in saved.evidence.get('words', [])}
    if (supplemental & parent_ids or child_ids != parent_ids | supplemental):
        raise ValueError('Palavras recuperadas não correspondem ao complemento da transcrição original')
    preview = child.get('preview') or {}
    relative = Path(preview.get('review_folder') or '')
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Caminho do preview recuperado inválido')
    folder = (directory / relative).resolve()
    if not folder.is_relative_to(directory) or folder.is_symlink():
        raise ValueError('Preview recuperado fora da revisão')
    review_path = folder / 'PREVIEW_REVIEW_V5.json'
    review = load_json(review_path, {}) or {}
    if (review.get('plan_signature') != preview.get('plan_hash')
            or review.get('plan_signature') != saved.signature(child)
            or review.get('sha256') != preview.get('sha256')
            or review.get('preview_approved_by_human') is not False
            or review.get('validation', {}).get('status') != 'validated'):
        raise ValueError('Assinatura/estado da prévia recuperada não confere')
    movie_rel = Path(review.get('path') or '')
    if movie_rel.is_absolute() or '..' in movie_rel.parts or not movie_rel.parts:
        raise ValueError('Caminho do MP4 recuperado inválido')
    movie = (folder / movie_rel).resolve()
    if not movie.is_relative_to(folder) or movie.is_symlink() or not movie.is_file():
        raise ValueError('MP4 de recuperação ausente ou externo')
    if file_hash(movie) != review['sha256']:
        raise ValueError('MP4 recuperado alterado após renderização')
    assets = review.get('assets') or []
    if not assets:
        raise ValueError('Prévia recuperada não possui manifesto de assets')
    paths = set()
    for row in assets:
        rel = Path(row.get('path') or '')
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ValueError('Asset recuperado com caminho inválido')
        asset = (folder / rel).resolve()
        if (not asset.is_relative_to(folder) or asset.is_symlink() or not asset.is_file()
                or file_hash(asset) != row.get('sha256')):
            raise ValueError('Asset de Story 6 divergiu: ' + str(rel))
        paths.add(rel.as_posix())
    if not {'CAPTIONS.ass','CAPTIONS.srt','SUBTITLE_SYNC.json'} <= paths:
        raise ValueError('Legendas da prévia recuperada não estão no manifesto')
    sync = load_json(folder / 'SUBTITLE_SYNC.json', {}) or {}
    if (not sync.get('renderable') or sync.get('alignment') != 'word'
            or sync.get('visual_behavior') != 'yellow_phrase_cumulative_white_at_measured_onset'
            or not sync.get('events') or
            any(e.get('method') != 'word' or not e.get('layout', {}).get('fits_safe_box')
                or len(e.get('layout', {}).get('visual_lines', [])) > 2
                for e in sync['events'])):
        raise ValueError('A revisão de Story 6 perdeu o karaoke/área segura')
    return movie



def _create_verified_story06_preview(project, episode, source, log):
    """Derive ONLY an unapproved Story 6 preview from signed ASR evidence.

    The failed parent render (with its receipt) remains untouched. Never infer
    12 missing words or lift safety checks; use the existing repair's gates.
    """
    if episode.get('episode_id') != _STORY06_ID:
        return None
    # Resolve from installed project root, not the output/project nesting.
    root = Path(__file__).resolve().parents[1]
    manifest = root / 'docs' / 'reports' / 'WORD_EVIDENCE_SEG00163.json'
    if not manifest.is_file():
        raise ValueError('Story 6 requer WORD_EVIDENCE_SEG00163.json original; evidência não disponível, lote interrompido sem alterar a origem')
    from scripts.REPARAR_STORY06_SEM_QWEN import check_case, derive_unpreviewed_story
    _, _, report = check_case(project, manifest)
    if report['status'] != 'SAFE_TO_DERIVE' or report.get('added_words') != 12:
        raise ValueError('Story 6 exige 12 palavras verificadas; não será forçada legenda')
    import uuid
    destination = project.directory.parent / ('story06_caption_recovered_' + uuid.uuid4().hex[:12])
    derived, provenance = derive_unpreviewed_story(project, destination, manifest)
    log('Story 6: nova revisão independente sem aprovação; câmera=' + provenance)
    preview = derived.render(_STORY06_ID, source, preview=True)
    return destination, preview

def render_stories_review_batch(project, source_path, log=print, progress=None, *, recovered_revision=None):
    """Render all Story previews in order, and finals ONLY where explicitly approved.

    No automatic sign-off. One-click produces all usable preview media while
    explicitly distinguishing ready-to-review from human-approved finals.
    """
    rows = []
    episodes = project.plan.get('episodes') or []
    if not episodes:
        raise ValueError('Sem episódios válidos de Stories')
    source = Path(source_path).resolve()
    if file_hash(source) != project.evidence['source']['sha256']:
        raise ValueError('SHA256 da mídia difere do Analyzer: Stories interrompidos')
    # Prevalidate the WHOLE sequence before rendering the first file: invalid
    # later parts must not produce a misleading partial "complete" series.
    for episode in episodes:
        seconds = episode['source_end'] - episode['source_start']
        if not (0 < seconds <= MAX_STORY_SECONDS + 1e-6):
            raise ValueError('Story ultrapassa 60s: ' + episode['episode_id'])
        if episode.get('boundary_quality') != 'sentence_or_qa':
            raise ValueError('Story sem início/fim de frase comprovados: ' + episode['episode_id'])
    # Source presentation order, never fabricated historical chronology.
    for index, episode in enumerate(episodes, 1):
        if progress:
            progress(index-1, len(episodes), episode)
        eid = episode['episode_id']
        folder = (episode.get('preview') or {}).get('review_folder')
        approved = bool(folder and episode_approval_matches(
            project.directory / folder, project.signature(episode)))
        log(f'Story {index}/{len(episodes)}: {episode.get("episode_part_label")} — {eid}')
        # A previously blocked Story 6 has a separately SHA-validated preview.
        # Refer to it without changing this project's episode, camera or approval.
        recovered = _verified_recovered_preview(project, episode, source,
                                                 explicit_revision=recovered_revision)
        if recovered is None and eid == _STORY06_ID and not (episode.get('preview') or {}).get('review_folder'):
            destination, _ = _create_verified_story06_preview(project, episode, source, log)
            recovered = _verified_recovered_preview(project, episode, source,
                                                    explicit_revision=destination)
        if recovered is not None:
            log('Story 6: revisão recuperada conferida; prévia reutilizada para revisão humana (sem aprovação automática).')
            rows.append({**_story_record(episode, recovered, status='PREVIEW_RECUPERADA_REVISAO_HUMANA'),
                         'recovery_project': str(recovered_revision or recovered.parents[4]),
                         'needs_audio_review': True, 'publication_ready': False})
        elif approved:
            final = project.render(eid, source, preview=False)
            rows.append(_story_record(project.episode(eid), final, status='FINAL_REVISADO'))
        else:
            preview = project.render(eid, source, preview=True)
            rows.append(_story_record(project.episode(eid), preview, status='PREVIEW_AGUARDA_APROVACAO'))
    if progress:
        progress(len(episodes), len(episodes), None)
    manifest = {
        'schema_version': 'LDP_COMBINED_STORY_BATCH_V1',
        'plan_id': project.plan['plan_id'],
        'source_sha256': project.evidence['source']['sha256'],
        'max_seconds': MAX_STORY_SECONDS,
        'total_parts': len(rows),
        'finals': sum(r['status'] == 'FINAL_REVISADO' for r in rows),
        'previews_pending': sum(r['status'] != 'FINAL_REVISADO' for r in rows),
        'publication_approved': False,
        'order': rows,
    }
    dest = project.directory / 'LOTE_STORIES_EM_ORDEM.json'
    write_json(dest, manifest)
    # Playlists contain reviewed final movies where available, otherwise
    # clearly marked previews. Group by series to avoid losing sequence.
    grouped = {}
    for row in rows:
        grouped.setdefault(row['series_id'], []).append(row)
    for sid, parts in grouped.items():
        lines = ['#EXTM3U', '# Playlist de revisão. PREVIEW não significa publicação aprovada.']
        for row in parts:
            lines += [f'#EXTINF:{row["duration_seconds"]:.3f},{sid} {row["part_label"]} {row["status"]}', row['file']]
        (project.directory / f'{safe_name(sid)}_PARTES_EM_ORDEM.m3u').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return manifest


def render_combined_batch(pipeline, source_input):
    """One click: verified Reels (no Qwen) followed by all Stories in source order."""
    # Prep first, so no Reel render occurs if Stories source/doc is missing.
    project, media, _ = prepare_stories(pipeline, source_input)
    original_progress = pipeline.progress
    if reel_batch_complete(pipeline, source_input):
        pipeline.log('Reels existentes revalidados por SHA256; lote preservado.')
    else:
        # Reserve the latter half of the progress bar for all Stories.
        def on_reel_progress(event):
            event = dict(event)
            if event.get('event') not in {'plan_state', 'curation_source', 'eta_context'}:
                fraction = event.get('overall_fraction')
                if fraction is not None:
                    event['overall_fraction'] = 0.5 * float(fraction)
            original_progress(event)
        pipeline.progress = on_reel_progress
        try:
            pipeline.render_all(source_input, preview=False)
        finally:
            pipeline.progress = original_progress

    def on_story_progress(index, total, episode):
        fraction = index / max(1, total)
        label = ('Stories concluídos' if episode is None else
                 f'Stories {index+1}/{total}: {episode.get("episode_part_label", "Parte")}')
        original_progress({'stage': 'stories_combined', 'label': label,
                           'step': index + 1 if episode is not None else total,
                           'total_steps': total, 'overall_fraction': 0.5 + 0.5 * fraction,
                           'stage_fraction': fraction, 'status': 'running' if episode else 'done',
                           'operation_label': 'Reels + Stories em sequência'})
    result = render_stories_review_batch(project, media, pipeline.log,
                                         progress=on_story_progress)
    pipeline.log(f'STORIES: {result["total_parts"]} partes em ordem; '
                 f'{result["finals"]} finais aprovados; '
                 f'{result["previews_pending"]} previews para revisão humana. '
                 'Nenhuma aprovação automática.')
    return result
