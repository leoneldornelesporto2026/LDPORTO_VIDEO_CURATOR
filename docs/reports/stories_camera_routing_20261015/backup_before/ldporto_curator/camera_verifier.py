"""Independent samples from rendered media; proxies are explicitly uncalibrated."""
from pathlib import Path
import cv2
import numpy as np
from .micro_perception import _detector


def verify_camera(path, clip, cfg=None):
    cfg = cfg or {}
    model = Path(cfg.get('face_model') or Path(__file__).resolve().parents[2] / 'LDPORTO_VIDEO_ANALYZER/models/face_detection_yunet_2023mar.onnx')
    detector = _detector(model)
    cap = cv2.VideoCapture(str(path))
    rows, issues, previous, changes = [], [], None, []
    try:
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1)
        for t in np.linspace(.2, max(.2, duration-.2), min(12, max(3, int(duration)))):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t)*1000)
            ok, frame = cap.read()
            if not ok:
                issues.append({'type':'UNDECODABLE_SAMPLE', 'time':float(t), 'severity':'error'})
                continue
            height, width = frame.shape[:2]
            small = cv2.resize(frame, (min(960,width), round(height*min(960,width)/width)))
            faces = detector(small) if detector else []
            clear = []
            for face in faces:
                box=face['face_bbox']; sh,sw=small.shape[:2]
                roi=small[int(box['y']*sh):int((box['y']+box['height'])*sh),int(box['x']*sw):int((box['x']+box['width'])*sw)]
                if not roi.size or cv2.Laplacian(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var() < 40:
                    continue
                clear.append(face)
                if min(box['x'],box['y'],1-box['x']-box['width'],1-box['y']-box['height']) < .008:
                    issues.append({'type':'FACE_AT_OUTPUT_EDGE', 'time':float(t), 'severity':'warning', 'bbox':box})
            tiny = cv2.resize(frame,(90,160))
            if previous is not None:
                changes.append(float(cv2.absdiff(tiny,previous).mean()/255))
            previous=tiny
            rows.append({'time':float(t),'clear_face_count':len(clear),'faces':clear})
    finally:
        cap.release()
    return {'schema_version':'4.4.0','status':'needs_review' if issues or detector is None else 'measured',
            'uses_rendered_frames':True,'sample_count':len(rows),'samples':rows,'issues':issues,
            'identity_accuracy':None,'subject_visibility_fraction':sum(r['clear_face_count']>0 for r in rows)/max(1,len(rows)),
            'scene_change_proxy_mean':float(np.mean(changes)) if changes else None,
            'measurement_limits':'Sparse YuNet/sharpness and frame-change proxies; source cuts and gestures also change frames. No calibrated identity or perceptual accuracy.',
            'gc_copy_validation':'composition regression tested; source-specific visual review required',
            'camera_diagnostics':clip.get('camera_plan',{}).get('diagnostics',{})}
