"""Pixels, geometry, font coverage and bounded name fitting from the final engine."""
from copy import deepcopy
from io import BytesIO
import math
import pytest
from fastapi import HTTPException
from PIL import Image,ImageDraw,ImageChops
from sqlalchemy import select,func
from app.application import self_certificate_rendering as rendering
from app.application import self_certificate_fonts as fonts
from app.application import self_certificate_branding as branding
from app.application import self_certificate_repository as repo
from app.self_certificates_db import models,revisions
from tests.test_self_certificate_data import db

def revision(width=1200,height=800,stamp=False,font_id='NotoSansArabic-Regular'):
    brand=branding.system_profile(width,height)
    config={**rendering.default_config(width,height,stamp),'font_id':font_id}
    config,manifest=rendering.validate_config(config,width,height,stamp,brand)
    return dict(schema_version=2,renderer_version=rendering.VERSION,config=config,
        font_manifest=manifest,branding_manifest=brand)

def raw_image(size=(1200,800),color='white'):
    output=BytesIO();Image.new('RGBA',size,color).save(output,format='PNG');return output.getvalue()

@pytest.mark.parametrize('font_id',[c['id'] for c in fonts.choices()])
@pytest.mark.parametrize('name',['مُحَمَّد أحمد علي العمري','John Michael Smith','محمد John أحمد Smith','محمد أحمد علي حسن العمري','John Michael David Robert Smith'])
def test_all_available_real_fonts_shape_measure_and_render_arabic_latin_mixed(font_id,name):
    row=revision(font_id=font_id)
    data,layout=rendering.preview(row,raw_image(),None,name)
    assert layout['normalized_name']==name
    assert layout['name_printed'] and len(layout['removed_words'])<=3
    with Image.open(BytesIO(data)) as image:assert image.size==(1200,800)

@pytest.mark.parametrize('name,code',[('', 'INVALID_NAME'),('أ ب ج د ه و','NAME_WORD_LIMIT'),
    ('محمد\u202eعلي','NAME_CONTROL_CHARACTERS'),('محمد\nعلي','NAME_CONTROL_CHARACTERS'),
    ('محمد 😀','NAME_GLYPH_UNSUPPORTED')])
def test_invalid_names_fail_before_image_generation(name,code):
    row=revision()
    with pytest.raises(HTTPException) as exc:rendering.fit_name(name,row['config'],row['font_manifest'],row['branding_manifest'])
    assert exc.value.detail==code

def test_nfc_whitespace_and_original_name_are_separate():
    row=revision()
    layout=rendering.fit_name('  Jose\u0301   محمد  ',row['config'],row['font_manifest'],row['branding_manifest'])
    assert layout['normalized_name']=='José محمد'
    assert layout['name_printed']=='José محمد'

def test_shrink_first_then_remove_only_penultimate_until_two_words():
    row=revision()
    config=row['config'];config.update(preferred_size=70,minimum_size=40)
    box=rendering.measurement('محمد العمري',config,row['font_manifest'],40)
    config['name_rect']=dict(x=350,y=300,width=math.ceil(box[2]-box[0])+4,height=90)
    layout=rendering.fit_name('محمد أحمد علي حسن العمري',config,row['font_manifest'],row['branding_manifest'])
    assert layout['name_printed']=='محمد العمري' and layout['font_size']==40
    assert layout['removed_words']==['حسن','علي','أحمد']
    assert layout['normalized_name']=='محمد أحمد علي حسن العمري'

def test_largest_fitting_size_before_deletion():
    row=revision();config=row['config'];config.update(preferred_size=100,minimum_size=20)
    box=rendering.measurement('محمد أحمد',config,row['font_manifest'],55)
    config['name_rect']=dict(x=350,y=300,width=math.ceil(box[2]-box[0])+4,height=100)
    layout=rendering.fit_name('محمد أحمد',config,row['font_manifest'],row['branding_manifest'])
    assert layout['removed_words']==[] and layout['font_size']<100
    larger=rendering.measurement('محمد أحمد',config,row['font_manifest'],layout['font_size']+1)
    assert larger[2]-larger[0]>config['name_rect']['width']-4 or larger[3]-larger[1]>96

@pytest.mark.parametrize('name',['طوييييييييييييييييييييييل','محمد العمري'])
def test_impossible_one_or_two_words_are_rejected_without_clipping(name):
    row=revision();row['config']['name_rect']=dict(x=350,y=300,width=6,height=8)
    with pytest.raises(HTTPException) as exc:rendering.fit_name(name,row['config'],row['font_manifest'],row['branding_manifest'])
    assert exc.value.detail=='NAME_CANNOT_FIT'

def test_preview_and_saved_layout_render_have_identical_bytes_and_no_legacy_frame_qr():
    row=revision();background=raw_image()
    preview,layout=rendering.preview(row,background,None,'محمد أحمد علي العمري')
    final=rendering.render(row,background,None,layout)
    assert preview==final
    with Image.open(BytesIO(final)) as image:
        assert image.size==(1200,800)
        difference=ImageChops.difference(image.convert('RGB'),Image.new('RGB',image.size,'white'))
        draw=ImageDraw.Draw(difference)
        for rect in (row['config']['name_rect'],row['branding_manifest']['card_rect']):
            draw.rectangle((rect['x'],rect['y'],rect['x']+rect['width']-1,rect['y']+rect['height']-1),fill='black')
        assert difference.getbbox() is None
    tampered=deepcopy(layout);tampered['text_origin'][0]=0
    with pytest.raises(HTTPException):rendering.render(row,background,None,tampered)

def test_stamp_alpha_and_ratio_and_original_dimensions():
    row=revision(stamp=True)
    stamp=raw_image((40,80),(255,0,0,128))
    data,layout=rendering.preview(row,raw_image(),stamp,'John Smith')
    with Image.open(BytesIO(data)) as image:
        rect=row['config']['stamp_rect']
        crop=image.crop((rect['x'],rect['y'],rect['x']+rect['width'],rect['y']+rect['height'])).convert('RGB')
        difference=ImageChops.difference(crop,Image.new('RGB',crop.size,'white'))
        box=difference.getbbox()
        assert abs((box[2]-box[0])/(box[3]-box[1])-.5)<.01
        center=image.getpixel((round(rect['x']+rect['width']/2),round(rect['y']+rect['height']/2)))
        assert center[0]==255 and 120<=center[1]<=130

def test_overlap_or_forged_brand_rejected_before_model_or_revision_insert(db):
    config=rendering.default_config(800,600)
    config['name_rect']=deepcopy(branding.system_profile(800,600)['card_rect'])
    for bad in (config,{**rendering.default_config(800,600),'branding_manifest':{'enabled':False}}):
        with pytest.raises(HTTPException):repo.save_model(db,{'id':'a'},name='bad',
            background_asset_id='bg',stamp_asset_id=None,config=bad)
    assert db.execute(select(func.count()).select_from(models)).scalar_one()==0
    assert db.execute(select(func.count()).select_from(revisions)).scalar_one()==0

def test_font_manifest_is_server_derived_and_unsupported_kufi_is_not_silently_substituted():
    assert len(fonts.choices())==8
    with pytest.raises(HTTPException) as exc:fonts.manifest('NotoKufiArabic-Regular')
    assert exc.value.detail=='FONT_SHAPING_UNSUPPORTED'
    with pytest.raises(HTTPException):fonts.validate_manifest({'primary_id':'NotoSansArabic-Regular'})
