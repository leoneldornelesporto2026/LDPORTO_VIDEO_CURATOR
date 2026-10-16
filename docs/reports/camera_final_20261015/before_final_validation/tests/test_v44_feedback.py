import json
import pytest
from jsonschema.exceptions import ValidationError
from ldporto_curator.feedback import record_observed_performance


def test_optional_observed_feedback_preserves_unknowns_and_source(tmp_path):
    row={'schema_version':'4.4.0','source_sha256':'a'*64,'clip_id':'C',
         'observed_at':'2026-10-07T00:00:00Z','metrics':{'views':12,'retention':None}}
    path=record_observed_performance(row,tmp_path,expected_source_sha256='a'*64)
    assert json.loads(path.read_text(encoding='utf-8')) == row
    with pytest.raises(ValueError,match='SHA256'):
        record_observed_performance(row,tmp_path,expected_source_sha256='b'*64)
    with pytest.raises(ValidationError):
        record_observed_performance({**row,'metrics':{'ctr':1.2}},tmp_path)
    with pytest.raises(ValidationError):
        record_observed_performance({**row,'observed_at':'invented-date'},tmp_path)
