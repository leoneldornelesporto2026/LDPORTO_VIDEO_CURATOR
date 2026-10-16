from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT if (ROOT/'ldporto_curator').is_dir() else Path('/mnt/data/curator_work')
if PROJECT_ROOT.is_dir():
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPT = ROOT / 'payload' / 'scripts' / 'RECUPERAR_OUTPUT_LDPORTO.py'
if not SCRIPT.is_file():
    SCRIPT = ROOT / 'scripts' / 'RECUPERAR_OUTPUT_LDPORTO.py'
SPEC = importlib.util.spec_from_file_location('recovery_output', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_original_ids_are_unique_and_exact():
    assert len(module.EXPECTED_IDS) == 16
    assert len(set(module.EXPECTED_IDS)) == 16
    assert module.EXPECTED_IDS[5] == module.STORY06


def test_verified_cache_zip_rejects_modified_file(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'source').mkdir()
    (cache / 'source' / 'metadata.json').write_text(json.dumps({'sha256': module.EXPECTED_SOURCE}), encoding='utf-8')
    b = b'v1'
    (cache / 'file.json').write_bytes(b)
    (cache / 'SECOND_CURATION_MANIFEST.json').write_text(json.dumps({
        'source_hash': module.EXPECTED_SOURCE,
        'files': [{'path': 'file.json', 'bytes': len(b), 'sha256': __import__('hashlib').sha256(b).hexdigest()}]
    }), encoding='utf-8')
    output = tmp_path / 'recreated.zip'
    assert module._verified_cache_zip(cache, output).is_file()
    with zipfile.ZipFile(output) as z:
        assert z.read('file.json') == b
    (cache / 'file.json').write_bytes(b'v2')
    import pytest
    with pytest.raises(ValueError, match='Evidência do cache foi alterada'):
        module._verified_cache_zip(cache, output)


def test_recovery_refuses_missing_original(tmp_path):
    import argparse
    import pytest
    root = tmp_path / 'curator'
    (root / 'ldporto_curator').mkdir(parents=True)
    (root / 'ldporto_curator' / 'series_workflow.py').touch()
    (root / 'output').mkdir()
    with pytest.raises(ValueError, match='Vídeo original'):
        module._prepare(argparse.Namespace(projeto=root, midia=None, pacote=None, stories=None, manifesto=None))
    assert not list((root / 'output').iterdir())


def test_plan_recreated_from_user_verified_package():
    # Optional local reference fixture bundled separately in dev environment.
    source = Path('/mnt/data/SECOND_CURATION_PARTIAL_zd_wjssZ7mc_20261015_030411_890527_b3fdef.zip')
    editorial = Path('/mnt/data/curator_work/docs/second_curation/zd_wjssZ7mc/STORIES_SEQUENCIAIS_REVISAR.json')
    lib = Path('/mnt/data/curator_work')
    import pytest
    if not source.is_file() or not editorial.is_file() or not lib.is_dir():
        pytest.skip('Optional original analyzer fixture not bundled with patch')
    sys.path.insert(0, str(lib))
    from ldporto_curator.evidence_source import load_evidence
    from ldporto_curator.story_import import plan_reviewed_stories
    evidence = load_evidence(source)
    plan = plan_reviewed_stories(evidence, json.loads(editorial.read_text(encoding='utf-8')))
    assert tuple(e['episode_id'] for e in plan['episodes']) == module.EXPECTED_IDS
    assert plan['human_approval'] is None
    assert all(e.get('human_approval') is None for e in plan['episodes'])
