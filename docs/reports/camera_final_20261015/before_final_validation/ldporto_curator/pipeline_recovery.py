"""Recover local legacy decisions without reading or rerunning the Analyzer."""
from copy import deepcopy
from pathlib import Path

from .analysis_loader import AnalysisBundle
from .approval import file_hash, plan_signature
from .persisted_plan import PlanStore
from .utils import load_json, safe_name


def recover_local_plan(base, cfg, source_input, project_root):
    base = Path(base)
    old = load_json(base / 'EDIT_DECISIONS.json', {}) or {}
    if not old.get('approved_clips'):
        raise ValueError('Plano legado sem seleção recuperável. Execute CURAR explicitamente.')
    decisions = deepcopy(old['approved_clips'])
    preview = load_json(base / 'PREVIEW_REVIEW_V44.json', {}) or {}
    restored = deepcopy(decisions)
    reviewed = preview.get('reviewed_clip_id')
    for index, clip in enumerate(restored):
        if clip.get('clip_id') == reviewed and safe_name(reviewed) == reviewed:
            local = load_json(base / 'clips' / reviewed / 'clip.json', {}) or {}
            if local.get('clip_id') == reviewed:
                restored[index] = local
    # Known historical code is used only to explain a legacy preview, never as
    # permission to reuse its approval against a new render revision.
    baseline = Path(project_root) / 'docs/reports/curator_v5_2/render_p0/legacy_code_baseline'
    names = {'renderer_fingerprint': 'render.py',
             'subtitle_renderer_fingerprint': 'subtitles.py',
             'title_renderer_fingerprint': 'title_card.py'}
    hashes = {key: file_hash(baseline / name) for key, name in names.items()
              if (baseline / name).is_file()}
    preview_path = Path(preview.get('path', ''))
    media_ok = preview_path.is_file() and file_hash(preview_path) == preview.get('sha256')
    signature_ok = bool(preview.get('plan_signature') and
                        plan_signature(restored, cfg, reviewed, hashes) == preview['plan_signature'])
    if media_ok and signature_ok:
        decisions = restored
    handoff = load_json(base / 'CHATGPT_HANDOFF.json', {}) or {}
    seen, segments = set(), []
    for clip in handoff.get('approved_clips', []):
        for segment in clip.get('transcript_with_context', []):
            key = (segment.get('start'), segment.get('end'), segment.get('text'))
            if key not in seen:
                segments.append(deepcopy(segment))
                seen.add(key)
    segments.sort(key=lambda item: float(item.get('start') or 0))
    vid = old.get('video_id') or base.name
    source = old.get('source') or handoff.get('video', {}).get('source') or {}
    bundle = AnalysisBundle(
        root=base, video_id=vid,
        analysis={'metadata': {'source': source,
                              'duration': handoff.get('video', {}).get('duration'),
                              'sha256': None},
                  'legacy_recovery': {'coverage': 'partial_local_handoff',
                                      'caption_basis': 'existing_transcript_segment_timestamps',
                                      'original_analysis_sha256': None}},
        insights={}, editorial=[], review={}, segments=segments, words=[], captions=deepcopy(segments),
        timeline=[], scenes=[], people_observations=[], frame_samples=[], silences=[],
        speakers=[], speaker_person_mapping=[], questions_answers=[])
    store = PlanStore(base)
    doc, frozen = store.create(bundle, decisions, cfg, source_input)
    reason = ('Plano legado recuperado de arquivos locais. A identidade SHA-256 do vídeo original '
              'não foi registrada; selecione o original, gere nova prévia e aprove esta revisão.')
    doc.update(approval_state='NEEDS_REVIEW', invalidation_reason=reason,
               legacy_evidence={'preview': preview if media_ok else None,
                                'preview_sha256_verified': media_ok,
                                'refined_plan_matches_legacy_preview': signature_ok,
                                'analysis_coverage': 'partial_local_handoff',
                                'original_media_sha256': None,
                                'human_approval_reused': False})
    doc = store.save_state(doc)
    return doc, frozen
