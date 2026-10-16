"""P0 acceptance evidence using FFmpeg and Curator-local, completed artifacts.

The synthetic approval is an automated acceptance-test action, never evidence of
human approval of real content. No Analyzer directory or model is accessed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ldporto_curator.analysis_loader import AnalysisBundle
from ldporto_curator.approval import file_hash
from ldporto_curator.config import load_config
from ldporto_curator.pipeline import Pipeline
from ldporto_curator.source_video import SourceUnavailable

EVIDENCE = ROOT / 'docs/reports/curator_v5_2/render_p0'
REAL_PROJECT = 'zd_wjssZ7mc'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def probe(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True,
    )
    decoded = json.loads(result.stdout)
    return {
        'duration': float(decoded['format']['duration']),
        'streams': [{key: stream[key] for key in ('codec_type', 'codec_name', 'width', 'height', 'sample_rate', 'channels', 'nb_frames') if key in stream}
                    for stream in decoded['streams']],
    }


def artifact(path):
    result = {'path': str(Path(path).resolve()), 'sha256': file_hash(path),
              'bytes': Path(path).stat().st_size, 'ffprobe': probe(path)}
    sidecar = Path(str(path) + '.render.json')
    if sidecar.is_file():
        metadata = read_json(sidecar)
        if metadata['media_sha256'] != result['sha256']:
            raise AssertionError('Sidecar de render não corresponde ao MP4 efetivamente gerado')
        result['effective_render'] = metadata
        result['effective_render_metadata_sha256'] = file_hash(sidecar)
    return result


def original_hashes():
    """Hash the exact, authorized files recorded before code changes."""
    audit = read_json(EVIDENCE / 'P0_BASELINE_AUDIT.json')
    return {name: {'sha256': file_hash(ROOT / name), 'size_bytes': (ROOT / name).stat().st_size}
            for name in audit['original_files_before']}


def recompute_legacy_signature(decisions, settings, reviewed_clip_id):
    """Use archived renderer hashes, avoiding dependence on changed source code."""
    rows = [{key: clip.get(key) for key in
             ('clip_id', 'source_start', 'source_end', 'title_text', 'title_style', 'curation_source')}
            for clip in decisions]
    for row, original in zip(rows, decisions):
        if reviewed_clip_id is None or original['clip_id'] == reviewed_clip_id:
            row['camera_plan'] = original.get('camera_plan')
            row['subtitle_plan'] = original.get('subtitle_plan')
    payload = json.dumps({'clips': rows, 'settings': settings}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_real_cached_preview():
    """Verify H against existing Curator assets without changing the originals."""
    baseline = read_json(EVIDENCE / 'P0_BASELINE_AUDIT.json')
    recovered = read_json(EVIDENCE / 'LEGACY_INPUTS_RECOVERED.json')
    preview = recovered['source_preview']
    measured = artifact(preview['path'])
    settings = baseline['legacy_signatures']['settings_and_renderer_hash_inputs']
    restored = recompute_legacy_signature(recovered['editorial_plan']['approved_clips'], settings, preview['reviewed_clip_id'])
    if measured['sha256'] != preview['sha256']:
        raise AssertionError('O preview legado mudou após o baseline')
    if restored != preview['plan_signature']:
        raise AssertionError('A restauração do clip refinado não reproduz a assinatura histórica')
    return {
        'project_id': REAL_PROJECT, 'preview': measured,
        'restored_legacy_signature': restored,
        'matches_recorded_preview_signature': True,
        'original_source_sha256': None, 'analyzer_accessed': False,
        'words_available': len(recovered['recoverable_bundle_inputs']['words']),
        'recovered_segment_count': len(recovered['recoverable_bundle_inputs']['segments']),
        'human_approval_claimed': False,
        'limits': ['Original fonte não disponível no cache autorizado.',
                   'Transcrição recuperada é somente o contexto já existente no handoff.',
                   'Este MP4 é o preview histórico preservado; não foi regenerado.'],
    }


def synthetic_bundle(media, directory):
    values = {field.name: [] for field in fields(AnalysisBundle) if field.name not in
              ('root', 'video_id', 'analysis', 'insights', 'review', 'second_package', 'second_decisions')}
    return AnalysisBundle(
        root=directory, video_id='P0_SYNTHETIC_FROZEN',
        analysis={'metadata': {'duration': 4.0, 'width': 640, 'height': 360, 'fps': 24,
                              'sha256': file_hash(media),
                              'source': {'id': 'P0_SYNTHETIC_FROZEN', 'filename': media.name,
                                         'title': 'Fixture sintética P0 — padrão gráfico e tom senoidal',
                                         'type': 'local_synthetic_fixture'}},
                  'synthetic': True},
        insights={}, review={}, second_package={}, second_decisions={}, **values,
    )


def synthetic_decisions(count):
    return [{'clip_id': f'CLIP_{i + 1:03d}', 'rank': i + 1, 'score': 90 - i,
             'source_start': i * .5, 'source_end': (i + 1) * .5, 'duration': .5,
             'title_text': f'FIXTURE SINTETICA {i + 1}', 'title_duration': .35,
             'reason': 'Seleção determinística escrita para o teste de integração P0.',
             'curation_source': 'SYNTHETIC_P0_TEST', 'synthetic': True,
             'transcript_status': 'absent_no_speech_in_sine_fixture'} for i in range(count)]


def synthetic_acceptance(directory):
    directory.mkdir(parents=True, exist_ok=False)
    media = directory / 'SYNTHETIC_ORIGINAL.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=640x360:rate=24', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000', '-t', '4', '-c:v', 'libx264',
                    '-preset', 'veryfast', '-threads', '2', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', str(media)], check=True)
    cfg = load_config(ROOT / 'config.yaml')
    cfg['paths'].update(analysis_root=str(directory / 'NOT_ANALYZER'), output_root=str(directory / 'output'),
                        source_cache=str(directory / 'cache'))
    cfg['source_media'] = {'path': str(media), 'allow_download': False}
    cfg['render']['prefer_nvenc'] = False
    cfg['thumbnail']['candidate_count'] = 1
    cfg['micro_perception'] = {'face_model': str(directory / 'NO_MODEL.onnx')}
    bundle = synthetic_bundle(media, directory)
    logs = []
    calls = []

    def curated(*_args, **_kwargs):
        count = 7 if not calls else 3
        calls.append({'explicit_curate_number': len(calls) + 1, 'clip_count': count})
        return synthetic_decisions(count)

    with patch('ldporto_curator.pipeline.find_analysis', return_value=directory) as locate, \
            patch('ldporto_curator.pipeline.load_bundle', return_value=bundle) as load, \
            patch('ldporto_curator.pipeline.curate', side_effect=curated):
        pipeline = Pipeline(cfg, ROOT, log=logs.append)
        _, decisions, base = pipeline.curate_only(str(media))
        first = read_json(base / 'EDIT_DECISIONS.json')
        original_decisions = deepcopy(first['approved_clips'])
        # A new Pipeline represents a fresh GUI session for every downstream step.
        with patch('ldporto_curator.pipeline.curate', side_effect=AssertionError('Qwen indisponível após CURAR')), \
                patch('ldporto_curator.pipeline.find_analysis', side_effect=AssertionError('Analyzer consultado após CURAR')), \
                patch('ldporto_curator.pipeline.load_bundle', side_effect=AssertionError('Analyzer lido após CURAR')):
            preview, _ = Pipeline(cfg, ROOT, log=logs.append).test_one(str(media), rank=1)
            tested = read_json(base / 'EDIT_DECISIONS.json')
            Pipeline(cfg, ROOT, log=logs.append).approve_test(str(media))
            approved = read_json(base / 'EDIT_DECISIONS.json')
            finals, _ = Pipeline(cfg, ROOT, log=logs.append).render_all(str(media), preview=False)
            final_doc = read_json(base / 'EDIT_DECISIONS.json')
        if len(finals) != 7 or len(calls) != 1:
            raise AssertionError('O fluxo aprovado não manteve a seleção de sete cortes')
        for current in (tested, approved, final_doc):
            if current['approved_clips'] != original_decisions or current['plan_revision'] != first['plan_revision']:
                raise AssertionError('Etapa posterior alterou a revisão editorial persistida')
        if tested['preview'] != approved['approval_record']:
            raise AssertionError('A aprovação não preservou a identidade da prévia revisada')
        _, updated, _ = Pipeline(cfg, ROOT, log=logs.append).curate_only(str(media))
        new_doc = read_json(base / 'EDIT_DECISIONS.json')
        if len(updated) != 3 or len(calls) != 2 or first['plan_revision'] == new_doc['plan_revision']:
            raise AssertionError('CURAR explícito não criou a nova revisão de três cortes')
        if new_doc['approval_state'] == 'TEST_APPROVED':
            raise AssertionError('A nova curadoria herdou a aprovação antiga')
    report = {
        'synthetic': True, 'real_ffmpeg_render': True, 'render_mocked': False,
        'models_called': False, 'curation_mock_scope': 'Somente decisões editoriais da fixture; sem simular render.',
        'automated_fixture_approval': True, 'human_approval_of_product_content': False,
        'source': artifact(media), 'first_plan_revision': first['plan_revision'],
        'after_explicit_recurate_revision': new_doc['plan_revision'],
        'curate_call_count_before_explicit_recurate': 1, 'curate_calls_total': len(calls),
        'find_analysis_calls_total': locate.call_count, 'load_bundle_calls_total': load.call_count,
        'selection_during_four_actions': 7, 'explicit_recuration_selection': 3,
        'editorial_clips_identical_across_four_actions': True, 'revision_identical_across_four_actions': True,
        'approval_binds_exact_preview_record': True,
        'preview_binding': tested['preview']['binding'],
        'states': [first['approval_state'], tested['approval_state'], approved['approval_state'], final_doc['approval_state']],
        'final_approval_state_before_explicit_recurate': final_doc['approval_state'],
        'new_revision_approval_state': new_doc['approval_state'],
        'preview': artifact(preview), 'finals': [artifact(path) for path in finals],
    }
    (directory / 'PIPELINE_LOG.txt').write_text('\n'.join(logs), encoding='utf-8')
    save_json(directory / 'SYNTHETIC_ACCEPTANCE.json', report)
    return report


def isolated_legacy_acceptance(directory):
    cfg = load_config(ROOT / 'config.yaml')
    cfg['paths'].update(analysis_root=str(directory / 'NOT_ANALYZER'), output_root=str(directory / 'output'),
                        source_cache=str(directory / 'EMPTY_SOURCE_CACHE'))
    cfg['source_media'] = {'allow_download': False}
    source = ROOT / 'output/curation' / REAL_PROJECT
    copied = directory / 'output/curation' / REAL_PROJECT
    shutil.copytree(source, copied)
    logs = []
    with patch('ldporto_curator.pipeline.curate', side_effect=AssertionError('Qwen em recuperação')), \
            patch('ldporto_curator.pipeline.find_analysis', side_effect=AssertionError('Analyzer em recuperação')), \
            patch('ldporto_curator.pipeline.load_bundle', side_effect=AssertionError('Analyzer em recuperação')):
        recovered_bundle, recovered_clips, base = Pipeline(cfg, ROOT, log=logs.append).recover_legacy(REAL_PROJECT)
        current = read_json(base / 'EDIT_DECISIONS.json')
        try:
            Pipeline(cfg, ROOT, log=logs.append).test_one(REAL_PROJECT)
        except SourceUnavailable as error:
            blocked = str(error)
        else:
            raise AssertionError('Recuperação não pode fabricar a fonte original ausente')
        try:
            Pipeline(cfg, ROOT, log=logs.append).approve_test(REAL_PROJECT)
        except (ValueError, RuntimeError) as error:
            approval_blocked = str(error)
        else:
            raise AssertionError('Preview legado sem origem íntegra não pode liberar aprovação')
    report = {
        'isolated_copy': str(copied), 'original_project_modified': False,
        'source_available': False, 'new_preview_block_reason': blocked,
        'approval_block_reason': approval_blocked, 'approval_state': current['approval_state'],
        'recovered_clips': len(recovered_clips), 'transcript_segments': len(recovered_bundle.segments),
        'words': len(recovered_bundle.words), 'human_approved': False, 'models_called': False,
        'analyzer_accessed': False, 'plan_revision': current['plan_revision'],
        'legacy_evidence': current.get('legacy_evidence'),
    }
    (directory / 'LEGACY_RECOVERY_LOG.txt').write_text('\n'.join(logs), encoding='utf-8')
    save_json(directory / 'LEGACY_ISOLATED_ACCEPTANCE.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--read-only', action='store_true', help='Verificar somente o preview real histórico.')
    args = parser.parse_args()
    directory = args.output or EVIDENCE / ('acceptance_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    directory.mkdir(parents=True, exist_ok=False)
    before = original_hashes()
    report = {'report_directory': str(directory), 'originals_before': before,
              'analyzer_accessed': False, 'models_called': False}
    try:
        report['real_cached_preview'] = audit_real_cached_preview()
        if not args.read_only:
            report['synthetic_four_action_flow'] = synthetic_acceptance(directory / 'synthetic')
            report['legacy_isolated_recovery'] = isolated_legacy_acceptance(directory / 'legacy_isolated')
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        report['originals_after'] = original_hashes()
        report['originals_unchanged'] = report['originals_before'] == report['originals_after']
        save_json(directory / 'P0_ACCEPTANCE.json', report)
        print(json.dumps({'status': report['status'], 'report': str(directory / 'P0_ACCEPTANCE.json'),
                          'originals_unchanged': report['originals_unchanged']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
