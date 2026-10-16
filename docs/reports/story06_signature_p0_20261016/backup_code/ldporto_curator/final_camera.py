"""Refine only selected clips after source resolution, preserving the legacy planner."""
import math
from copy import deepcopy
from .micro_perception import inspect_clip, open_clip_source
from .camera_refinement import refine_camera_plan, use_analyzer_director
from .utils import write_json
from .broadcast_graphics import inspect_candidate_graphics
from .storage import media_lease
from .smart_composition import improve_camera_plan


def refine_from_existing_metadata(clip, metadata, *, micro=None, director=None, cfg=None,
                                  prefer_visual_focus=False):
    """Return a new camera proposal using saved evidence only, without any I/O.

    The caller creates a separate revision. Clip/editorial/caption inputs and any
    frozen historical plan stay untouched. No detector, model, ASR or renderer is
    called, including when the available visual evidence is insufficient.
    """
    cfg = cfg or {}
    start, end = float(clip['source_start']), float(clip['source_end'])
    if not all(math.isfinite(t) for t in (start, end)) or start < 0 or end <= start:
        raise ValueError('Invalid camera-only source interval')
    if micro is not None and not isinstance(micro, dict):
        raise ValueError('Existing camera metadata must be an object')
    evidence = deepcopy(micro or {})
    style = deepcopy(cfg.get('camera_v44', {}))
    suggested = clip.get('suggested_layout')
    # Explicit *new revision* opt-in. Historical plans are never mutated here.
    # SECOND_CURATOR often labels every clip source_preserve even when measured
    # single-face geometry is available. Keep blur for ambiguous/map shots.
    reframe_requested = (prefer_visual_focus is True and
                         clip.get('curation_source') == 'SECOND_CURATOR' and
                         suggested == 'source_preserve' and
                         bool(evidence.get('observations')))
    if reframe_requested:
        suggested = None
        # Face-only shot windows are often 2-3s in the VARIG edit. The
        # default 3s minimum suppresses *every* otherwise safe crop. An
        # explicit camera-only revision may shorten dwell to 2s, never below.
        style.setdefault('director_style', {})['min_hold_seconds'] = 2.0
    if clip.get('camera_mode') in {'SOURCE_PRESERVE', 'source_preserve'}:
        suggested = 'source_preserve'
    if suggested == 'source_preserve':
        evidence['visual_focus_regions'] = []
    elif isinstance(clip.get('visual_focus_regions'), list):
        evidence['visual_focus_regions'] = deepcopy(clip['visual_focus_regions'])
    if evidence.get('observations'):
        plan = refine_camera_plan(evidence, metadata, start, end, style, suggested)
    else:
        plan = use_analyzer_director(director or [], start, end) if not suggested else None
        if plan is None:
            old = clip.get('camera_plan') or {}
            preserved = (old.get('mode') == 'full_frame_blur' or
                old.get('mode') == 'adaptive_timeline' and old.get('segments') and
                all(row.get('mode') == 'full_frame_blur' for row in old['segments']))
            plan = deepcopy(old) if preserved else {}
        if not plan or suggested == 'source_preserve':
            plan = {'schema_version':'4.4.0', 'mode':'adaptive_timeline',
                    'visual_source':'existing_metadata_fallback', 'needs_review':True,
                    'segments':[{'start':0., 'end':end-start, 'mode':'full_frame_blur',
                                 'zoom':1., 'motion_follow':False,
                                 'reason':'INSUFFICIENT_EXISTING_VISUAL_EVIDENCE',
                                 'evidence_role':'SOURCE_PRESERVE', 'speaker_identity_confirmed':False}]}
        elif plan.get('mode') == 'full_frame_blur' and not plan.get('segments'):
            plan.update(mode='adaptive_timeline', segments=[{'start':0., 'end':end-start,
                'mode':'full_frame_blur', 'zoom':1., 'reason':'EXISTING_SOURCE_PRESERVE',
                'evidence_role':'SOURCE_PRESERVE'}])
        for row in plan.get('segments') or []:
            if row.get('mode') == 'full_frame_blur' and not row.get('reason'):
                row['reason'] = 'INSUFFICIENT_EXISTING_VISUAL_EVIDENCE'
    unreviewed_graphics = 0
    for row in plan.get('segments') or []:
        regions = row.get('graphics_regions') or []
        if row.get('mode') in {'crop','split_screen'} and row.get('graphics_policy') == 'single_copy_source_strip' and (
                not regions or not all(region.get('reviewed') is True and region.get('evidence_kind') == 'visual_region'
                                       for region in regions)):
            # Legacy edge-density candidates frequently describe a shirt or
            # shelf. They cannot certify a recomposition that duplicates it.
            row.update(mode='full_frame_blur', person_id=None, person_ids=[], motion_follow=False,
                       zoom=1., reason='UNREVIEWED_GRAPHICS_PRESERVE_SOURCE', evidence_role='SOURCE_PRESERVE')
            for key in ('zoom_start','zoom_end','zoom_transition_start','zoom_transition_duration','zoom_easing'):
                row.pop(key, None)
            unreviewed_graphics += 1
    plan = improve_camera_plan(plan, evidence, metadata, start, end, style)
    plan.setdefault('diagnostics', {}).update(existing_metadata_only=True,
        new_analysis_executed=False, source_timestamps_changed=False,
        subtitle_inputs_changed=False, editorial_decisions_recomputed=False,
        existing_micro_observations_available=bool(evidence.get('observations')),
        unreviewed_graphics_source_preserved=unreviewed_graphics,
        safe_second_curator_reframe_requested=reframe_requested,
        effective_crop_count=sum(row.get('mode') == 'crop' for row in plan.get('segments') or []))
    plan['needs_review'] = True
    return plan


