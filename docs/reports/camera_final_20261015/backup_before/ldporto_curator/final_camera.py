"""Refine only selected clips after source resolution, preserving the legacy planner."""
import math
from .micro_perception import inspect_clip, open_clip_source
from .camera_refinement import refine_camera_plan, use_analyzer_director
from .utils import write_json
from .broadcast_graphics import inspect_candidate_graphics
from .storage import media_lease
from .smart_composition import improve_camera_plan


def refine_clip(bundle, clip, video, folder, cfg, progress=None):
    with media_lease(video):
        return _refine_clip(bundle, clip, video, folder, cfg, progress)


def _refine_clip(bundle, clip, video, folder, cfg, progress=None):
    if not cfg.get('camera', {}).get('v44_refinement', True):
        return clip['camera_plan']
    start, end = clip['source_start'], clip['source_end']
    micro = None
    plan = use_analyzer_director(getattr(bundle, 'director', []), start, end) if not clip.get('suggested_layout') else None
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
            plan = refine_camera_plan(micro, bundle.analysis['metadata'], start, end, cfg.get('camera_v44', {}), clip.get('suggested_layout'))
            plan['micro_status'] = micro['status']
        write_json(folder / 'clip_micro_perception.json', micro)
    # Only explicit camera re-generation reaches here. Never mutate a frozen review.
    # Input map ROIs require visual samples and human review; without evidence, source is preserved.
    if micro is not None and clip.get('suggested_layout') == 'source_preserve':
        micro = {**micro, 'visual_focus_regions': []}
    elif micro is not None and isinstance(clip.get('visual_focus_regions'), list):
        micro = {**micro, 'visual_focus_regions': clip['visual_focus_regions']}
    plan = improve_camera_plan(plan, micro, bundle.analysis['metadata'], start, end, cfg.get('camera_v44', {}))
    write_json(folder / 'FINAL_CAMERA_PLAN_V44.json', plan)
    clip['camera_plan'] = plan
    if any(s.get('graphics_regions') for s in plan['segments']):
        clip.setdefault('subtitle_plan', {})['margin_v_final'] = max(320, int(cfg.get('subtitles', {}).get('margin_v_final', 320)))
    return plan
