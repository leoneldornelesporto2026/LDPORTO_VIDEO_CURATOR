"""Desktop entrypoint (also compatible with PyInstaller on Windows)."""
from pathlib import Path
import sys
from ldporto_studio.gui import launch

root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
example=root/'example'/'CURADORIA_R57.zip'
if __name__=='__main__':
    launch(example if example.is_file() else None)