def refine_clip(bundle, clip, video, folder, cfg, progress=None):
    with media_lease(video):
        return _refine_clip(bundle, clip, video, folder, cfg, progress)


def _refine_clip(bundle, clip, video, folder, cfg, progress=None):
    if not cfg.get('camera', {}).get('v44_refinement', True):
        return clip['camera_plan']
    start, end = clip['source_start'], clip['source_end']
    # A second-curation global SOURCE_PRESERVE label must not defeat *measured*
    # presenter crops on a freshly created review revision. No visual evidence,
    # graphics uncertainty, or map -> existing conservative fallback remains.
    reframe_requested = (clip.get('curation_source') == 'SECOND_CURATOR' and
                         clip.get('suggested_layout') == 'source_preserve')
    suggested_for_camera = None if reframe_requested else clip.get('suggested_layout')
    micro = None
    plan = use_analyzer_director(getattr(bundle, 'director', []), start, end) if not suggested_for_camera else None
    if plan is not None:
        graphics = inspect_candidate_graphics(video, [{'core_moment':{'start':start,'end':end}}], limit=1)
        # A source crop certificate does not certify a changed GC composition.
        if any(r.get('regions') for r in graphics.get('intervals', [])):
            plan = None
        else:
            plan['graphics_status'] = graphics['status']
    if plan is None:
        micro_cfg = cfg.get('micro_perception', {})
        budget = float(micro_cfg.get('max_clip_seconds', 240))
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError('Invalid clip micro-perception budget')
        if end - start > budget:
            cap, _ = open_clip_source(video, start, end)
            cap.release()
            graphics = inspect_candidate_graphics(video, [{'core_moment':{'start':start,'end':end}}], limit=1)
            regions = [region for interval in graphics.get('intervals', []) for region in interval.get('regions', [])]
            micro = {'status':'skipped_budget', 'scope':'selected_clip', 'start':start, 'end':end,
                     'sample_count':0, 'dense_perception_executed':False, 'budget_seconds':budget,
                     'broadcast_graphics':graphics}
            plan = {'schema_version':'4.4.0', 'mode':'adaptive_timeline', 'visual_source':'source_preserve_budget',
                    'micro_status':'skipped_budget', 'needs_review':True, 'graphics_status':graphics['status'],
                    'segments':[{'start':0., 'end':end-start, 'mode':'full_frame_blur', 'zoom':1.,
                                 'reason':'MICRO_PERCEPTION_BUDGET_SOURCE_PRESERVE', 'evidence_role':'SOURCE_PRESERVE',
                                 'speaker_identity_confirmed':False, 'graphics_regions':regions,
                                 'graphics_policy':'single_copy_source_strip' if regions else 'none'}],
                    'diagnostics':{'dense_perception_executed':False, 'resolved_visual_focus_fraction':0.}}
        else:
            micro = inspect_clip(video, clip, folder / 'micro_cache', micro_cfg, progress=progress)
            style = deepcopy(cfg.get('camera_v44', {}))
            if reframe_requested:
                style.setdefault('director_style', {})['min_hold_seconds'] = 2.0
            plan = refine_camera_plan(micro, bundle.analysis['metadata'], start, end, style, suggested_for_camera)
            plan['micro_status'] = micro['status']
        write_json(folder / 'clip_micro_perception.json', micro)
    # Only explicit camera re-generation reaches here. Never mutate a frozen review.
    # Input map ROIs require visual samples and human review; without evidence, source is preserved.
    if micro is not None and suggested_for_camera == 'source_preserve':
        micro = {**micro, 'visual_focus_regions': []}
    elif micro is not None and isinstance(clip.get('visual_focus_regions'), list):
        micro = {**micro, 'visual_focus_regions': clip['visual_focus_regions']}
    style = deepcopy(cfg.get('camera_v44', {}))
    if reframe_requested:
        style.setdefault('director_style', {})['min_hold_seconds'] = 2.0
    plan = improve_camera_plan(plan, micro, bundle.analysis['metadata'], start, end, style)
    plan.setdefault('diagnostics', {})['safe_second_curator_reframe_requested'] = reframe_requested
    plan['diagnostics']['effective_crop_count'] = sum(x.get('mode') == 'crop' for x in plan.get('segments') or [])
    write_json(folder / 'FINAL_CAMERA_PLAN_V44.json', plan)
    clip['camera_plan'] = plan
    if any(s.get('graphics_regions') for s in plan['segments']):
        clip.setdefault('subtitle_plan', {})['margin_v_final'] = max(320, int(cfg.get('subtitles', {}).get('margin_v_final', 320)))
    return plan
