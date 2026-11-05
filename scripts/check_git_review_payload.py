"""Reject non-script or oversized local content in staged input/output.

Run after git add, BEFORE commit. This file does not install a Git hook,
delete files, push, or stage anything.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import subprocess
import sys

ALLOWED_SUFFIXES={'.json','.md','.txt','.csv','.srt','.ass','.yaml','.yml'}
LIMIT=3*1024*1024

def validate():
    names=subprocess.check_output(['git','diff','--cached','--name-only','-z',
                                   '--diff-filter=ACMR']).split(b'\0')
    violations=[]
    accepted=[]
    for raw in names:
        if not raw:continue
        path=raw.decode('utf-8','surrogateescape').replace('\\','/')
        if not path.startswith(('input/','output/')):
            continue
        if path in ('input/README.md','output/README.md'):
            continue
        suffix=PurePosixPath(path).suffix.casefold()
        if (not path.startswith(('input/scripts/','output/scripts/'))
            or suffix not in ALLOWED_SUFFIXES):
            violations.append('Não é roteiro permitido: '+path)
            continue
        try:
            size=int(subprocess.check_output(['git','cat-file','-s',':'+path]).strip())
        except (OSError,ValueError,subprocess.CalledProcessError):
            violations.append('Não foi possível verificar staging: '+path)
            continue
        if size>LIMIT:
            violations.append(f'Roteiro acima de 3 MiB: {path}')
        else:
            accepted.append(path)
    return violations,accepted


if __name__=='__main__':
    try:
        failures,items=validate()
    except (OSError,subprocess.CalledProcessError) as error:
        print('Não foi possível ler staging Git:',error,file=sys.stderr)
        raise SystemExit(2)
    print('Roteiros staged:',len(items))
    for item in items:print('  ',item)
    if failures:
        for item in failures:print('BLOQUEADO:',item,file=sys.stderr)
        raise SystemExit(1)
    print('Tipos/tamanhos permitidos. Revise o conteúdo antes de enviar.')
