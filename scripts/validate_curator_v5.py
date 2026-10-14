"""Run local regression and artifact demo; persist exact counts and preservation hashes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'docs/reports/curator_v5'
sys.path.insert(0,str(ROOT))
from ldporto_curator.approval import file_hash
from ldporto_curator.full_handoff import validate_handoff
from ldporto_curator.utils import write_json


def execute(arguments, filename):
    result=subprocess.run([sys.executable,*arguments],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',
                          env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'})
    (REPORT/filename).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Falhou: {arguments}; veja {filename}')
    return result


def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    execute(['-m','compileall','-q','ldporto_curator','cli.py','scripts'],'COMPILACAO.txt')
    execute(['-m','pytest','-q','--junitxml='+str(REPORT/'pytest_junit.xml')],'REGRESSAO_COMPLETA.txt')
    xml=ET.parse(REPORT/'pytest_junit.xml').getroot()
    suites=list(xml.iter('testsuite'))
    counts={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    counts['seconds']=sum(float(s.get('time',0)) for s in suites)
    execute(['scripts/demo_curator_v5.py'],'DEMO_LOG.txt')
    demo=json.loads((REPORT/'demo_v2/DEMO_REPORT.json').read_text(encoding='utf-8'))
    packet=ROOT/demo['handoff']
    manifest=validate_handoff(packet)
    exact=REPORT/'EXEMPLO_HANDOFF_CHATGPT.zip'
    if exact.exists() and file_hash(exact)!=file_hash(packet):
        archive=REPORT/('EXEMPLO_HANDOFF_CHATGPT_previous_'+file_hash(exact)[:12]+'.zip')
        if not archive.exists():
            shutil.copy2(exact,archive)
    if packet!=exact:
        shutil.copy2(packet,exact)
    probe=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(ROOT/demo['preview'])],
                          capture_output=True,text=True,check=True)
    (REPORT/'FFPROBE_DEMO.json').write_text(probe.stdout,encoding='utf-8')
    frame=REPORT/'PREVIEW_FRAME_FINAL.png'
    if not frame.exists():
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss','5','-i',str(ROOT/demo['preview']),
                        '-frames:v','1',str(frame)],check=True)
    screenshots=execute(['scripts/capture_v5_ui.py'],'GUI_CAPTURE_LOG.txt')
    baseline=json.loads((REPORT/'BASELINE_SHA256.json').read_text(encoding='utf-8'))
    preservation={name:{'before':sha,'after':file_hash(ROOT/name),'unchanged':sha==file_hash(ROOT/name)} for name,sha in baseline['files'].items()}
    changed=[name for name,row in preservation.items() if not row['unchanged']]
    unexpected=[name for name in changed if name not in {'cli.py','ldporto_curator/gui.py','ldporto_curator/pipeline.py'}]
    if unexpected:
        raise RuntimeError('Arquivo legado inesperadamente alterado: '+str(unexpected))
    validation={'client_date':'2026-10-13','python':sys.version.split()[0],
        'command':str(Path(sys.executable).name)+' -m pytest -q --junitxml=docs/reports/curator_v5/pytest_junit.xml',
        'tests':counts,'baseline_tests':37,'legacy_changes':changed,
        'original_schemas_overrides_config_bats':'preserved by hash','git_repository':False,
        'source_processing':'No models, reanalysis, download, commit or publication; active Analyzer untouched',
        'demo':demo,'handoff_exact':exact.relative_to(ROOT).as_posix(),'handoff_sha256':file_hash(exact),
        'handoff_files':len(manifest['files']),'human_approvals_demo':0,
        'screenshots':['GUI_MAPA.png','GUI_EDITOR.png','GUI_CAPAS.png'],
        'manual_homologation':'pending; see DIAGNOSTICO_ANTES_DEPOIS.md and PRIMEIROS_PASSOS_WINDOWS.md'}
    write_json(REPORT/'PRESERVACAO_LEGADO.json',preservation)
    write_json(REPORT/'VALIDACAO_FINAL.json',validation)
    source_files=[*ROOT.glob('ldporto_curator/*.py'),ROOT/'cli.py',ROOT/'README.md',
                  *ROOT.glob('schemas/*.json'),*ROOT.glob('tests/test_*.py'),*ROOT.glob('scripts/*')]
    rows={p.relative_to(ROOT).as_posix():{'bytes':p.stat().st_size,'sha256':file_hash(p)} for p in source_files if p.is_file()}
    write_json(REPORT/'ARQUIVOS_E_HASHES.json',rows)
    phases=[
        ('0 — Auditoria/preservação','P0','BASELINE_SHA256.json, baseline/, PRESERVACAO_LEGADO.json','37 testes preexistentes; hashes originais; sem .git/instalação/Analyzer'),
        ('1 — Evidências/dossiê','P0','evidence_source.py, full_handoff.py','Pacotes/snapshots íntegros; shortlist zero; transcrição parcial explícita; privado sanitizado'),
        ('2 — Story engine/durações','P0','series_planner.py, duration_presets.py, series_plan_v5.schema.json','Série dinâmica; Q&A/frases; oito faixas; cobertura e divisão/reordenação'),
        ('3 — GUI/revisão','P1','series_review.py, local_player.py, gui.py, cli.py','Tk real capturado; callbacks headless testados; avançados JSON; player sem sync fino garantido'),
        ('4 — Legendas/câmera/capas/áudio','P1','subtitle_presets.py, title_presets.py, thumbnail_presets.py, media_effects.py, series_workflow.py','Frames e FFmpeg reais; regras de safe fallback; sem detecção/reanálise'),
        ('5 — Preview/gates/export','P1','episode_approval.py, series_workflow.py','Prévia e final de integração; gates/hash/tamper; demo sem aprovação humana'),
        ('6 — Regressão/handoff','P0/P1','VALIDACAO_FINAL.json, REGRESSAO_COMPLETA.txt, pytest_junit.xml, EXEMPLO_HANDOFF_CHATGPT.zip','Testes completos; ZIP CRC/SHA; humanos e Lito pendentes'),
    ]
    lines=['# Relatório por fase — Curator V5.1','',f"Regressão: {counts['passed']} passed; {counts['failures']} failures; {counts['errors']} errors; {counts['skipped']} skipped; {counts['seconds']:.2f}s.",
           '', 'Hashes por arquivo: `ARQUIVOS_E_HASHES.json`; comparação de legado: `PRESERVACAO_LEGADO.json`.',
           '', '| Fase | Prioridade | Arquivos/artefatos | Evidência e risco |','|---|---|---|---|']
    lines += [f'| {a} | {b} | {c} | {d} |' for a,b,c,d in phases]
    lines += ['',f"ZIP textual: {exact.name}, {exact.stat().st_size} bytes, SHA256 `{file_hash(exact)}`.",
              f"Preview real: `{demo['preview']}`; sequência de {len(demo['episodes'])} partes; primeira gerada, restantes pendentes.",
              '', 'Nenhuma fase foi homologada editorialmente por uma pessoa. O material do Lito não foi usado. Limites de produto estão em DIAGNOSTICO_ANTES_DEPOIS.md.']
    (REPORT/'RELATORIO_POR_FASE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'tests':counts,'demo_preview':demo['preview'],'handoff':exact.relative_to(ROOT).as_posix(),
                      'handoff_bytes':exact.stat().st_size,'legacy_changes':changed},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
