"""Testa proteção do restaurador sem depender de GUI/GPU ou mídia do usuário."""
from pathlib import Path
import ast
import importlib.util

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'REPARAR_STORY06_SEM_QWEN.py'


def test_script_imports_and_preserves_manual_approval():
    tree = ast.parse(MODULE.read_text(encoding='utf-8'))
    assert any(isinstance(n, ast.FunctionDef) and n.name == 'check_case' for n in tree.body)
    code = MODULE.read_text(encoding='utf-8')
    assert 'derive_caption_revision' in code
    assert 'source_sha256' in code
    assert 'LDP_REELS_KARAOKE' in code
    assert 'renderizar_preview and not args.aplicar' in code
    assert 'approved": False' in code
    assert 'hashes' in code


def test_cli_dry_run_exits_without_project_files(tmp_path):
    import subprocess
    import sys
    p = subprocess.run([sys.executable, str(MODULE), '--projeto', str(tmp_path/'unknown'),
                        '--manifesto', str(tmp_path/'missing')], capture_output=True, text=True)
    assert p.returncode != 0
    assert not (tmp_path/'unknown').exists()
