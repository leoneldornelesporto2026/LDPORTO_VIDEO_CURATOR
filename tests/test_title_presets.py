import json
from PIL import Image
import pytest
from ldporto_curator.title_presets import create_episode_title_card


@pytest.mark.parametrize('preview',[True,False])
def test_long_opening_title_is_measured_inside_card(preview,tmp_path):
    text='Esta é uma demonstração sintética local do Curator. O primeiro quadro mostra um painel azul com'
    path=create_episode_title_card({'title_text':text},tmp_path,{},preview)
    metadata=json.loads((tmp_path/'TITLE_LAYOUT.json').read_text(encoding='utf-8'))
    assert ' '.join(metadata['lines'])==text
    left,top,right,bottom=metadata['card_bounds']
    assert len(metadata['lines'])<=4
    for x1,y1,x2,y2 in metadata['text_bounds']:
        assert left<=x1<x2<=right and top<=y1<y2<=bottom
    with Image.open(path) as image:
        assert image.getpixel((0,0))[3]==0
    assert metadata['font_size'] >= (20 if preview else 40)


def test_title_toggle_and_overlong_text_are_explicit(tmp_path):
    assert create_episode_title_card({'title_enabled':False,'title_text':'Título'},tmp_path,{},True) is None
    with pytest.raises(ValueError,match='longo'):
        create_episode_title_card({'title_text':'muito '*100},tmp_path,{},True)
