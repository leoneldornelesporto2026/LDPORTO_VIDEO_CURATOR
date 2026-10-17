"""Read-only camera coverage inspector for V5 show Stories and Reels plans."""
import argparse,json
from pathlib import Path

def inspect(name,ep):
    plan=ep.get('camera_plan') or {}
    segments=plan.get('segments') or []
    modes={}
    for s in segments:
        mode=s.get('mode','unknown');modes[mode]=modes.get(mode,0)+1
    effective=sum(1 for s in segments if s.get('mode') in {'crop','dynamic_crop','person_focus','smart_zoom'} or
                  (isinstance(s.get('zoom'),(int,float)) and s['zoom']>1.005))
    return {'name':name,'mode':ep.get('camera_mode'), 'segments':len(segments),'effective_crop_or_zoom_segments':effective,'modes':modes,'warning':'NÃO HÁ ZOOM REAL COMPROVADO' if effective==0 else 'Verificar MP4 e safe-area'}

p=argparse.ArgumentParser();p.add_argument('series_index',type=Path)
a=p.parse_args();d=json.loads(a.series_index.read_text('utf-8-sig'))
for ep in d.get('episodes',[]):print(json.dumps(inspect(ep.get('title_text') or ep['episode_id'],ep),ensure_ascii=False))
print('Verificação de plano NÃO prova entrega no MP4. Confirmar quadro a quadro após render.')
