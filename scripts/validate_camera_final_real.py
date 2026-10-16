"""Five selected real-video camera checks in a new report directory; no models.

Historical Stories and source are read-only. All renders are unapproved previews.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ldporto_curator.approval import file_hash
from ldporto_curator.config import load_config
from ldporto_curator.series_workflow import SeriesProject


def run(args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True)


def audio_digest(path):
    import hashlib
    data = run(['ffmpeg', '-v', 'error', '-i', path, '-map', '0:a:0',
        '-f', 's16le', '-ac', '1', '-ar', '48000', '-']).stdout
    return {'sha256_pcm_s16le_mono_48000': hashlib.sha256(data).hexdigest(),
            'samples': len(data)//2}


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', path]).stdout)


def compare_frames(before, after, times, directory):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    directory.mkdir(parents=True, exist_ok=False)
    caps = [cv2.VideoCapture(str(p)) for p in (before, after)]
    results = []
    for index, time in enumerate(times):
        sheet = Image.new('RGB', (1080, 990), '#171a21')
        draw = ImageDraw.Draw(sheet)
        metrics = []
        for column, (label, cap) in enumerate(zip(('ANTES', 'DEPOIS'), caps)):
            cap.set(cv2.CAP_PROP_POS_MSEC, time*1000)
            ok, frame = cap.read()
            if not ok:
                raise ValueError('Frame real não decodificável')
            pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(pixels)
            image.save(directory / f'{index:02d}_{label.lower()}.png')
            sheet.paste(image.resize((540, 960)), (column*540, 30))
            draw.text((column*540+12, 8), f'{label} | {time:.3f}s do Story', fill='white')
            # Check full-width/full-height uniform near-black edges, not isolated
            # naturally dark pixels. These samples complement actual frame review.
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            bands = [gray[:4, :], gray[-4:, :], gray[:, :4], gray[:, -4:]]
            metrics.append({'label': label,
                'near_black_uniform_edges': [bool((b < 10).mean() > .995 and b.std() < 3) for b in bands],
                'laplacian_variance_whole_frame': float(cv2.Laplacian(gray, cv2.CV_64F).var())})
        name = f'comparativo_{index:02d}.jpg'
        sheet.save(directory / name, quality=92)
        results.append({'time': time, 'comparison': str(directory / name), 'metrics': metrics})
    for cap in caps:
        cap.release()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--camera-project', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    destination = args.destination.resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / 'docs/reports'):
        raise ValueError('As demonstrações exigem uma pasta inédita em docs/reports')
    parent = SeriesProject(args.project, load_config(ROOT / 'config.yaml'))
    source_sha = file_hash(args.source)
    if source_sha != parent.evidence['source']['sha256']:
        raise ValueError('Fonte real diverge do SHA256 do projeto')
    from ldporto_curator.camera_metadata import load_existing_camera_metadata
    camera_plan_path = args.camera_project / 'EDIT_DECISIONS.json'
    camera_doc = json.loads(camera_plan_path.read_text(encoding='utf-8-sig'))
    planning = args.camera_project / Path(camera_doc['planning_evidence'].replace('\\', '/')) / 'clips'
    # Existing episode IDs and windows are retained literally. These are selected
    # representatives, not an editorial re-selection or a render of all Stories.
    cases = [
        ('apresentador', 15, 7, [4., 18., 22.]),
        ('mapa_rota', 1, 5, [3., 12., 24.]),
        ('alternancia', 3, 2, [3., 22., 31.]),
        ('gestos', 5, 1, [8., 18., 25.]),
        ('baixa_confianca', 0, None, [2., 8., 18.]),
    ]
    micros, descriptions = {}, []
    for name, episode_index, reel_rank, times in cases:
        episode = parent.episodes()[episode_index]
        micro = load_existing_camera_metadata(planning / f'SECOND_LDP26_REEL_{reel_rank:02d}_01/clip_micro_perception.json',
            source_sha, source_plan=camera_plan_path) if reel_rank is not None else {}
        micros[episode['episode_id']] = micro
        descriptions.append((name, episode['episode_id'], times))
    derived = parent.derive_camera_revision(destination / 'review_project', micro_by_episode=micros)
    report = {'schema': 'LDP_REAL_CAMERA_DEMOS_V1', 'source_sha256': source_sha,
        'original_project': str(parent.directory), 'derived_project': str(derived.directory),
        'new_analysis_executed': False, 'approved': False, 'cases': []}
    for name, identifier, times in descriptions:
        print('Renderizando demonstração:', name, identifier, flush=True)
        old = parent.episode(identifier)
        before = parent.directory / old['preview']['project_path']
        after = derived.render(identifier, args.source, preview=True)
        episode = derived.episode(identifier)
        original_folder = parent.directory / old['preview']['review_folder']
        old_sync = json.loads((original_folder / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8-sig'))
        new_sync = json.loads((after.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8-sig'))
        old_audio, new_audio = audio_digest(before), audio_digest(after)
        row = {'scenario': name, 'episode_id': identifier, 'before': str(before), 'after': str(after),
            'source_start': old['source_start'], 'source_end': old['source_end'], 'duration': old['duration'],
            'editorial_window_unchanged': all(old[k] == episode[k] for k in ('source_start', 'source_end', 'duration')),
            'canonical_timeline_unchanged': old_sync['canonical_timeline_sha256'] == new_sync['canonical_timeline_sha256'],
            'ass_bytes_unchanged': file_hash(original_folder / 'CAPTIONS.ass') == file_hash(after.parent / 'CAPTIONS.ass'),
            'srt_bytes_unchanged': file_hash(original_folder / 'CAPTIONS.srt') == file_hash(after.parent / 'CAPTIONS.srt'),
            'title_pixels_unchanged': file_hash(original_folder / 'title_card_preview.png') == file_hash(after.parent / 'title_card_preview.png'),
            'audio_before': old_audio, 'audio_after': new_audio, 'audio_pcm_identical': old_audio == new_audio,
            'media_probe': probe(after), 'before_sha256': file_hash(before), 'after_sha256': file_hash(after),
            'camera_plan_before': old['camera_plan'], 'camera_plan_after': episode['camera_plan'],
            'frames': compare_frames(before, after, times, destination / name),
            'human_audio_visual_approval': 'PENDING'}
        assert row['editorial_window_unchanged'] and row['canonical_timeline_unchanged']
        assert row['ass_bytes_unchanged'] and row['srt_bytes_unchanged'] and row['title_pixels_unchanged']
        report['cases'].append(row)
        (destination / 'VALIDACAO_REAL.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if file_hash(args.source) != source_sha:
        raise ValueError('Fonte mudou durante os testes; revisar evidências')
    print('Evidências:', destination, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
