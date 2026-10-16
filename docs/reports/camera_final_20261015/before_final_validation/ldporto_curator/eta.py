"""ETA from completed compatible stages and rolling work samples, never stage count."""
from collections import deque
import hashlib
import json
import platform
from statistics import median
import time
import os
import shutil
import subprocess
from functools import lru_cache
from .utils import load_json, write_json


@lru_cache(maxsize=1)
def gpu_profile():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return []
    try:
        result = subprocess.run([exe, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, check=True, timeout=5,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError):
        return []


class CuratorEta:
    def __init__(self, path, cfg, clock=None):
        self.path, self.cfg, self.clock = path, cfg, clock or time.monotonic
        self.key, self.stage, self.started, self.last = None, None, None, None
        self.samples, self.costs, self.history = deque(maxlen=12), {}, load_json(path, {'records':[]})

    def context(self, metadata, clips, operation=None):
        key = hashlib.sha256(json.dumps({'hardware':platform.processor(), 'machine':platform.machine(), 'gpus':gpu_profile(),
            'metadata':{k:metadata.get(k) for k in ('duration','width','height','fps')},
            'clip_seconds':[round(c['duration'],2) for c in clips], 'operation':operation,
            'config':{k:self.cfg.get(k) for k in ('render','camera','camera_v44','micro_perception','subtitles','ollama')}}, sort_keys=True).encode()).hexdigest()
        if key != self.key:
            self.costs, self.stage, self.last = {}, None, None
            self.samples.clear()
        self.key = key

    def update(self, event):
        now=self.clock(); stage=event.get('stage'); fraction=event.get('stage_fraction')
        if stage != self.stage:
            self.stage, self.started, self.last = stage, now, None
            self.samples.clear()
        if fraction is not None:
            if self.last and fraction > self.last[0] and now > self.last[1]:
                self.samples.append((now-self.last[1])/(fraction-self.last[0]))
            if not self.last or fraction > self.last[0]:
                self.last=(fraction,now)
            if fraction >= 1:
                self.costs[stage]=now-self.started
        stage_range=None
        if len(self.samples)>=3 and fraction is not None and 0 < fraction < 1:
            stage_range=[min(self.samples)*(1-fraction), max(self.samples)*(1-fraction)]
        matching=[r for r in self.history.get('records',[]) if r.get('profile')==self.key]
        future=[]
        for index,label in enumerate(event.get('plan',[]),1):
            if index <= event.get('step',0):
                continue
            samples=[sum(v for k,v in r.get('costs',{}).items() if k.startswith(str(index)+':')) for r in matching
                     if any(k.startswith(str(index)+':') for k in r.get('costs',{}))]
            if len(samples)<3:
                future=None
                break
            future.append((min(samples),max(samples)))
        total_range=[stage_range[0]+sum(v[0] for v in future),stage_range[1]+sum(v[1] for v in future)] if stage_range and future is not None else None
        if event.get('status') in {'done','completed'} and event.get('overall_fraction')==1 and self.key:
            self.history.setdefault('records',[]).append({'profile':self.key,'costs':self.costs,'recorded_at':time.time()})
            self.history['records']=self.history['records'][-50:]
            write_json(self.path,self.history)
        return {'stage_range_seconds':stage_range,'total_range_seconds':total_range}
