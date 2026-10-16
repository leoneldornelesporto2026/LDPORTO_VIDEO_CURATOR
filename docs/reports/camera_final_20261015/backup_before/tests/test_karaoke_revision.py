"""Caption styling forks one selected review without changing approved inputs."""
from copy import deepcopy

import pytest

from test_caption_revision import historical, inventory
from test_stories_60s_import import fixtures as story_fixtures
from ldporto_curator.series_workflow import SeriesProject


def test_caption_style_is_selected_and_frozen_before_timeline(historical, tmp_path):
    project, _ = historical
    original = project.episodes()[0]
    original['subtitle_overrides'] = {'font_size_final': 90, 'color': '#123456'}
    original['caption_timeline'] = {'ass': 'historical-caption-plan.ass'}
    other = deepcopy(original)
    other.update(episode_id='E2', title_text='Outra revisão aprovada',
                 human_approval={'human_reviewed': True})
    project.plan['episodes'].append(other)
    project.save()
    before = inventory(project.directory)
    original_plan = deepcopy(project.plan)

    derived = project.derive_caption_revision(tmp_path / 'karaoke_part_1',
        episode_ids=['E1'], subtitle_preset='LDP_CLEAN',
        subtitle_overrides={'font_size_final': 60, 'color': '#FFD700'})
    assert [row['episode_id'] for row in derived.episodes()] == ['E1']
    episode = derived.episodes()[0]
    assert episode['subtitle_overrides'] == {'font_size_final': 60, 'color': '#FFD700'}
    assert 'caption_timeline' not in episode
    for key in ('title_text', 'title_duration', 'camera_plan', 'source_start',
                'source_end', 'transcript_literal'):
        assert episode[key] == original[key]
    assert inventory(project.directory) == before
    assert project.plan == original_plan
    profile = derived.plan['caption_revision']['caption_styles']['E1']['resolved']
    assert profile['font_size_final'] == 60 and profile['color'] == '#FFD700'
    # A style applied after freezing would fail this exact integrity check.
    derived._verify_caption_revision(episode)
    episode['subtitle_overrides']['color'] = '#FFFFFF'
    with pytest.raises(ValueError, match='editorial'):
        derived._verify_caption_revision(episode)


def test_caption_overrides_alone_retain_existing_selected_style(historical, tmp_path):
    project, _ = historical
    project.episodes()[0]['subtitle_overrides'] = {'font_size_final': 56}
    project.save()
    derived = project.derive_caption_revision(tmp_path / 'style_amendment',
        episode_ids=['E1'], subtitle_overrides={'outline': 6})
    assert derived.episodes()[0]['subtitle_preset'] == 'LDP_CLEAN'
    assert derived.episodes()[0]['subtitle_overrides'] == {'font_size_final': 56, 'outline': 6}


def test_invalid_caption_profile_does_not_create_revision(historical, tmp_path):
    project, _ = historical
    before = inventory(project.directory)
    with pytest.raises(ValueError, match='Cor inválida'):
        project.derive_caption_revision(tmp_path / 'rejected_style', episode_ids=['E1'],
            subtitle_preset='LDP_CLEAN', subtitle_overrides={'color': 'invalid'})
    assert not (tmp_path / 'rejected_style').exists()
    assert inventory(project.directory) == before


def test_new_stories_use_reel_style_but_reopen_preserves_saved_reviews(tmp_path):
    evidence, document = story_fixtures()
    project = SeriesProject.create_stories(evidence, document, tmp_path / 'stories')
    assert all(episode['subtitle_preset'] == 'LDP_REELS_KARAOKE' for episode in project.episodes())
    project.episodes()[0]['subtitle_preset'] = 'LDP_CLEAN'
    project.episodes()[0]['human_approval'] = {'human_reviewed': True}
    project.save()
    before = inventory(project.directory)
    reopened = SeriesProject.create_stories(evidence, document, tmp_path / 'stories')
    assert reopened.episodes()[0]['subtitle_preset'] == 'LDP_CLEAN'
    assert reopened.episodes()[0]['human_approval'] == {'human_reviewed': True}
    assert inventory(project.directory) == before
