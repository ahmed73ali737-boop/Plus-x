"""Original-resolution PNG renderer for self-service certificates, separate from legacy."""
from copy import deepcopy
from io import BytesIO
from PIL import Image,ImageDraw
from app.domain import certificate_layout as layout_rules
from app.application import self_certificate_fonts as fonts
from app.application import self_certificate_branding as branding

VERSION='self-png-portable-v3'
SUPPORTED_VERSIONS=('self-png-portable-v2',VERSION)
ALGORITHM=layout_rules.ALGORITHM
FIELDS=layout_rules.DESIGN_FIELDS

def default_config(width,height,has_stamp=False):
    return dict(name_rect=dict(x=round(width*.15),y=round(height*.35),width=round(width*.7),height=round(height*.18)),
        stamp_rect=dict(x=round(width*.72),y=round(height*.72),width=round(width*.18),height=round(height*.18)) if has_stamp else None,
        font_id='NotoSansArabic-Regular',preferred_size=max(12,round(height*.07)),
        minimum_size=max(6,round(height*.025)),direction='rtl',align='center',vertical_align='middle',color='#152e4d')

def validate_config(config,width,height,has_stamp,brand,saved_fonts=None):
    layout_rules.require_design_shape(config)
    layout_rules.require_pixel_budget(width,height)
    branding.validate_manifest(brand,width,height)
    layout_rules.require_typography(config,width,height)
    branding.validate_reserved_rect(config['name_rect'],brand,width,height)
    if has_stamp:
        branding.validate_reserved_rect(config['stamp_rect'],brand,width,height)
    layout_rules.require_stamp_matches(has_stamp,config['stamp_rect'])
    saved_fonts=fonts.manifest(config['font_id']) if saved_fonts is None else fonts.validate_manifest(saved_fonts)
    layout_rules.require_font_matches(saved_fonts['primary_id'],config['font_id'])
    return deepcopy(config),deepcopy(saved_fonts)

def normalize_name(value,saved_fonts):
    return layout_rules.normalize_name(value,lambda normalized:fonts.supports(normalized,saved_fonts))

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
    layout_rules.require_supported_renderer(renderer_version,SUPPORTED_VERSIONS)
    normalized=normalize_name(value,saved_fonts)
    fitted=layout_rules.fit_name(normalized,config['name_rect'],config,lambda printed,size:measurement(printed,config,saved_fonts,size))
    return dict(normalized_name=normalized,name_printed=fitted['name_printed'],removed_words=fitted['removed_words'],
        font_size=fitted['font_size'],text_bbox=fitted['text_bbox'],text_origin=fitted['text_origin'],algorithm=ALGORITHM,
        renderer_version=renderer_version,font_manifest=deepcopy(saved_fonts),branding_manifest=deepcopy(brand))

def render(revision,background,stamp,layout):
    layout_rules.require_renderable_revision(revision['schema_version'],revision['renderer_version'],SUPPORTED_VERSIONS)
    with Image.open(BytesIO(background)) as source:
        source.load();image=source.convert('RGBA')
    layout_rules.require_pixel_budget(image.width,image.height)
    brand=revision['branding_manifest']
    config,saved_fonts=validate_config(revision['config'],*image.size,stamp is not None,brand,revision['font_manifest'])
    layout_rules.require_font_manifest_unchanged(saved_fonts,revision['font_manifest'])
    expected=fit_name(layout.get('normalized_name'),config,saved_fonts,brand,renderer_version=revision['renderer_version'])
    layout_rules.require_layout_snapshot(layout,expected)
    draw=ImageDraw.Draw(image);cursor=layout['text_origin'][0];baseline=layout['text_origin'][1]
    for font,text in fonts.runs(layout['name_printed'],saved_fonts,layout['font_size'],config['direction']):
        draw.text((cursor,baseline),text,font=font,fill=config['color'],anchor='ls')
        cursor+=draw.textlength(text,font=font)
    if stamp is not None:
        with Image.open(BytesIO(stamp)) as seal:
            seal.load()
            size,origin=layout_rules.stamp_placement(config['stamp_rect'],seal.width,seal.height)
            resized=seal.convert('RGBA').resize(size,Image.Resampling.LANCZOS)
            image.alpha_composite(resized,origin)
    image=branding.composite_branding(image,brand)
    output=BytesIO();image.save(output,format='PNG')
    return output.getvalue()

def preview(revision,background,stamp,name):
    layout=fit_name(name,revision['config'],revision['font_manifest'],revision['branding_manifest'],renderer_version=revision['renderer_version'])
    return render(revision,background,stamp,layout),layout
