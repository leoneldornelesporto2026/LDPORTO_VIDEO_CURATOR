"""Review export preserves state, references real assets and stays external."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ldporto_curator import production_dossier as dossier


def project_at(path, *, text='Transcrição literal: avião, rota e segurança.'):
    path.mkdir()
    project = SimpleNamespace(directory=path, plan={'plan_id': 'P1', 'source_sha256': 'a' * 64,
        'production_import': {'format': 'CURATOR_READY', 'package_sha256': 'b' * 64,
            'revision_id': 'REV1', 'source_metadata': {'duration': 10., 'width': 1920, 'height': 1080, 'fps': 24.},
            'summary': {'title': 'Título original', 'approval_state': 'HUMAN_REVIEW_REQUIRED'},
            'media_reference': {'state': 'MEDIA_SELECTION_REQUIRED'}},
        'episodes': [{'episode_id': 'R1', 'piece_kind': 'REEL', 'production_origin_id': 'C1',
            'source_start': 1., 'source_end': 9., 'duration': 8., 'title_text': 'Título (original)',
            'human_approval': None, 'production_caption_gate': {'state': 'ALIGNMENT_REVIEW_REQUIRED', 'renderable': False},
            'camera_plan': {'mode': 'adaptive_timeline', 'segments': [
                {'start': 0., 'end': 8., 'mode': 'crop', 'center_x': .5, 'center_y': .4, 'zoom': 1.03}]}}],
        'extras': []}, evidence={'source': {'sha256': 'a' * 64}, 'segments': [
            {'segment_id': 'S1', 'start': 1., 'end': 9., 'text': text}]})
    project._visual_index = lambda: {}
    return project


def test_pdf_is_searchable_paginated_and_preserves_plan_without_overwrite(tmp_path):
    project = project_at(tmp_path / 'external', text='Palavra literal (avião) e rota. ' * 100)
    before = deepcopy((project.plan, project.evidence))
    result = dossier.export_production_dossier(project)
    payload = Path(result['path']).read_bytes()
    assert payload.startswith(b'%PDF-1.4') and payload.endswith(b'%%EOF\n')
    assert 'Título \\(original\\)'.encode('cp1252') in payload
    assert 'Palavra literal \\(avião\\) e rota.'.encode('cp1252') in payload
    assert b'ALIGNMENT_REVIEW_REQUIRED' in payload and ('a' * 64).encode() in payload
    assert result['searchable'] and result['pages'] >= 2 and not result['automatic_approval']
    assert result['sha256'] == hashlib.sha256(payload).hexdigest()
    assert (project.plan, project.evidence) == before
    second = dossier.export_production_dossier(project)
    assert second == result
    project.plan['episodes'][0]['title_text'] = 'Outro título'
    third = dossier.export_production_dossier(project)
    assert third['path'] != result['path'] and Path(result['path']).read_bytes() == payload
    # Every xref offset points to the corresponding object, including pages.
    xref = int(payload.split(b'startxref\n')[1].splitlines()[0])
    rows = payload[xref:].splitlines()
    for number, row in enumerate(rows[3:], 1):
        if row == b'trailer':
            break
        offset = int(row.split()[0])
        assert payload[offset:].startswith(f'{number} 0 obj\n'.encode())


def test_unicode_limit_is_reported_without_changing_original_text(tmp_path):
    project = project_at(tmp_path / 'external', text='Fala literal 🎬 漢字')
    result = dossier.export_production_dossier(project)
    assert result['unicode_replacements'] == 3
    assert project.evidence['segments'][0]['text'] == 'Fala literal 🎬 漢字'
    assert b'Encoding limitation:' in Path(result['path']).read_bytes()


def test_embeds_only_unchanged_hash_verified_real_jpeg_with_references(tmp_path):
    from PIL import Image
    project = project_at(tmp_path / 'external')
    image = project.directory / 'inputs' / 'actual.jpg'
    image.parent.mkdir()
    Image.new('RGB', (80, 40), color='navy').save(image)
    payload = image.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    index = {'assets': {'visual/actual.jpg': {'path': str(image), 'sha256': sha, 'bytes': len(payload)}},
             'frames': [{'frame_sample_id': 'F1', 'time': 2.5, 'asset_refs': ['visual/actual.jpg'],
                         'asset_kind': 'contact_sheet_not_individual_decoded_frame'}]}
    project._visual_index = lambda: index
    result = dossier.export_production_dossier(project)
    pdf = Path(result['path']).read_bytes()
    assert result['images_embedded'] == result['assets_referenced'] == result['frames_referenced'] == 1
    assert payload in pdf and sha.encode() in pdf and b'F1' in pdf and b'00:00:02.500' in pdf
    assert image.read_bytes() == payload and b'/DCTDecode' in pdf
    image.write_bytes(payload + b'changed')
    with pytest.raises(ValueError, match='no longer matches'):
        dossier.export_production_dossier(project)
    assert Path(result['path']).read_bytes() == pdf


def test_refuses_repository_destination_and_escaped_assets(tmp_path, monkeypatch):
    project = project_at(tmp_path / 'external')
    monkeypatch.setattr(dossier, '_REPOSITORY', tmp_path)
    with pytest.raises(ValueError, match='outside the repository'):
        dossier.export_production_dossier(project)
    monkeypatch.setattr(dossier, '_REPOSITORY', tmp_path / 'other_repository')
    outside = tmp_path / 'unrelated.jpg'
    outside.write_bytes(b'no image')
    project._visual_index = lambda: {'assets': {'x.jpg': {'path': str(outside), 'bytes': 8, 'sha256': 'b' * 64}}}
    with pytest.raises(ValueError, match='inside the external project'):
        dossier.export_production_dossier(project)
    assert not (project.directory / '04_RELATORIOS').exists()


def test_conflicting_existing_report_is_preserved(tmp_path):
    project = project_at(tmp_path / 'external')
    result = dossier.export_production_dossier(project)
    target = Path(result['path'])
    target.write_bytes(b'existing external alteration')
    with pytest.raises(ValueError, match='no overwrite'):
        dossier.export_production_dossier(project)
    assert target.read_bytes() == b'existing external alteration'
