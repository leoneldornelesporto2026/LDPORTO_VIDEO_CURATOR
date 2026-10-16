"""Render two unapproved 1080x1920 technical demos from a frozen camera review."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    from ldporto_curator.approval import file_hash
    from ldporto_curator.series_workflow import SeriesProject, validate_episode_media
    from ldporto_curator.subtitle_presets import write_episode_subtitles
    from ldporto_curator.title_presets import create_episode_title_card
    from ldporto_curator.render import _base_cmd, ffmpeg_has_nvenc
    from ldporto_curator.media_effects import extend_render_command
    report = json.loads(args.validation.read_text(encoding='utf-8'))
    destination = args.destination.resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / 'docs/reports'):
        raise ValueError('Demonstração HD exige pasta inédita em docs/reports')
    project = SeriesProject(report['derived_project'])
    if file_hash(args.source) != report['source_sha256']:
        raise ValueError('Fonte diverge do SHA256 verificado')
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for scenario in ('apresentador', 'mapa_rota'):
        case = next(c for c in report['cases'] if c['scenario'] == scenario)
        episode = project.episode(case['episode_id'])
        project.signature(episode)  # Refuse any changed frozen input.
        folder = destination / scenario
        folder.mkdir(exist_ok=False)
        canonical = project.prepare_caption_timeline(episode['episode_id'])['sync']
        subtitles = write_episode_subtitles(project.evidence, episode, folder,
            preset=episode['subtitle_preset'], overrides=episode.get('subtitle_overrides'),
            width=1080, height=1920, canonical_timeline=canonical)
        if subtitles['sync']['canonical_timeline_sha256'] != canonical['canonical_timeline_sha256']:
            raise ValueError('Timeline canônica diverge no ensaio HD')
        clip = {**episode, 'clip_id': episode['episode_id']}
        clip.setdefault('title_duration', 5.)
        card = create_episode_title_card(clip, folder, project.cfg, preview=False)
        output = folder / ('DEMO_' + scenario.upper() + '_1080x1920.mp4')
        encoder = 'h264_nvenc' if ffmpeg_has_nvenc() else 'libx264'
        command, _, _ = _base_cmd(None, clip, args.source, output,
            Path(subtitles['ass']), card, project.cfg, False, encoder)
        command = extend_render_command(command, episode, 1080, 1920, episode['duration'], folder)
        command = ['-n' if a == '-y' else a for a in command]
        command[-1:-1] = ['-threads', '2', '-filter_complex_threads', '2']
        print('Demonstração técnica HD:', scenario, flush=True)
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        validation = validate_episode_media(output, 1080, 1920, episode['duration'])
        records.append({'scenario': scenario, 'path': str(output), 'sha256': file_hash(output),
            'source_start': episode['source_start'], 'source_end': episode['source_end'],
            'canonical_timeline_sha256': canonical['canonical_timeline_sha256'],
            'validation': validation, 'approved': False, 'technical_demo_only': True})
        (destination / 'HD_DEMOS.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Demonstrações HD:', destination, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
