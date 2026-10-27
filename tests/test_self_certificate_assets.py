"""Real isolated decoders: file boundaries, orientation, alpha, PDF encryption and 2x."""
from io import BytesIO
from hashlib import md5
import struct
import zlib
import pytest
from PIL import Image,ImageCms,PngImagePlugin
from fastapi import HTTPException
from app.application.self_certificate_assets import validate_upload,ingest_asset
from app.application.self_certificate_storage import CertificateStore
from tests.test_self_certificate_data import db
from app.application.self_certificate_sandbox import availability

pytestmark=pytest.mark.skipif(not availability(),reason='Isolated Linux decoder required; dedicated Linux CI covers this module')

def image_bytes(fmt='PNG',size=(240,160),**options):
    im=Image.new('RGBA' if fmt=='PNG' else 'RGB',size,(20,100,160,80) if fmt=='PNG' else '#54789a')
    output=BytesIO();im.save(output,format=fmt,**options);return output.getvalue()

def rc4(key,data):
    state=list(range(256));j=0
    for i in range(256):
        j=(j+state[i]+key[i%len(key)])%256;state[i],state[j]=state[j],state[i]
    result=bytearray();i=j=0
    for value in data:
        i=(i+1)%256;j=(j+state[i])%256;state[i],state[j]=state[j],state[i]
        result.append(value^state[(state[i]+state[j])%256])
    return bytes(result)

