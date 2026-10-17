"""Render three explicitly technical, unapproved camera previews externally.

Uses the installed SeriesProject renderer. It never approves a blocked native
candidate, modifies its captions, or writes under output/. Captions are hidden
with the existing SEM_LEGENDA preset; literal source words remain in the audit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ldporto_curator.episode_approval import file_hash
from ldporto_curator.production_evidence import build_piece_camera, normalise_production_evidence
from ldporto_curator.production_contract import read_production_archive
from ldporto_curator.production_package import (import_production_package, load_production_project,
                                               videos_folder)
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles
from ldporto_curator.utils import write_json

SOURCE = '5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea'
WINDOWS = (
    ('D_ALTERNANCIA_MEDIDA', 1147.62, 1153.82, 'WORD_0000140 onset to WORD_0000159 offset; certified focus then explicit renderer-limit fallback'),
    ('E_FONTE_AMPLA', 1393.98, 1397.38, 'SEG_00041 measured boundaries; Director preserves both original source shots'),
    ('F_ZOOM_CERTIFICADO', 1147.25, 1150.48409375, 'Consecutive original certified Director boundaries; zoom 1.0 to 1.030037, within existing 1.05 renderer envelope'),
)


def _outside(path):
    path = Path(path).resolve()
    repository = Path(__file__).resolve().parent.parent
    if path.is_relative_to(repository):
        raise ValueError('Technical media must be written outside the repository')
    for ancestor in (path, *path.parents):
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked destination is not allowed')
    return path


def run(project_directory, *, destination=None, evidence_package=None):
    parent = load_production_project(project_directory)
    imported = parent.plan['production_import']
    if parent.evidence['source']['sha256'] != SOURCE:
        raise ValueError('These measured windows apply exclusively to the audited 5d089e1825b3 source')
    media = Path(imported['media_reference'].get('path') or '')
    if not media.is_file() or file_hash(media) != SOURCE:
        raise ValueError('The exact original media is required; no download or other source is substituted')
    index_path = parent.directory / 'visual_evidence_index.json'
    if file_hash(index_path) != imported['visual_index_sha256']:
        raise ValueError('The imported visual evidence index changed')
    index = json.loads(index_path.read_text(encoding='utf-8-sig'))
    index_origin = {'parent_index_sha256': file_hash(index_path)}
    if evidence_package:
        container = read_production_archive(evidence_package)
        if container['metadata']['sha256'] != SOURCE:
            raise ValueError('Diagnostic camera package belongs to another source')
        normalized = normalise_production_evidence(container)
        index = normalized['visual_index']
        index_origin.update(reconstructed_from_verified_original_package=str(evidence_package),
            original_package_sha256=container['package_sha256'],
            adapter_sha256=file_hash(Path(__file__).resolve().parent.parent / 'ldporto_curator/production_evidence.py'),
            parent_index_modified=False)
    destination = _outside(destination or videos_folder() / 'LDPORTO_VIDEO_CURATOR' / 'technical_camera_validation' /
        (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]))
    destination.mkdir(parents=True, exist_ok=False)
    snapshot = {name: file_hash(parent.directory / name) for name in ('series_index.json', 'evidence.json', 'visual_evidence_index.json')}
    report = {'schema': 'LDP_TECHNICAL_CAMERA_VALIDATION_V1', 'source_sha256': SOURCE,
        'parent_project': str(parent.directory), 'parent_snapshots': snapshot,
        'scope': 'technical_camera_only_not_candidate_approval_or_caption_release',
        'camera_evidence_origin': index_origin,
        'native_caption_gates_changed': False, 'new_asr_or_perception': False,
        'audio': 'original_without_normalization_or_added_music', 'human_approved': False,
        'caption_policy': 'existing_SEM_LEGENDA_preset_no_text_drawn_no_invented_timestamps', 'previews': []}
    write_json(destination / 'TECHNICAL_VALIDATION.json', report)
    for name, start, end, provenance in WINDOWS:
        source_segments = [deepcopy(row) for row in parent.evidence['segments'] if row['start'] < end and row['end'] > start]
        segment_ids = {row['segment_id'] for row in source_segments}
        evidence = {'schema_version': parent.evidence.get('schema_version'),
            'source': deepcopy(parent.evidence['source']), 'metadata': deepcopy(parent.evidence.get('metadata') or {}),
            'segments': source_segments,
            # Alignment validates each complete original segment before the
            # existing serializer clips events to the diagnostic window.
            'words': [deepcopy(row) for row in parent.evidence['words'] if row.get('segment_id') in segment_ids],
            'availability': deepcopy(parent.evidence.get('availability') or {}),
            'provenance': {'technical_diagnostic_only': True, 'source_sha256': SOURCE,
                'parent_project': str(parent.directory), 'parent_evidence_sha256': snapshot['evidence.json'],
                'literal_words_and_timestamps_copied_unchanged': True, 'audio_human_verified': False}}
        episode = {'episode_id': 'TECHNICAL_' + name, 'series_id': 'DIAGNOSTICO_CAMERA', 'order': 1, 'story_order': 1,
            'source_start': start, 'source_end': end, 'duration': end - start, 'duration_preset': 'auto_under_90',
            'state': 'PLANNED', 'status': 'PLANNED', 'technical_diagnostic_only': True,
            'title_enabled': False, 'title_text': '', 'subtitle_preset': 'SEM_LEGENDA',
            'thumbnail_overrides': {'frame_count': 3}, 'audio': {'mode': 'original'},
            'camera_mode': 'AUTO_CONSERVADOR', 'human_approved': False, 'preview_approved': False,
            'window_provenance': provenance}
        episode['camera_plan'] = build_piece_camera(index, episode, imported['source_metadata'], parent.cfg)
        project = SeriesProject(destination / name, deepcopy(parent.cfg))
        project.evidence = evidence
        project.plan = {'schema_version': '5.2.0', 'plan_id': 'TECHNICAL_' + name,
            'source_sha256': SOURCE, 'status': 'TECHNICAL_DIAGNOSTIC_ONLY',
            'mode': 'SERIE_CRONOLOGICA', 'duration_preset': 'auto_under_90',
            'episodes': [episode], 'extras': [], 'story_map': {},
            'audit_trail': [{'action': 'technical_camera_validation', 'candidate_approved': False,
                'upstream_caption_gate_preserved': True, 'window_provenance': provenance}]}
        project.save()
        # Still use real lexical timing validation. Hiding text is not a way to
        # fabricate a missing transcript or silence classification.
        check = write_episode_subtitles(evidence, episode, project.directory / 'caption_preflight', preset='SEM_LEGENDA')
        if check['sync'].get('renderable') is False or check['sync'].get('alignment') != 'word':
            raise ValueError('Technical window lacks mechanical word alignment: ' + name)
        movie = project.render(episode['episode_id'], media, preview=True)
        subtitle = json.loads((movie.parent / 'SUBTITLE_SYNC.json').read_text(encoding='utf-8-sig'))
        if subtitle.get('enabled') is not False or any(event.get('ass_event_written') for event in subtitle.get('events', [])):
            raise ValueError('Diagnostic unexpectedly drew captions')
        report['previews'].append({'name': name, 'movie': str(movie), 'sha256': file_hash(movie),
            'source_start': start, 'source_end': end, 'duration': end-start,
            'source_word_ids': [row['word_id'] for row in evidence['words']],
            'camera_plan': episode['camera_plan'], 'subtitle_enabled': False,
            'publication_ready': False, 'human_review_required': True})
        write_json(destination / 'TECHNICAL_VALIDATION.json', report)
    if any(file_hash(parent.directory / name) != digest for name, digest in snapshot.items()):
        raise ValueError('Parent project changed during diagnostic; all artifacts preserved')
    print(json.dumps({'destination': str(destination), 'movies': [row['movie'] for row in report['previews']]}, ensure_ascii=False, indent=2))
    return report


def analyse_pixels(validation_path):
    """Measure source-to-render scale using SIFT/RANSAC, without a model.

    The source decoder is sampled within two source frames of the nominal
    matched output time. Every tested offset is recorded. This handles normal
    seek/frame rounding; no face, body, hand or instrument is inferred here.
    """
    import cv2
    import numpy as np
    validation_path = Path(validation_path)
    report = json.loads(validation_path.read_text(encoding='utf-8-sig'))
    directory = _outside(validation_path.parent / ('PIXEL_PROOF_' + uuid4().hex[:8]))
    directory.mkdir(exist_ok=False)
    parent = load_production_project(report['parent_project'])
    media = Path(parent.plan['production_import']['media_reference']['path'])
    if file_hash(media) != report['source_sha256']:
        raise ValueError('Source changed before pixel inspection')
    source = cv2.VideoCapture(str(media))
    source_fps = source.get(cv2.CAP_PROP_FPS)
    sift = cv2.SIFT_create(nfeatures=8000)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    result = {'schema': 'LDP_CAMERA_PIXEL_PROOF_V1', 'source_sha256': report['source_sha256'],
        'method': 'SIFT_features_source_to_actual_decoded_MP4_RANSAC_homography',
        'matching_ratio_threshold': .72, 'ransac_reprojection_pixels': 2.5,
        'source_temporal_search_frames': [-2, -1, 0, 1, 2], 'source_fps': source_fps,
        'identity_or_instrument_inference': False, 'frames': [], 'zoom_measurements': []}
    try:
        for row in report['previews']:
            movie = Path(row['movie'])
            if file_hash(movie) != row['sha256']:
                raise ValueError('Rendered preview changed before inspection')
            rendered = cv2.VideoCapture(str(movie))
            fps = rendered.get(cv2.CAP_PROP_FPS)
            try:
                for label, seconds in [('early', .2), ('late', min(2.5, row['duration'] - .2))]:
                    frame_number = round(seconds * fps)
                    rendered.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                    ok, output = rendered.read()
                    if not ok:
                        raise ValueError('Cannot decode preview proof frame')
                    output_time = frame_number / fps
                    path = directory / (row['name'] + '_' + label + '.png')
                    if not cv2.imwrite(str(path), output):
                        raise ValueError('Cannot save proof frame')
                    result['frames'].append({'name': row['name'], 'label': label, 'output_frame': frame_number,
                        'output_time': output_time, 'path': str(path), 'sha256': file_hash(path)})
                    if row['name'] != 'F_ZOOM_CERTIFICADO':
                        continue
                    output_keys, output_descriptors = sift.detectAndCompute(cv2.cvtColor(output, cv2.COLOR_BGR2GRAY), None)
                    nominal_source = round((row['source_start'] + output_time) * source_fps)
                    trials = []
                    candidates = []
                    for offset in [-2, -1, 0, 1, 2]:
                        source_frame = nominal_source + offset
                        source.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                        ok, original = source.read()
                        if not ok:
                            continue
                        source_keys, source_descriptors = sift.detectAndCompute(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), None)
                        pairs = matcher.knnMatch(source_descriptors, output_descriptors, k=2)
                        matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .72 * pair[1].distance]
                        trial = {'offset_frames': offset, 'source_frame': source_frame, 'good_matches': len(matches)}
                        if len(matches) >= 12:
                            p = np.float32([source_keys[m.queryIdx].pt for m in matches])
                            q = np.float32([output_keys[m.trainIdx].pt for m in matches])
                            matrix, mask = cv2.findHomography(p, q, cv2.RANSAC, 2.5)
                            if matrix is not None and mask is not None:
                                inliers = mask.ravel().astype(bool)
                                count = int(inliers.sum())
                                trial.update(inliers=count, inlier_fraction=count / len(matches))
                                if count >= 12:
                                    center = np.median(p[inliers], axis=0)
                                    probes = np.float32([[center, center + [100., 0.], center + [0., 100.]]])
                                    projected = cv2.perspectiveTransform(probes, matrix)[0]
                                    sx = float(np.linalg.norm(projected[1] - projected[0]) / 100.)
                                    sy = float(np.linalg.norm(projected[2] - projected[0]) / 100.)
                                    baseline = output.shape[0] / original.shape[0]
                                    trial.update(scale_x=sx, scale_y=sy, measured_zoom=((sx+sy)/2) / baseline,
                                        baseline_scale=baseline, homography=matrix.tolist(),
                                        source_inlier_span=np.ptp(p[inliers], axis=0).tolist())
                                    candidates.append((count, trial, original))
                        trials.append(trial)
                    if not candidates:
                        result['zoom_measurements'].append({'label': label, 'output_time': output_time,
                            'status': 'INSUFFICIENT_FEATURE_MATCHES', 'trials': trials})
                        continue
                    _, best, original = max(candidates, key=lambda value: value[0])
                    source_path = directory / ('SOURCE_F_' + label + '.png')
                    cv2.imwrite(str(source_path), original)
                    result['zoom_measurements'].append({'label': label, 'output_time': output_time,
                        'status': 'MEASURED', 'selected': best, 'trials': trials, 'source_frame_path': str(source_path)})
            finally:
                rendered.release()
    finally:
        source.release()
    measured = result['zoom_measurements']
    if len(measured) == 2 and all(row['status'] == 'MEASURED' for row in measured):
        early, late = [row['selected']['measured_zoom'] for row in measured]
        result.update(measured_zoom_early=early, measured_zoom_late=late,
            measured_relative_scale_growth=late/early-1,
            zoom_increase_measured_in_actual_MP4=late > early + .005,
            limitations='Decoded-frame feature correspondence estimates delivered scale; does not verify identity, hands, instruments, lyric accuracy or final human approval.')
    write_json(directory / 'PIXEL_MEASUREMENTS.json', result)
    print(json.dumps({'pixel_proof': str(directory), 'measurements': result['zoom_measurements'],
        'growth': result.get('measured_relative_scale_growth')}, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, help='Already imported production revision (preferred; does not import again)')
    parser.add_argument('--package', type=Path, help='Optional first import, used only without --project')
    parser.add_argument('--handoff', type=Path)
    parser.add_argument('--media', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--evidence-package', type=Path, help='Reconstruct the diagnostic camera index from the verified original ZIP without modifying the imported parent')
    parser.add_argument('--analyse', type=Path, help='Existing TECHNICAL_VALIDATION.json: decode proof frames and measure actual MP4 zoom')
    arguments = parser.parse_args()
    if arguments.analyse:
        analyse_pixels(arguments.analyse)
        raise SystemExit(0)
    if arguments.project:
        project_path = arguments.project
    elif arguments.package:
        result = import_production_package(arguments.package, handoff_dir=arguments.handoff, media_path=arguments.media)
        project_path = result['project'].directory
    else:
        parser.error('Supply --project or --package')
    run(project_path, destination=arguments.destination, evidence_package=arguments.evidence_package)
