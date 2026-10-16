"""Story proposals remain separate, sentence-bounded, and human-review only."""
import json
from pathlib import Path

import pytest
from ldporto_curator.story_import import plan_reviewed_stories, MAX_STORY_SECONDS
from ldporto_curator.series_workflow import SeriesProject


def fixtures():
    segments = []
    # 4 complete sentences; 72 seconds -> split without cutting the 4th sentence.
    for i in range(4):
        segments.append({'segment_id': f'SEG_{i}', 'start': i * 18.0,
                         'end': (i+1)*18.0, 'text': f'Essa é a frase {i}.',
                         'sentence_complete': True})
    evidence = {
        'source': {'sha256': 'a' * 64, 'duration': 90.0, 'video_id': 'v1'},
        'segments': segments, 'words': [], 'scenes': [], 'timeline': [], 'story_arcs': [],
        'candidates': [{'candidate_id': 'C1', 'start': 0.0, 'end': 72.0,
                        'segment_ids': [r['segment_id'] for r in segments]}],
        'availability': {'segments': {'status': 'partial', 'count': 4}}
    }
    document = {
        'schema_version': 'LDP_STORIES_REVIEW_V1', 'state': 'PROPOSED_NOT_APPROVED',
        'source_sha256': 'a' * 64,
        'series': [{'series_id': 'S01', 'title': 'Acontecimento', 'parts': [
            {'part': 1, 'candidate_id': 'C1', 'start': 0.0, 'end': 72.0,
             'source_segment_ids': [r['segment_id'] for r in segments]}]}]
    }
    return evidence, document


def test_split_without_truncating_speech():
    evidence, document = fixtures()
    plan = plan_reviewed_stories(evidence, document)
    episodes = plan['episodes']
    assert len(episodes) == 2
    assert [(e['source_start'], e['source_end']) for e in episodes] == [(0, 54), (54, 72)]
    assert [e['episode_part_label'] for e in episodes] == ['Parte 1/2', 'Parte 2/2']
    assert all(0 < e['duration'] <= MAX_STORY_SECONDS for e in episodes)
    assert all(e['boundary_quality'] == 'sentence_or_qa' for e in episodes)
    assert all(e['title_duration'] == 5 for e in episodes)
    assert all(e['status'] == 'REVIEW_REQUIRED' and e['human_approval'] is None for e in episodes)
    assert plan['approval_required'] is True and not plan['human_approval']


def test_sha_is_required():
    evidence, document = fixtures()
    document['source_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='SHA256'):
        plan_reviewed_stories(evidence, document)


def test_incomplete_sentence_never_forced_into_60s():
    evidence, document = fixtures()
    evidence['segments'][-1]['text'] = 'Frase incompleta sem final'
    evidence['segments'][-1]['sentence_complete'] = False
    # The proposal is rejected: no invented or cut-off final sentence.
    with pytest.raises(ValueError, match='Nenhum Story elegível'):
        plan_reviewed_stories(evidence, document)


def test_disjoint_series_project_does_not_touch_existing(tmp_path):
    evidence, document = fixtures()
    previous = SeriesProject.create(evidence, tmp_path / 'output')
    original = (previous.directory / 'series_index.json').read_bytes()
    project = SeriesProject.create_stories(evidence, document, tmp_path / 'output')
    assert project.directory != previous.directory
    assert (previous.directory / 'series_index.json').read_bytes() == original
    assert project.plan['mode'] == 'SERIE_CRONOLOGICA'
    assert project.plan['story_import_report']['episodes'] == 2
    assert SeriesProject.create_stories(evidence, document, tmp_path / 'output').directory == project.directory
    assert not (project.directory / 'SERIES_PLAYLIST_ORDER.m3u').read_text().count('.mp4')
