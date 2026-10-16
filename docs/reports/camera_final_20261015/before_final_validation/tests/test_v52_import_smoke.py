import hashlib
import json
import zipfile
import pytest
from ldporto_curator.import_smoke import inspect_media,smoke_import


def package(path):
    segments=[{'segment_id':f'S{i}','start':i*100,'end':(i+1)*100,'text':f'Bloco de teste {i}.','sentence_complete':True} for i in range(5)]
    files={'source/metadata.json':json.dumps({'sha256':'source_hash','duration':500,'source':{'id':'fixture_80'},'build_mismatch':{'inference':'A','replay':'B'}}).encode(),
           'editorial/candidate_catalog.json':json.dumps({'candidates':[{'candidate_id':f'C{i}','start':i*5,'end':i*5+10,'segment_ids':[f'S{int(i*5//100)}']} for i in range(80)]}).encode(),
           'editorial/review_queue.json':json.dumps({'candidate_ids':[f'C{i}' for i in range(77)]}).encode(),
           'editorial/default_shortlist.json':b'[]',
           'transcript/relevant_segments.jsonl':'\n'.join(json.dumps(s) for s in segments).encode()}
    manifest={'source_hash':'source_hash','files':[{'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()]}
    with zipfile.ZipFile(path,'w') as z:
        for n,b in files.items():z.writestr(n,b)
        z.writestr('SECOND_CURATION_MANIFEST.json',json.dumps(manifest))
    return path


def test_80_candidates_77_review_zero_shortlist_is_not_promoted(tmp_path):
    path=package(tmp_path/'fixture_closed.zip');before=path.read_bytes()
    evidence,plan,report=smoke_import(path)
    assert (report['candidates'],report['review_queue'],report['official_shortlist'])==(80,77,0)
    assert plan['episodes'] and plan['extras'] and report['approved_count']==0
    assert evidence['shortlist']==[] and path.read_bytes()==before
    assert evidence['availability']['segments']['status']=='partial'
    assert all(e['status']=='REVIEW_REQUIRED' and e['human_approval'] is None for e in plan['episodes'])
    assert report['media']['status']=='referenced_only' and not report['models_executed']


def test_media_is_never_found_by_similar_filename(tmp_path):
    (tmp_path/'alike.mp4').write_bytes(b'not the source')
    assert inspect_media({'source':{'sha256':'hash','duration':3}})['status']=='referenced_only'


@pytest.mark.parametrize('kind',['match','mismatch','missing'])
def test_explicit_media_availability(tmp_path,kind):
    path=tmp_path/'media.mp4'
    if kind!='missing':path.write_bytes(b'source')
    evidence={'source':{'sha256':hashlib.sha256(b'source').hexdigest() if kind=='match' else 'wrong','duration':3}}
    assert inspect_media(evidence,path)['status']=={'match':'available_verified','mismatch':'hash_mismatch','missing':'missing'}[kind]
