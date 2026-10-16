"""Reproducible synthetic fixture, explicitly labelled; no source media reanalysis."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ldporto_curator.config import load_config
from ldporto_curator.evidence_source import load_evidence
from ldporto_curator.full_handoff import validate_handoff
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.approval import file_hash
from ldporto_curator.utils import write_json, run
from PIL import Image, ImageDraw
from ldporto_curator.title_card import _load_font

PHRASES = [
    {'id':'S1','text':'Esta é uma demonstração sintética local do Curator. O primeiro quadro mostra um painel azul com três caixas numeradas, que representam a ordem dos episódios.'},
    {'id':'S2','text':'No segundo quadro, as caixas estão conectadas por uma linha. A sequência mantém os tempos da fonte, e as lacunas ficam registradas para a revisão humana.'},
    {'id':'S3','text':'O último quadro mostra a palavra revisão. Os vídeos continuam sendo propostas: a pessoa precisa assistir à prévia, conferir as legendas e aprovar cada episódio antes do render final.'},
]


def build_fixture(directory):
    directory.mkdir(parents=True, exist_ok=True)
    spec_file=directory/'speech_spec.json'
    if spec_file.exists() and json.loads(spec_file.read_text(encoding='utf-8'))['phrases'] != PHRASES:
        raise ValueError('Fixture existente tem outra fala; use nova pasta/versionamento')
    if not spec_file.exists():
        write_json(spec_file, {'synthetic':True,'phrases':PHRASES})
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        str(ROOT/'scripts/demo_speech.ps1'),'-SpecFile',str(directory/'speech_spec.json'),
        '-OutputDirectory',str(directory)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Narração local SAPI indisponível: '+result.stderr)
    segments, pcm, cursor, params = [], [], 0.0, None
    slide_files = []
    for index, phrase in enumerate(PHRASES,1):
        with wave.open(str(directory/(phrase['id']+'.wav')),'rb') as handle:
            if params is None:
                params=handle.getparams()
            assert handle.getframerate()==params.framerate and handle.getnchannels()==params.nchannels
            frames=handle.readframes(handle.getnframes())
            duration=handle.getnframes()/handle.getframerate()
        pcm.append(frames)
        segments.append({'segment_id':phrase['id'],'start':cursor,'end':cursor+duration,
            'speaker':'SYNTHETIC_NARRATOR','text':phrase['text'],'timestamp_method':'separate_sapi_wave_boundaries',
            'synthetic':True,'sentence_complete':True})
        cursor+=duration
        slide=Image.new('RGB',(1280,720),'#102B49')
        draw=ImageDraw.Draw(slide)
        draw.text((45,40),'DEMO SINTETICA LOCAL · V5.1',font=_load_font(38),fill='#BFFF36')
        draw.text((45,105),('Ordem dos episódios','Continuidade e lacunas','Revisão humana')[index-1],font=_load_font(52),fill='white')
        for n in range(3):
            x=80+n*390
            draw.rounded_rectangle((x,270,x+280,475),radius=20,fill='#285D86',outline='#BFFF36',width=4)
            draw.text((x+110,330),str(n+1),font=_load_font(62),fill='white')
            if index>=2 and n<2:
                draw.line((x+280,370,x+390,370),fill='#BFFF36',width=8)
        if index==3:
            draw.text((435,545),'REVISAO',font=_load_font(64),fill='#BFFF36')
        path=directory/f'slide_{index}.png'
        slide.save(path)
        slide_files.append((path,duration))
    with wave.open(str(directory/'narration.wav'),'wb') as handle:
        handle.setparams(params)
        handle.writeframes(b''.join(pcm))
    concat='\n'.join(f"file '{path.name}'\nduration {duration:.9f}" for path,duration in slide_files)+f"\nfile '{slide_files[-1][0].name}'\n"
    (directory/'slides.txt').write_text(concat,encoding='utf-8')
    media=directory/'SYNTHETIC_SOURCE.mp4'
    if not media.exists():
        run(['ffmpeg','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i','slides.txt',
            '-i','narration.wav','-t',f'{cursor:.9f}','-vf','fps=30,tpad=stop_mode=clone:stop_duration=60','-c:v','libx264','-preset','veryfast',
            '-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',media.name],cwd=directory)
    measured=float(json.loads(run(['ffprobe','-v','error','-show_format','-of','json',str(media)]).stdout)['format']['duration'])
    # Container can extend a fraction of a frame; speech ends at actual WAV boundary.
    source_hash=file_hash(media)
    metadata={'sha256':source_hash,'duration':measured,'width':1280,'height':720,'fps':30,
        'source':{'id':'curator_v5_synthetic_demo','title':'Demonstração sintética local V5.1',
                  'type':'local_synthetic_fixture','filename':media.name}, 'analyzer_version':'fixture_contract_v4.4'}
    scenes=[{'scene_id':f'SCENE_{i+1}','start':segment['start'],'end':segment['end'],
        'visual_description':('Painel azul com três caixas numeradas.','Painel azul com três caixas conectadas por uma linha.','Painel azul com caixas conectadas e texto REVISAO.')[i],
        'description_method':'authored_fixture_slide','confidence':1.0,'synthetic':True,
        'critical_text':True,'camera_policy':'source_preserve'} for i,segment in enumerate(segments)]
    files={'source/metadata.json':json.dumps(metadata,ensure_ascii=False).encode(),
        'editorial/candidate_catalog.json':json.dumps({'candidates':[]}).encode(),
        'editorial/default_shortlist.json':b'[]',
        'transcript/relevant_segments.jsonl':'\n'.join(json.dumps(s,ensure_ascii=False) for s in segments).encode(),
        'transcript/full_segments.jsonl':'\n'.join(json.dumps(s,ensure_ascii=False) for s in segments).encode(),
        'scenes.json':json.dumps(scenes,ensure_ascii=False).encode(),
        'SYNTHETIC_FIXTURE.md':b'Local synthetic source, generated slides and installed SAPI narration. No Lito footage, no measured word alignment, no human approval.'}
    manifest={'source_hash':source_hash,'schema_version':'4.4.0','package_type':'SECOND_CURATION_PARTIAL',
        'files':[{'path':name,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()} for name,payload in files.items()]}
    package=directory/'SECOND_CURATION_PARTIAL_SYNTHETIC.zip'
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,payload in sorted({**files,'SECOND_CURATION_MANIFEST.json':json.dumps(manifest).encode()}.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,payload)
    package_bytes=buffer.getvalue()
    if package.exists() and package.read_bytes()!=package_bytes:
        package=directory/f'SECOND_CURATION_PARTIAL_SYNTHETIC_{hashlib.sha256(package_bytes).hexdigest()[:12]}.zip'
    if not package.exists():
        package.write_bytes(package_bytes)
    write_json(directory/'fixture_provenance.json',{'synthetic':True,'voice':result.stdout.strip(),
        'source_sha256':source_hash,'source_duration_ffprobe':measured,'segments':segments,'scenes':scenes,
        'word_alignment':'not_measured','audio_human_review':'pending'})
    return package,media


def main():
    directory=ROOT/'docs/reports/curator_v5/demo_v2'
    package,media=build_fixture(directory)
    evidence=load_evidence(package)
    cfg=load_config(ROOT/'config.yaml')
    cfg['render']['prefer_nvenc']=False
    project=SeriesProject.create(evidence,directory/'output',cfg,duration_preset='under_30')
    episode=project.episodes()[0]
    preview=project.render(episode['episode_id'],media)
    handoff=project.export()
    example=directory.parent/'EXEMPLO_HANDOFF_CHATGPT.zip'
    if example.exists() and file_hash(example)!=file_hash(handoff):
        example=directory.parent/f'EXEMPLO_HANDOFF_CHATGPT_{file_hash(handoff)[:12]}.zip'
    shutil.copy2(handoff,example)
    manifest=validate_handoff(example)
    report={'synthetic_fixture':True,'package':str(package.relative_to(ROOT)),
        'project':str(project.directory.relative_to(ROOT)),'preview':str(preview.relative_to(ROOT)),
        'preview_sha256':file_hash(preview),'handoff':str(example.relative_to(ROOT)),
        'handoff_bytes':example.stat().st_size,'manifest_files':len(manifest['files']),
        'shortlist_count':len(evidence.get('shortlist',[])),
        'episodes':[{'id':e['episode_id'],'order':e['order'],'start':e['source_start'],
                     'end':e['source_end'],'state':e.get('state') or e.get('status')} for e in project.episodes()],
        'human_approvals':0,'final_rendered':False}
    write_json(directory/'DEMO_REPORT.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
