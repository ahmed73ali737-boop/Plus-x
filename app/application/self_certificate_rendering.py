"""Original-resolution PNG renderer for self-service certificates, separate from legacy."""
from copy import deepcopy
from io import BytesIO
import math,re,unicodedata
from PIL import Image,ImageDraw
from app.domain import fail
from app.application import self_certificate_fonts as fonts
from app.application import self_certificate_branding as branding

VERSION='self-png-portable-v3'
SUPPORTED_VERSIONS=('self-png-portable-v2',VERSION)
ALGORITHM='shrink-then-penultimate-v1'
FIELDS={'name_rect','stamp_rect','font_id','preferred_size','minimum_size','direction','align','vertical_align','color'}

def default_config(width,height,has_stamp=False):
    return dict(name_rect=dict(x=round(width*.15),y=round(height*.35),width=round(width*.7),height=round(height*.18)),
        stamp_rect=dict(x=round(width*.72),y=round(height*.72),width=round(width*.18),height=round(height*.18)) if has_stamp else None,
        font_id='NotoSansArabic-Regular',preferred_size=max(12,round(height*.07)),
        minimum_size=max(6,round(height*.025)),direction='rtl',align='center',vertical_align='middle',color='#152e4d')

def validate_config(config,width,height,has_stamp,brand,saved_fonts=None):
    if not isinstance(config,dict) or set(config)!=FIELDS:
        fail('DESIGN_CONFIG_INVALID')
    if width*height>18_000_000:fail('IMAGE_PIXEL_LIMIT')
    branding.validate_manifest(brand,width,height)
    for key in ('preferred_size','minimum_size'):
        if type(config[key]) is not int or not 1<=config[key]<=1024:
            fail('FONT_SIZE_INVALID')
    if config['minimum_size']<max(1,math.ceil(min(width,height)*.008)) or config['preferred_size']<config['minimum_size']:
        fail('FONT_SIZE_INVALID')
    if config['direction'] not in ('rtl','ltr') or config['align'] not in ('left','center','right') or config['vertical_align'] not in ('top','middle','bottom'):
        fail('TEXT_ALIGNMENT_INVALID')
    if not isinstance(config['color'],str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',config['color']):
        fail('TEXT_COLOR_INVALID')
    branding.validate_reserved_rect(config['name_rect'],brand,width,height)
    if has_stamp:
        branding.validate_reserved_rect(config['stamp_rect'],brand,width,height)
    elif config['stamp_rect'] is not None:fail('STAMP_CONFIG_INVALID')
    saved_fonts=fonts.manifest(config['font_id']) if saved_fonts is None else fonts.validate_manifest(saved_fonts)
    if saved_fonts['primary_id']!=config['font_id']:fail('FONT_MANIFEST_INVALID')
    return deepcopy(config),deepcopy(saved_fonts)

def normalize_name(value,saved_fonts):
    if not isinstance(value,str) or not value or len(value)>250:
        fail('INVALID_NAME')
    if any(unicodedata.category(c) in ('Cc','Cf','Cs') for c in value):
        fail('NAME_CONTROL_CHARACTERS')
    normalized=' '.join(unicodedata.normalize('NFC',value).split())
    if not normalized or len(normalized.split())>5:fail('NAME_WORD_LIMIT')
    if not fonts.supports(normalized,saved_fonts):fail('NAME_GLYPH_UNSUPPORTED')
    return normalized

def measurement(value,config,saved_fonts,size):
    draw=ImageDraw.Draw(Image.new('RGB',(1,1)))
    cursor=0.;bounds=[]
    for font,text in fonts.runs(value,saved_fonts,size,config['direction']):
        box=draw.textbbox((cursor,0),text,font=font,anchor='ls')
        bounds.append(box)
        cursor+=draw.textlength(text,font=font)
    return [min(b[0] for b in bounds),min(b[1] for b in bounds),
        max(b[2] for b in bounds),max(b[3] for b in bounds)]

def fit_name(value,config,saved_fonts,brand,renderer_version=VERSION):
    if renderer_version not in SUPPORTED_VERSIONS:fail('RENDERER_VERSION_UNAVAILABLE',503)
    normalized=normalize_name(value,saved_fonts)
    rect=config['name_rect'];pad=2
    if rect['width']<=2*pad or rect['height']<=2*pad:fail('NAME_CANNOT_FIT')
    def fits(box):
        return box[2]-box[0]<=rect['width']-2*pad and box[3]-box[1]<=rect['height']-2*pad
    printed=normalized;removed=[];chosen=None
    # Bounded, exact descending search avoids assumptions about hinted bbox monotonicity.
    for size in range(config['preferred_size'],config['minimum_size']-1,-1):
        box=measurement(printed,config,saved_fonts,size)
        if fits(box):chosen=(size,box);break
    words=normalized.split()
    while chosen is None and len(words)>2:
        removed.append(words.pop(-2));printed=' '.join(words)
        box=measurement(printed,config,saved_fonts,config['minimum_size'])
        if fits(box):chosen=(config['minimum_size'],box)
    if chosen is None:fail('NAME_CANNOT_FIT')
    size,box=chosen
    remaining_x=rect['width']-2*pad-(box[2]-box[0])
    remaining_y=rect['height']-2*pad-(box[3]-box[1])
    dx={'left':0,'center':remaining_x/2,'right':remaining_x}[config['align']]
    dy={'top':0,'middle':remaining_y/2,'bottom':remaining_y}[config['vertical_align']]
    origin=[rect['x']+pad+dx-box[0],rect['y']+pad+dy-box[1]]
    return dict(normalized_name=normalized,name_printed=printed,removed_words=removed,font_size=size,
        text_bbox=box,text_origin=origin,algorithm=ALGORITHM,renderer_version=renderer_version,
        font_manifest=deepcopy(saved_fonts),branding_manifest=deepcopy(brand))

def render(revision,background,stamp,layout):
    if revision['schema_version']!=2 or revision['renderer_version'] not in SUPPORTED_VERSIONS:
        fail('RENDERER_VERSION_UNAVAILABLE',503)
    with Image.open(BytesIO(background)) as source:
        source.load();image=source.convert('RGBA')
    if image.width*image.height>18_000_000:fail('IMAGE_PIXEL_LIMIT')
    brand=revision['branding_manifest']
    config,saved_fonts=validate_config(revision['config'],*image.size,stamp is not None,brand,revision['font_manifest'])
    if saved_fonts!=revision['font_manifest']:fail('FONT_MANIFEST_INVALID')
    expected=fit_name(layout.get('normalized_name'),config,saved_fonts,brand,renderer_version=revision['renderer_version'])
    if layout!=expected:fail('LAYOUT_SNAPSHOT_INVALID')
    draw=ImageDraw.Draw(image);cursor=layout['text_origin'][0];baseline=layout['text_origin'][1]
    for font,text in fonts.runs(layout['name_printed'],saved_fonts,layout['font_size'],config['direction']):
        draw.text((cursor,baseline),text,font=font,fill=config['color'],anchor='ls')
        cursor+=draw.textlength(text,font=font)
    if stamp is not None:
        with Image.open(BytesIO(stamp)) as seal:
            seal.load()
            rect=config['stamp_rect']
            scale=min(rect['width']/seal.width,rect['height']/seal.height)
            size=(max(1,math.floor(seal.width*scale)),max(1,math.floor(seal.height*scale)))
            if size[0]>rect['width'] or size[1]>rect['height']:fail('STAMP_CANNOT_FIT')
            resized=seal.convert('RGBA').resize(size,Image.Resampling.LANCZOS)
            x=round(rect['x']+(rect['width']-size[0])/2)
            y=round(rect['y']+(rect['height']-size[1])/2)
            if x<rect['x'] or y<rect['y'] or x+size[0]>rect['x']+rect['width'] or y+size[1]>rect['y']+rect['height']:
                fail('STAMP_CANNOT_FIT')
            image.alpha_composite(resized,(x,y))
    image=branding.composite_branding(image,brand)
    output=BytesIO();image.save(output,format='PNG')
    return output.getvalue()

def preview(revision,background,stamp,name):
    layout=fit_name(name,revision['config'],revision['font_manifest'],revision['branding_manifest'],renderer_version=revision['renderer_version'])
    return render(revision,background,stamp,layout),layout
