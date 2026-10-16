"""Grounded decision feedback for future learning, without a training/model side effect."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid


def record_feedback(document, catalog, compiled, root):
    candidates = {r['candidate_id']:r for r in catalog['candidates']}
    outputs = {}
    for row in compiled:
        outputs.setdefault(row['decision_id'].rsplit('_',1)[0],[]).append(row)
    records = []
    for action in document['actions']:
        before = [candidates[cid] for cid in action['candidate_ids']]
        records.append({'schema_version':'4.4.0','recorded_at':datetime.now(timezone.utc).isoformat(),
            'source_sha256':document['source_sha256'],'input_package_sha256':document.get('input_package_sha256'),
            'provider':document['provider'],'decision_id':action['decision_id'],'action':action['action'],
            'candidate_ids':action['candidate_ids'],'reason':action['reason'],
            'before':[{'candidate_id':r['candidate_id'],'rank':r.get('original_rank',r.get('rank')),
                       'start':r['start'],'end':r['end'],'commercial':r.get('commercial_classification'),
                       'score_components':r.get('score_components'),'context_requirement':r.get('context_requirement')} for r in before],
            'after':outputs.get(action['decision_id'],[]),'explicit_evidence_segment_ids':action.get('evidence_segment_ids',[]),
            'training_executed':False,'human_preview_approval':'not_implied_by_import',
            'label_status':'manual_editorial_decision' if document['provider']=='manual_json' else 'ai_proposal_requires_review'})
    path=Path(root)/'.cache/second_curation_feedback'/('feedback_'+uuid.uuid4().hex+'.jsonl')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    return path


def record_observed_performance(document, root, expected_source_sha256=None):
    """Store only explicitly supplied observations; never train or approve a render."""
    from jsonschema import Draft202012Validator, FormatChecker
    schema_path = Path(__file__).resolve().parents[1] / 'schemas/performance_feedback.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    checker = FormatChecker()
    @checker.checks('date-time', raises=(ValueError, TypeError))
    def dated(value):
        return 'T' in value and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    Draft202012Validator(schema, format_checker=checker).validate(document)
    if expected_source_sha256 and document['source_sha256'].lower() != expected_source_sha256.lower():
        raise ValueError('Feedback não corresponde ao SHA256 da fonte')
    if document.get('manual_approval') is True and document.get('manual_rejection') is True:
        raise ValueError('Aprovação e rejeição simultâneas são incompatíveis')
    # Reject NaN/Infinity explicitly even where Python's numeric validators accept them.
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
    path = Path(root) / '.cache/observed_performance' / ('observation_' + uuid.uuid4().hex + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding='utf-8')
    return path
