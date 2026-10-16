"""Render ONE derived Story from a SHA-verified original, then prepare 15 timelines.

No approvals, downloads, model calls, source writes, or batch encodes are used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ldporto_curator.approval import file_hash
from ldporto_curator.config import load_config
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles

EPISODE = 'PROP_f654d728d26180f2fb0e5816'
TIMES = (.5, 1.5, 3., 5.5, 8.5, 10., 14.5, 19., 23., 25.5)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def run(args):
    return subprocess.run(args, check=True, capture_output=True)


def audio_evidence(source, preview, start, duration, directory):
    """Check source/preview acoustic continuity; this cannot verify spoken words."""
    import numpy as np
    source_pcm = run(['ffmpeg', '-v', 'error', '-ss', str(start), '-i', str(source), '-t', str(duration),
                      '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-']).stdout
    preview_pcm = run(['ffmpeg', '-v', 'error', '-i', str(preview), '-t', str(duration),
                       '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-']).stdout
    a = np.frombuffer(source_pcm, dtype='<i2').astype(float)
    b = np.frombuffer(preview_pcm, dtype='<i2').astype(float)
    length = min(len(a), len(b))
    a, b = a[:length], b[:length]
    a -= a.mean(); b -= b.mean()
    n = 1 << (2 * length - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    lags = np.arange(-4000, 4001)
    values = corr[lags % n]
    lag = int(lags[int(np.argmax(values))])
    coefficient = float(max(values) / (np.linalg.norm(a) * np.linalg.norm(b)))
    run(['ffmpeg', '-v', 'error', '-i', str(preview), '-vn', '-ac', '1', '-ar', '16000', str(directory / 'AUDIO_PARA_REVISAO.wav')])
    return {'status': 'NEEDS_HUMAN_AUDIO_REVIEW', 'spoken_word_audio_verification': 'not_performed',
            'method': 'normalized PCM FFT cross correlation, mono 8kHz, +/-500ms search',
            'preview_relative_to_source_lag_seconds': lag / 8000,
            'source_preview_waveform_correlation': coefficient,
            'original_clip_source_start': start, 'clip_duration': duration,
            'limitation': 'Confere continuidade/defasagem global do áudio; não prova que cada palavra ASR corresponde à fala nem homologa timestamps individuais.',
            'publication_approved': False}


def extract_frames(before, after, directory, old_sync, new_sync):
    from PIL import Image, ImageDraw, ImageFont
    records = []
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 22)
    for t in TIMES:
        row = {'time': t}
        panels = []
        for kind, media, sync in [('antes', before, old_sync), ('depois', after, new_sync)]:
            output = directory / 'frames' / f'{kind}_{t:05.2f}s.png'
            output.parent.mkdir(parents=True, exist_ok=True)
            run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', str(media), '-frames:v', '1', str(output)])
            active = [e for e in sync['events'] if e['start'] <= t < e['end']]
            row[kind] = {'frame': output.relative_to(directory).as_posix(), 'sha256': file_hash(output),
                         'visible_events': [{'text': e.get('literal_text'), 'start': e['start'], 'end': e['end'],
                                             'word_ids': e.get('word_ids', []), 'lines': len(e.get('layout', {}).get('visual_lines', []))} for e in active]}
            with Image.open(output) as frame:
                panel = Image.new('RGB', (540, 1000), '#151b25')
                panel.paste(frame.convert('RGB'), (0, 40))
                ImageDraw.Draw(panel).text((12, 6), f'{kind.upper()} | {t:.2f}s', fill='white', font=font)
                panels.append(panel)
        pair = Image.new('RGB', (1080, 1000))
        pair.paste(panels[0], (0, 0)); pair.paste(panels[1], (540, 0))
        pair.save(directory / 'frames' / f'comparativo_{t:05.2f}s.jpg', quality=90)
        records.append(row)
    # Two sheets preserve enough pixels for actual visual inspection.
    for group in range(2):
        contact = Image.new('RGB', (1080, 1500), '#151b25')
        for i, t in enumerate(TIMES[group * 5:(group + 1) * 5]):
            with Image.open(directory / 'frames' / f'comparativo_{t:05.2f}s.jpg') as panel:
                contact.paste(panel.resize((540, 500)), ((i % 2) * 540, (i // 2) * 500))
        contact.save(directory / f'CONTATO_{group + 1}.jpg', quality=92)
    return records


def _seconds(value):
    hours, minutes, seconds = value.replace(',', '.').split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def verify(sync, expected_ids, duration):
    events = sync['events']
    ids = [word for event in events for word in event['word_ids']]
    assert ids == expected_ids, 'Palavras perdidas, repetidas ou fora de ordem'
    assert len(ids) == len(set(ids)) == 71
    assert len(events) == 71, 'Modo estrito deve mostrar cada palavra uma única vez'
    assert all(0 <= e['start'] < e['end'] <= duration + 1e-9 for e in events)
    assert all(len(e['layout']['visual_lines']) <= 2 and e['layout']['fits_safe_box'] for e in events)
    assert all(e.get('method') == 'word' for e in events)
    assert sync['no_word_anticipation'] is True
    assert sync['renderable'] is True
    originals = {w['word_id']: w for segment in sync['segments'] for w in segment['words']}
    ass = [line.split(',', 9) for line in Path(sync['_ass']).read_text(encoding='utf-8-sig').splitlines() if line.startswith('Dialogue:')]
    srt = Path(sync['_srt']).read_text(encoding='utf-8').strip().split('\n\n')
    assert len(ass) == len(srt) == len(events)
    serialization = []
    for ass_row, cue, event in zip(ass, srt, events):
        assert cue.splitlines()[2:] == event['literal_text'].splitlines()
        source = originals[event['word_ids'][0]]
        assert event['source_start'] == source['source_start'] and event['source_end'] == source['source_end']
        assert abs(event['start'] - max(0, source['source_start'] - sync['source_start'])) < 1e-9
        assert abs(event['end'] - min(duration, source['source_end'] - sync['source_start'])) < 1e-9
        sa, sb = map(_seconds, cue.splitlines()[1].split(' --> '))
        aa, ab = map(_seconds, ass_row[1:3])
        assert abs(sa - event['start']) <= .0005001 and abs(sb - event['end']) <= .0005001
        assert abs(aa - event['start']) <= .005001 and abs(ab - event['end']) <= .005001
        assert abs(sa - aa) <= .005001 and abs(sb - ab) <= .005001
        body = re.sub(r'\{[^}]*\}', '', ass_row[9]).replace('\\N', '\n')
        assert body == event['literal_text']
        serialization.append({'event_id': event['event_id'], 'ass_start': aa, 'ass_end': ab,
                              'srt_start': sa, 'srt_end': sb, 'word_ids': event['word_ids']})
    return {'canonical_events': len(events), 'word_ids': len(ids), 'ordered_lossless_unique': True,
            'max_lines': max(len(e['layout']['visual_lines']) for e in events),
            'all_within_clip': True, 'ass_srt_event_count_equivalent': True,
            'literal_transcript_unchanged': True, 'exact_evidence_windows': True,
            'ass_srt_times_and_text_equivalent': True, 'serialized_events': serialization,
            'review_status': 'NEEDS_HUMAN_AUDIO_REVIEW'}


def main(args):
    parent = SeriesProject(args.project, load_config(ROOT / 'config.yaml'), log=lambda t: print(t, flush=True))
    before_episode = parent.episode(EPISODE)
    old_media = parent.directory / before_episode['preview']['project_path']
    assert file_hash(old_media) == before_episode['preview']['sha256']
    assert file_hash(args.source) == parent.evidence['source']['sha256'], 'Fonte não corresponde ao contrato SHA256'
    args.report.mkdir(parents=True, exist_ok=False)
    derived = parent.derive_caption_revision(args.derived, **({'word_evidence': args.word_evidence} if args.word_evidence else {}))
    print('Revisão derivada criada; renderizando somente Parte 1.', flush=True)
    preview = derived.render(EPISODE, args.source, preview=True)
    demo_dir = args.report / 'story_parte_1'
    demo_dir.mkdir()
    for filename in ('CAPTIONS.ass', 'CAPTIONS.srt', 'SUBTITLE_SYNC.json', 'episode.json', 'camera_plan.json',
                     'TITLE_LAYOUT.json', 'RENDER_RUN.json', 'RENDER_VALIDATION.json', 'PREVIEW_REVIEW_V5.json', 'PREVIEW_540x960.mp4'):
        shutil.copy2(preview.parent / filename, demo_dir / filename)
    sync = read(demo_dir / 'SUBTITLE_SYNC.json')
    old_sync = read(old_media.parent / 'SUBTITLE_SYNC.json')
    checks = verify(dict(sync, _ass=str(demo_dir / 'CAPTIONS.ass'), _srt=str(demo_dir / 'CAPTIONS.srt')), before_episode['word_ids'], before_episode['duration'])
    # Export the exact frozen timeline at final resolution without encoding a final.
    final_subs = write_episode_subtitles(derived.evidence, derived.episode(EPISODE), demo_dir / 'resolution_1080x1920',
        preset=before_episode['subtitle_preset'], overrides=before_episode.get('subtitle_overrides'),
        width=1080, height=1920, canonical_timeline=sync)
    assert final_subs['sync']['canonical_timeline_sha256'] == sync['canonical_timeline_sha256']
    frames = extract_frames(old_media, preview, demo_dir, old_sync, sync)
    audio = audio_evidence(args.source, preview, before_episode['source_start'], before_episode['duration'], demo_dir)
    save(demo_dir / 'AUDIO_REVIEW.json', audio)
    save(demo_dir / 'EVENT_SYNC_REPORT.json', {'checks': checks, 'events': sync['events'], 'sampled_frames': frames,
        'source_sha256': parent.evidence['source']['sha256'], 'audio_review': audio})
    save(demo_dir / 'CORRECOES_PROPOSTAS.json', {'transcript_modified': False, 'proposals': [],
        'status': 'NEEDS_HUMAN_AUDIO_REVIEW', 'reason': 'Sem comprovação auditiva independente para propor alteração de nomes, números ou palavras.'})
    # Only AFTER Part1 exists: materialize caption plans for the other15; no encodes.
    others = []
    for episode in derived.episodes():
        if episode['episode_id'] == EPISODE:
            continue
        result = derived.prepare_caption_timeline(episode['episode_id'])
        destination = args.report / 'outros_15' / episode['series_id'] / f"parte_{episode['order']:02d}"
        destination.mkdir(parents=True)
        for key in ('ass', 'srt', 'sync_metadata'):
            shutil.copy2(result[key], destination / Path(result[key]).name)
        others.append({'episode_id': episode['episode_id'], 'series_id': episode['series_id'], 'part': episode['order'],
                       'events': len(result['sync']['events']), 'alignment': result['sync']['alignment'],
                       'renderable': result['sync']['renderable'], 'needs_alignment_review': result['sync']['needs_human_review'],
                       'audio_review_status': result['sync']['audio_review_status'], 'diagnostics': result['sync']['diagnostics'],
                       'canonical_timeline_sha256': result['sync']['canonical_timeline_sha256'],
                       'rendered': False, 'approved': False, 'folder': destination.relative_to(args.report).as_posix()})
    save(args.report / 'DELIVERY.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'parent_project': str(parent.directory), 'derived_project': str(derived.directory),
        'source_path': str(args.source.resolve()), 'source_sha256': parent.evidence['source']['sha256'],
        'preview': str(preview), 'checks': checks, 'audio_review': audio, 'other_episodes': others,
        'rendered_story_count': 1, 'new_human_approvals': 0, 'new_final_renders': 0,
        'series_counts': dict(Counter(e['series_id'] for e in derived.episodes()))})
    figures = '\n'.join(f'<figure><img src="story_parte_1/frames/comparativo_{t:05.2f}s.jpg" loading="lazy"><figcaption>{t:.2f}s</figcaption></figure>' for t in TIMES)
    table = '\n'.join(f'<tr><td>{i}</td><td>{e["start"]:.3f}–{e["end"]:.3f}</td><td>{html.escape(e["literal_text"])}</td><td>{html.escape(", ".join(e["word_ids"]))}</td></tr>' for i, e in enumerate(sync['events'], 1))
    (args.report / 'REVISAO.html').write_text('<!doctype html><meta charset="utf-8"><title>Stories — revisão de legendas P0</title>'
        '<style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px;background:#111827;color:#fff}video{max-height:80vh;width:auto;max-width:100%}img{max-width:100%}td{padding:7px;border-bottom:1px solid #475569}a{color:#9de1ff}</style>'
        '<h1>Parte 1 — legendas sincronizadas</h1><p>71 palavras preservadas. Exibição individual, sem antecipação. Revisão humana de áudio e leitura pendente; nenhuma aprovação/publicação concedida.</p>'
        '<video controls src="story_parte_1/PREVIEW_540x960.mp4"></video><p><a href="story_parte_1/AUDIO_PARA_REVISAO.wav">Áudio para conferência</a></p>'
        '<h2>Comparações: antes à esquerda, depois à direita</h2>' + figures + '<h2>Timeline canônica</h2><table><tr><th>Evento</th><th>Tempo no clipe</th><th>Texto literal</th><th>ID original</th></tr>' + table + '</table>', encoding='utf-8')
    print(json.dumps({'report': str(args.report), 'preview': str(preview),
                      'events': checks['canonical_events'], 'word_ids': checks['word_ids'],
                      'other_prepared': len(others), 'other_blocked': sum(not e['renderable'] for e in others),
                      'audio_review_status': audio['status']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--derived', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--word-evidence', type=Path, help='Manifesto opcional de palavras originais adicionais, com hashes e fonte verificados')
    main(p.parse_args())
