import hashlib
import json
import zipfile
from ldporto_curator.full_handoff import export_handoff, validate_handoff


def test_supplied_text_media_is_sanitized_with_original_hash(tmp_path):
    evidence={'source':{'sha256':'source-hash','duration':10,'video_id':'test'},'segments':[], 'availability':{}}
    source=tmp_path/'episode.json'
    source.write_text(json.dumps({'audio':{'music_path':r'C:\Users\private\track.wav'},
                                 'hf_token':'hf_abcdefghijklmnopqrstu','text':'Trecho literal.'}),encoding='utf-8')
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    path=export_handoff(evidence,{'episodes':[]},tmp_path/'packet',media_paths={'media/episode.json':source})
    validate_handoff(path)
    with zipfile.ZipFile(path) as archive:
        payload=archive.read('media/episode.json').decode('utf-8')
        assert 'C:\\Users' not in payload and 'private' not in payload and 'hf_' not in payload
        assert 'Trecho literal.' in payload
        metadata=json.loads(archive.read('source_manifest.json'))
        row=next(row for row in metadata['media'] if row['path']=='media/episode.json')
        assert row['original_sha256']==original and row['sanitized_copy'] is True
        assert metadata['redactions']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
