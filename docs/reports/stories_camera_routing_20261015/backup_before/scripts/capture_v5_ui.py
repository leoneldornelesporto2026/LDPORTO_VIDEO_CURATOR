"""Capture only the Curator fixture window, then close it. No human approval."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ldporto_curator.config import load_config
from ldporto_curator.series_review import SeriesReview
from ldporto_curator.series_review import PRESET_LABELS,PRESET_KEYS
from ldporto_curator.series_workflow import SeriesProject
from PIL import ImageGrab


def main():
    report_dir=ROOT/'docs/reports/curator_v5'
    report=json.loads((report_dir/'demo_v2/DEMO_REPORT.json').read_text(encoding='utf-8'))
    root=tk.Tk()
    root.withdraw()
    review=None
    try:
        review=SeriesReview(root,ROOT,load_config(ROOT/'config.yaml'))
        review.project=SeriesProject(ROOT/report['project'],review.cfg)
        review.duration.set(PRESET_LABELS[PRESET_KEYS.index(review.project.plan['duration_preset'])])
        review._refresh()
        review.geometry(f'{min(1240,root.winfo_screenwidth()-60)}x{min(860,root.winfo_screenheight()-60)}+20+20')
        review.attributes('-topmost',True)
        review.deiconify()
        root.update()
        for index,tab in enumerate(('MAPA','EDITOR','CAPAS')):
            review.tabs.select(index)
            if index==1:
                review.table.selection_set(review.project.episodes()[0]['episode_id'])
            began=time.monotonic()
            while time.monotonic()-began<.6:
                root.update()
                time.sleep(.03)
            x,y=review.winfo_rootx(),review.winfo_rooty()
            image=ImageGrab.grab(bbox=(x,y,x+review.winfo_width(),y+review.winfo_height()))
            image.save(report_dir/f'GUI_{tab}.png')
        print('3 captures saved; actual Tk widgets on Windows, fixture only. Human QA remains pending.')
    finally:
        if review:
            review._close()
        root.destroy()


if __name__=='__main__':
    main()
