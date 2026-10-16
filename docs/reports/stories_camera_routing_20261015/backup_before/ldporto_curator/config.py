from __future__ import annotations
from pathlib import Path
import yaml

def load_config(path: str|Path):
    p=Path(path)
    data=yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    base=p.parent.resolve()
    paths=data.setdefault("paths",{})
    for key in ("analysis_root","output_root","source_cache"):
        v=Path(paths.get(key,"."))
        paths[key]=str((base/v).resolve() if not v.is_absolute() else v)
    return data
