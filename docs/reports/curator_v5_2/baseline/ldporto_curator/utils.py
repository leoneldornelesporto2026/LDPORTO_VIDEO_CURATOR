from __future__ import annotations
import json, re, subprocess, shutil, hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs

def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def youtube_id(value: str|None):
    if not value: return None
    value=str(value).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value): return value
    try:
        u=urlparse(value)
        if u.hostname in {"youtu.be","www.youtu.be"}: return u.path.strip("/").split("/")[0]
        if u.hostname and "youtube.com" in u.hostname:
            if u.path == "/watch": return parse_qs(u.query).get("v", [None])[0]
            parts=[x for x in u.path.split("/") if x]
            if parts and parts[0] in {"shorts","live","embed"} and len(parts)>1: return parts[1]
    except Exception: pass
    m=re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", value)
    return m.group(1) if m else None

def safe_name(s: str):
    s=re.sub(r"[^A-Za-z0-9._-]+","_",s or "item")
    return s[:100].strip("._") or "item"

def run(cmd, *, cwd=None, timeout=None, check=True):
    p=subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"Comando falhou ({p.returncode}): {cmd}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p

def which(name): return shutil.which(name)

def file_fingerprint(path: Path):
    st=path.stat(); return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