def pdf_bytes(pages=1,padding=0,password=None):
    # Minimal synthetic blank PDF, including Standard Security revision 2 fixtures.
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        ('<< /Type /Pages /Count '+str(pages)+' /Kids ['+' '.join(str(i+3)+' 0 R' for i in range(pages))+'] >>').encode()]
    objects += [b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>']*pages
    trailer=b''
    if password is not None:
        pad=bytes.fromhex('28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a')
        padded=lambda value:(value.encode('latin1')+pad)[:32]
        ident=md5(b'certificate-test-only').digest()
        owner=rc4(md5(padded('synthetic-owner')).digest()[:5],padded(password))
        key=md5(padded(password)+owner+struct.pack('<i',-4)+ident).digest()[:5]
        user=rc4(key,pad)
        objects.append(b'<< /Filter /Standard /V 1 /R 2 /O <'+owner.hex().encode()+b'> /U <'+user.hex().encode()+b'> /P -4 >>')
        trailer=b' /Encrypt '+str(len(objects)).encode()+b' 0 R /ID [<'+ident.hex().encode()+b'><'+ident.hex().encode()+b'>]'
    data=bytearray(b'%PDF-1.4\n%'+b'x'*padding+b'\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    start=len(data);data.extend(b'xref\n0 '+str(len(objects)+1).encode()+b'\n0000000000 65535 f \n')
    for offset in offsets[1:]:data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(b'trailer\n<< /Size '+str(len(objects)+1).encode()+b' /Root 1 0 R'+trailer+b' >>\nstartxref\n'+str(start).encode()+b'\n%%EOF')
    return bytes(data)

@pytest.mark.parametrize('fmt',['PNG','JPEG'])
def test_normalized_actual_image_type_and_no_source_metadata(fmt):
    meta=PngImagePlugin.PngInfo();meta.add_text('Private','synthetic-secret')
    data=image_bytes(fmt,pnginfo=meta) if fmt=='PNG' else image_bytes(fmt,comment=b'synthetic-secret')
    output,info=validate_upload(data,'background')
    with Image.open(BytesIO(output)) as im:
        assert im.size==(240,160) and im.format=='PNG'
        assert 'Private' not in im.info and 'comment' not in im.info
    assert b'synthetic-secret' not in output
    assert info['source_kind']==fmt.lower()

def test_jpeg_exif_orientation_is_applied_and_removed():
    exif=Image.Exif();exif[274]=6
    output,info=validate_upload(image_bytes('JPEG',exif=exif),'background')
    with Image.open(BytesIO(output)) as im:
        assert im.size==(160,240) and not im.getexif()
    assert info['width']==160 and info['height']==240

def test_icc_conversion_strips_profile_and_preserves_stamp_alpha():
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    output,_=validate_upload(image_bytes(icc_profile=profile),'stamp')
    with Image.open(BytesIO(output)) as im:
        assert im.mode=='RGBA' and im.getpixel((10,10))[3]==80 and not im.info

@pytest.mark.parametrize('kind,maximum',[('background',3_000_000),('stamp',999_999)])
def test_exact_byte_boundaries_are_enforced_before_decode(kind,maximum):
    data=image_bytes()
    normalized,_=validate_upload(data+b' '*(maximum-len(data)),kind)
    assert normalized.startswith(b'\x89PNG')
    with pytest.raises(HTTPException) as exc:validate_upload(data+b' '*(maximum+1-len(data)),kind)
    assert exc.value.detail==('STAMP_TOO_LARGE' if kind=='stamp' else 'BACKGROUND_TOO_LARGE')

@pytest.mark.parametrize('data,kind,code',[(b'<svg></svg>','background','IMAGE_DECODE_FAILED'),
    (b'not an image','stamp','IMAGE_DECODE_FAILED'),(image_bytes('JPEG'),'stamp','STAMP_PNG_REQUIRED'),
    (image_bytes()[:70],'background','IMAGE_DECODE_FAILED')])
def test_forged_truncated_and_disallowed_files_are_rejected(data,kind,code):
    with pytest.raises(HTTPException) as exc:validate_upload(data,kind)
    assert exc.value.detail==code

def test_animated_png_and_bomb_header_are_rejected():
    stream=BytesIO();im=Image.new('RGBA',(50,50),'red')
    im.save(stream,format='PNG',save_all=True,append_images=[Image.new('RGBA',(50,50),'blue')])
    with pytest.raises(HTTPException) as exc:validate_upload(stream.getvalue(),'background')
    assert exc.value.detail=='ANIMATED_IMAGE_UNSUPPORTED'
    ihdr=struct.pack('>IIBBBBB',6000,3001,8,2,0,0,0)
    chunk=b'IHDR'+ihdr
    bomb=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',len(ihdr))+chunk+struct.pack('>I',zlib.crc32(chunk))+b'\x00\x00\x00\x00IDAT'+struct.pack('>I',zlib.crc32(b'IDAT'))
    with pytest.raises(HTTPException) as exc:validate_upload(bomb,'background')
    assert exc.value.detail=='IMAGE_PIXEL_LIMIT'

def test_single_pdf_renders_once_at_bounded_dpi_and_obeys_background_only_ratio():
    data=pdf_bytes(padding=100_000)
    output,info=validate_upload(data,'background')
    assert len(output)<=2*len(data) and info['source_metadata']['dpi']==300
    assert info['source_metadata']['minimum_dpi']==150
    assert abs(info['width']/info['height']-595/842)<.001
    with pytest.raises(HTTPException) as exc:validate_upload(pdf_bytes(),'background')
    assert exc.value.detail=='PDF_SIZE_QUALITY_CONFLICT'

@pytest.mark.parametrize('password',['','synthetic-password'])
def test_all_encrypted_pdf_including_blank_password_are_rejected(password):
    with pytest.raises(HTTPException) as exc:validate_upload(pdf_bytes(password=password),'background')
    assert exc.value.detail=='PDF_ENCRYPTED'

def test_multiple_page_invalid_pdf_and_pdf_stamp_rejected():
    for data,kind,code in [(pdf_bytes(2),'background','PDF_ONE_PAGE_REQUIRED'),
        (b'%PDF-broken','background','PDF_INVALID'),(pdf_bytes(),'stamp','STAMP_PNG_REQUIRED')]:
        with pytest.raises(HTTPException) as exc:validate_upload(data,kind)
        assert exc.value.detail==code

def test_ingestion_uses_active_account_ownership_and_private_integrity_store(db,tmp_path):
    from sqlalchemy import select
    from app.self_certificates_db import assets
    store=CertificateStore(tmp_path/'private')
    row=ingest_asset(db,{'id':'a'},store,image_bytes(),'background')
    assert row['owner_account_id']=='a' and row['mime']=='image/png'
    assert store.read(row).startswith(b'\x89PNG')
    assert db.execute(select(assets.c.owner_account_id).where(assets.c.id==row['id'])).scalar_one()=='a'

def photographic_pdf():
    output=BytesIO()
    Image.effect_noise((640,480),90).convert('RGB').save(output,format='JPEG',quality=95)
    pixels=output.getvalue()
    content=b'q 640 0 0 480 0 0 cm /Im1 Do Q'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 640 480] /Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream',
        b'<< /Type /XObject /Subtype /Image /Width 640 /Height 480 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+str(len(pixels)).encode()+b' >>\nstream\n'+pixels+b'\nendstream']
    data=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    start=len(data);data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF')
    return bytes(data)

def test_pdf_photographic_background_uses_bounded_jpeg_candidate():
    source=photographic_pdf()
    output,info=validate_upload(source,'background')
    assert info['mime']=='image/jpeg' and output.startswith(b'\xff\xd8')
    assert len(output)<=2*len(source)
    assert info['source_metadata']['dpi'] in (300,240,200,150)
    assert info['source_metadata']['quality'] in (95,90,85)

def test_invalid_icc_profile_is_rejected_instead_of_silently_miscolored():
    with pytest.raises(HTTPException) as exc:validate_upload(image_bytes(icc_profile=b'invalid-icc'),'background')
    assert exc.value.detail=='IMAGE_COLOR_PROFILE_INVALID'
