"""Render exactly two isolated, unapproved Stories from verified saved evidence.

The caller explicitly identifies the host and map episodes. This command never
curates, analyzes, approves, updates the normal project, or renders a batch.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ldporto_curator.approval import file_hash
from ldporto_curator.camera_metadata import load_existing_camera_metadata
from ldporto_curator.config import load_config
from ldporto_curator.series_workflow import SeriesProject, _canonical_hash
from scripts.validate_camera_final_real import audio_digest, compare_frames, probe


def inventory(directory):
    """Hash existing project inputs and artifacts without changing them."""
    directory = Path(directory)
    return {path.relative_to(directory).as_posix(): file_hash(path)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def selected_episodes(parent, host_id, map_id):
    if host_id == map_id:
        raise ValueError('Host and map must identify two different episodes')
    result = []
    for scenario, identifier in [('apresentador', host_id), ('mapa_rota', map_id)]:
        matches = [row for row in parent.episodes() if row.get('episode_id') == identifier]
        if len(matches) != 1:
            raise ValueError('Episode ID is missing or ambiguous: ' + identifier)
        episode = matches[0]
        if not (episode.get('preview') or {}).get('project_path'):
            raise ValueError('A historical preview is required: ' + identifier)
        result.append((scenario, episode))
    return result


def _window(row):
    values = [row.get(key) for key in ('source_start', 'source_end')]
    if any(isinstance(value, bool) for value in values):
        raise ValueError('Invalid source interval in declared clip')
    try:
        start, end = map(float, values)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid source interval in declared clip') from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError('Invalid source interval in declared clip')
    return start, end


def resolve_saved_micro(plan_path, plan, episode, source_sha256):
    """Use one declared clip with the exact window, otherwise one covering it.

    No clip rank, array position, nearest timestamp or glob order can select the
    evidence. Ambiguous coverage is an error rather than a silent choice.
    """
    start, end = _window(episode)
    exact, covers = [], []
    for clip in plan.get('approved_clips') or []:
        if not isinstance(clip, dict):
            raise ValueError('Invalid declared camera clip')
        first, last = _window(clip)
        if abs(first-start) <= 1e-6 and abs(last-end) <= 1e-6:
            exact.append(clip)
        elif first <= start+1e-6 and last >= end-1e-6:
            covers.append(clip)
    candidates = exact or covers
    if len(candidates) != 1:
        raise ValueError('Existing camera interval is missing or ambiguous: ' + episode['episode_id'])
    clip = candidates[0]
    identifier = clip.get('clip_id')
    if (not isinstance(identifier, str) or not identifier or identifier in {'.', '..'}
            or any(char in identifier for char in '/\\:')):
        raise ValueError('Invalid declared camera clip ID')
    planning = plan.get('planning_evidence')
    if not isinstance(planning, str) or not planning:
        raise ValueError('Source plan is missing planning_evidence')
    relative = PurePosixPath(planning.replace('\\', '/'))
    if (relative.is_absolute() or PureWindowsPath(planning).drive
            or ':' in planning or '..' in relative.parts):
        raise ValueError('Source planning_evidence must stay inside its project')
    path = Path(plan_path).parent.joinpath(*relative.parts, 'clips', identifier,
                                          'clip_micro_perception.json')
    micro = load_existing_camera_metadata(path, source_sha256, source_plan=plan_path)
    binding = {'clip_id': identifier, 'source_start': clip['source_start'],
        'source_end': clip['source_end'], 'match': 'exact' if exact else 'covers',
        'metadata_provenance': deepcopy(micro['metadata_provenance'])}
    return micro, binding


def checked_destination(destination, reports_root):
    destination, reports_root = Path(destination).resolve(), Path(reports_root).resolve()
    if destination.exists() or destination == reports_root or not destination.is_relative_to(reports_root):
        raise ValueError('Demonstrations require a new directory under docs/reports')
    return destination


def _historical_asset(parent, relative):
    candidate = parent.directory / relative
    if candidate.is_symlink():
        raise ValueError('Historical asset cannot be a symbolic link')
    path = candidate.resolve()
    if not path.is_relative_to(parent.directory) or not path.is_file():
        raise ValueError('Historical asset is absent or outside the project')
    return path


def _routing_trace(old, new, micro, binding, command):
    plan = new['camera_plan']
    segments = plan.get('segments') or []
    keys = ('start', 'end', 'mode', 'reason', 'evidence_role', 'fallback_reason',
        'crop_safe', 'person_id', 'center_x', 'center_y', 'center_x_start',
        'center_x_end', 'center_y_start', 'center_y_end', 'zoom', 'zoom_start',
        'zoom_end', 'zoom_transition_start', 'zoom_transition_duration',
        'zoom_easing', 'graphics_policy')
    return {'episode_camera_mode': old.get('camera_mode'),
        'old_persisted_mode': (old.get('camera_plan') or {}).get('mode'),
        'saved_micro_binding': binding,
        'existing_observation_count': len(micro.get('observations') or []),
        'existing_visual_focus_region_count': len(micro.get('visual_focus_regions') or []),
        'new_persisted_mode': plan.get('mode'),
        'renderer_input_camera_plan_sha256': _canonical_hash(plan),
        'new_segment_modes': sorted({row.get('mode', '') for row in segments}),
        'crop_segment_count': sum(row.get('mode') == 'crop' for row in segments),
        'wide_segment_count': sum(row.get('mode') == 'full_frame_blur' for row in segments),
        'segments': [{key: row[key] for key in keys if key in row} for row in segments],
        'diagnostics': deepcopy(plan.get('diagnostics') or {}),
        'ffmpeg_filter_complex': command[command.index('-filter_complex')+1],
        'command_constructed_for_evidence_only': True,
        'additional_encode_executed_for_filter_evidence': False}


def _save_report(destination, report):
    (destination / 'VALIDACAO_STORY_CAMERA_ROUTING.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--camera-plan', type=Path, required=True,
                        help='Current Reels EDIT_DECISIONS.json that declares saved micro evidence')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--host-episode', required=True, help='Exact historical episode_id')
    parser.add_argument('--map-episode', required=True, help='Exact historical episode_id')
    args = parser.parse_args(argv)
    destination = checked_destination(args.destination, ROOT / 'docs/reports')
    cfg = load_config(ROOT / 'config.yaml')
    cfg.setdefault('render', {})['prefer_nvenc'] = False
    parent = SeriesProject(args.project, cfg)
    cases = selected_episodes(parent, args.host_episode, args.map_episode)
    source_sha = file_hash(args.source)
    if source_sha != parent.evidence['source']['sha256']:
        raise ValueError('Source SHA256 differs from the historical Stories project')
    plan = json.loads(args.camera_plan.read_text(encoding='utf-8-sig'))
    micros, bindings = {}, {}
    protected = {str(args.camera_plan.resolve()): file_hash(args.camera_plan)}
    for _, episode in cases:
        identifier = episode['episode_id']
        micros[identifier], bindings[identifier] = resolve_saved_micro(
            args.camera_plan, plan, episode, source_sha)
        provenance = micros[identifier]['metadata_provenance']
        protected[provenance['path']] = provenance['sha256']
    before = inventory(parent.directory)
    # The inventory is persisted before derivation or rendering can write files.
    destination.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'LDP_STORY_CAMERA_ROUTING_DEMOS_V1',
        'source_sha256': source_sha, 'original_project': str(parent.directory),
        'derived_project': str(destination / 'review_project'),
        'selected_episode_ids': [episode['episode_id'] for _, episode in cases],
        'historical_project_inventory_before': before, 'protected_inputs_before': protected,
        'approved': False, 'human_audio_visual_approval': 'PENDING',
        'normal_workflow_integration': 'PENDING_USER_APPROVAL',
        'batch_render_executed': False, 'new_analysis_executed': False,
        'curation_executed': False, 'cpu_encoder_requested': 'libx264', 'cases': []}
    _save_report(destination, report)
    derived = parent.derive_camera_revision(destination / 'review_project',
        micro_by_episode=micros, episode_ids=report['selected_episode_ids'])
    if {row['episode_id'] for row in derived.episodes()} != set(report['selected_episode_ids']):
        raise ValueError('Camera demo revision must contain exactly the two selected Stories')
    if not any(segment.get('mode') == 'crop' for segment in
               derived.episode(args.host_episode)['camera_plan'].get('segments', [])):
        raise ValueError('Selected host demonstration has no evidence-supported vertical crop')
    if not any(segment.get('mode') == 'full_frame_blur' for segment in
               derived.episode(args.map_episode)['camera_plan'].get('segments', [])):
        raise ValueError('Selected map demonstration has no source-preserving wide interval')
    from ldporto_curator.render import _base_cmd
    for scenario, old in cases:
        identifier = old['episode_id']
        print('Rendering isolated camera demonstration:', scenario, identifier, flush=True)
        historical = _historical_asset(parent, old['preview']['project_path'])
        original_folder = _historical_asset(parent,
            Path(old['preview']['review_folder']) / 'SUBTITLE_SYNC.json').parent
        output = derived.render(identifier, args.source, preview=True)
        episode = derived.episode(identifier)
        old_sync = json.loads((original_folder / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8-sig'))
        new_sync = json.loads((output.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8-sig'))
        original_audio, new_audio = audio_digest(historical), audio_digest(output)
        # _base_cmd only probes dimensions and constructs a graph; never runs an encode.
        clip = {**episode, 'clip_id': identifier}
        command, _, _ = _base_cmd(None, clip, args.source,
            output.parent / 'FILTER_EVIDENCE_NOT_RENDERED.mp4', output.parent / 'CAPTIONS.ass',
            output.parent / 'title_card_preview.png', derived.cfg, True, 'libx264')
        duration = float(old['duration'])
        frame_times = [round(duration*fraction, 3) for fraction in (.25, .5, .75)]
        row = {'scenario': scenario, 'episode_id': identifier,
            'before': str(historical), 'after': str(output),
            'source_start': old['source_start'], 'source_end': old['source_end'],
            'duration': old['duration'], 'before_sha256': file_hash(historical),
            'after_sha256': file_hash(output),
            'editorial_window_unchanged': all(old[key] == episode[key]
                for key in ('source_start', 'source_end', 'duration')),
            'title_and_order_unchanged': all(old.get(key) == episode.get(key)
                for key in ('title_text', 'title_duration', 'series_id', 'order', 'story_order')),
            'canonical_timeline_unchanged': old_sync['canonical_timeline_sha256'] == new_sync['canonical_timeline_sha256'],
            'ass_bytes_unchanged': file_hash(original_folder / 'CAPTIONS.ass') == file_hash(output.parent / 'CAPTIONS.ass'),
            'srt_bytes_unchanged': file_hash(original_folder / 'CAPTIONS.srt') == file_hash(output.parent / 'CAPTIONS.srt'),
            'title_pixels_unchanged': file_hash(original_folder / 'title_card_preview.png') == file_hash(output.parent / 'title_card_preview.png'),
            'audio_before': original_audio, 'audio_after': new_audio,
            'audio_pcm_identical': original_audio == new_audio,
            'media_probe': probe(output), 'camera_plan_before': old.get('camera_plan'),
            'camera_plan_after': episode['camera_plan'],
            'routing_trace': _routing_trace(old, episode, micros[identifier], bindings[identifier], command),
            'frames': compare_frames(historical, output, frame_times, destination / scenario),
            'human_audio_visual_approval': 'PENDING', 'approved': False}
        persisted_plan = json.loads((output.parent / 'camera_plan.json').read_text(encoding='utf-8-sig'))
        row['routing_trace']['rendered_camera_plan_sha256'] = _canonical_hash(persisted_plan)
        row['routing_trace']['renderer_input_matches_rendered_camera_plan'] = (
            row['routing_trace']['renderer_input_camera_plan_sha256'] ==
            row['routing_trace']['rendered_camera_plan_sha256'])
        report['cases'].append(row)
        _save_report(destination, report)
        invariant_keys = ('editorial_window_unchanged', 'title_and_order_unchanged',
            'canonical_timeline_unchanged', 'ass_bytes_unchanged', 'srt_bytes_unchanged',
            'title_pixels_unchanged', 'audio_pcm_identical')
        if not all(row[key] for key in invariant_keys):
            raise ValueError('Demonstration changed a protected input; inspect the saved report')
        if not row['routing_trace']['renderer_input_matches_rendered_camera_plan']:
            raise ValueError('Rendered camera plan differs from the filter evidence input')
    report['historical_project_inventory_after'] = inventory(parent.directory)
    report['historical_project_unchanged'] = report['historical_project_inventory_after'] == before
    report['protected_inputs_after'] = {path: file_hash(Path(path)) for path in protected}
    report['protected_inputs_unchanged'] = report['protected_inputs_after'] == protected
    report['source_sha256_after'] = file_hash(args.source)
    report['source_unchanged'] = report['source_sha256_after'] == source_sha
    _save_report(destination, report)
    if not all(report[key] for key in ('historical_project_unchanged', 'protected_inputs_unchanged', 'source_unchanged')):
        raise ValueError('Historical input changed during the demonstration; inspect the saved report')
    print('Two unapproved camera demonstrations:', destination, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
