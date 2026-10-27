"""Isolated image/PDF decoder. No URL, shell, document script or form actions."""
from io import BytesIO
import json
import math
import sys
import warnings
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

MAX_PIXELS = 18_000_000
MAX_BACKGROUND_BYTES = 3_000_000
MAX_STAMP_BYTES = 999_999
DPIS = (300, 240, 200, 150)
JPEG_QUALITIES = (95, 90, 85)

class AssetError(Exception):
    pass

def checked_size(width, height):
    if min(width, height) <= 0 or width * height > MAX_PIXELS:
        raise AssetError('IMAGE_PIXEL_LIMIT')

def encode(image, fmt, **options):
    stream=BytesIO()
    # No source metadata is forwarded to the normalized result.
    clean=Image.new(image.mode,image.size)
    clean.paste(image)
    clean.save(stream,format=fmt,**options)
    return stream.getvalue()

def raster(data, kind):
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in ('PNG','JPEG') or (kind=='stamp' and probe.format!='PNG'):
                raise AssetError('STAMP_PNG_REQUIRED' if kind=='stamp' else 'BACKGROUND_TYPE_INVALID')
            fmt=probe.format
            checked_size(*probe.size)
            if getattr(probe,'n_frames',1)!=1:
                raise AssetError('ANIMATED_IMAGE_UNSUPPORTED')
            probe.verify()
        with Image.open(BytesIO(data)) as source:
            source.load()
            original_size=source.size
            image=ImageOps.exif_transpose(source)
            alpha=image.convert('RGBA').getchannel('A') if 'A' in image.getbands() or 'transparency' in image.info else None
            profile=image.info.get('icc_profile')
            if profile:
                try:
                    image=ImageCms.profileToProfile(image,ImageCms.ImageCmsProfile(BytesIO(profile)),
                        ImageCms.createProfile('sRGB'),outputMode='RGB')
                except (OSError,ValueError,ImageCms.PyCMSError):
                    raise AssetError('IMAGE_COLOR_PROFILE_INVALID')
            else:
                image=image.convert('RGB')
            if alpha is not None:
                image.putalpha(alpha)
            checked_size(*image.size)
            result=encode(image,'PNG')
            return result,dict(mime='image/png',width=image.width,height=image.height,source_kind=fmt.lower(),
                source_metadata=dict(original_width=original_size[0],original_height=original_size[1],
                    orientation_applied=True,color_space='sRGB',metadata_stripped=True))
    except (Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise AssetError('IMAGE_PIXEL_LIMIT')
    except (UnidentifiedImageError,OSError,SyntaxError,ValueError):
        raise AssetError('IMAGE_DECODE_FAILED')

def pdf(data):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    try:
        document=pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise AssetError('PDF_ENCRYPTED' if error.err_code==raw.FPDF_ERR_PASSWORD else 'PDF_INVALID')
    with document:
        if raw.FPDF_GetSecurityHandlerRevision(document.raw)!=-1:
            raise AssetError('PDF_ENCRYPTED')
        if len(document)!=1:
            raise AssetError('PDF_ONE_PAGE_REQUIRED')
        page=document[0]
        try:
            width,height=page.get_size()
            if not all(math.isfinite(v) and v>0 for v in (width,height)):
                raise AssetError('PDF_PAGE_INVALID')
            for dpi in DPIS:
                out_width,out_height=math.ceil(width*dpi/72),math.ceil(height*dpi/72)
                if out_width*out_height>MAX_PIXELS:
                    continue
                bitmap=page.render(scale=dpi/72)
                try:
                    image=bitmap.to_pil().convert('RGB')
                    checked_size(*image.size)
                    for fmt,quality in (('PNG',None),*(('JPEG',q) for q in JPEG_QUALITIES)):
                        options={} if quality is None else dict(quality=quality,subsampling=0)
                        result=encode(image,fmt,**options)
                        if len(result)<=2*len(data):
                            return result,dict(mime='image/png' if fmt=='PNG' else 'image/jpeg',
                                width=image.width,height=image.height,source_kind='pdf',
                                source_metadata=dict(dpi=dpi,format=fmt,quality=quality,
                                    pdf_points=[width,height],page_count=1,minimum_dpi=150,
                                    minimum_jpeg_quality=85,color_space='sRGB',metadata_stripped=True,
                                    converter='pypdfium2-5.14.0',background_ratio_limit=2))
                finally:
                    bitmap.close()
        finally:
            page.close()
    raise AssetError('PDF_SIZE_QUALITY_CONFLICT')

def convert(data,kind):
    if kind not in ('background','stamp'):
        raise AssetError('ASSET_KIND_INVALID')
    if not data:
        raise AssetError('FILE_EMPTY')
    if len(data)>(MAX_STAMP_BYTES if kind=='stamp' else MAX_BACKGROUND_BYTES):
        raise AssetError('STAMP_TOO_LARGE' if kind=='stamp' else 'BACKGROUND_TOO_LARGE')
    if data.startswith(b'%PDF-'):
        if kind=='stamp':
            raise AssetError('STAMP_PNG_REQUIRED')
        return pdf(data)
    return raster(data,kind)

def main():
    try:
        # The supported runtime is Linux Docker. Never silently remove resource limits.
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(12,12))
        resource.setrlimit(resource.RLIMIT_FSIZE,(80_020_000,80_020_000))
        from app.application.self_certificate_sandbox import confine
        confine()
        Image.MAX_IMAGE_PIXELS=MAX_PIXELS
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        data=sys.stdin.buffer.read(MAX_BACKGROUND_BYTES+1)
        output,info=convert(data,sys.argv[1])
        sys.stdout.buffer.write(json.dumps(info,separators=(',',':')).encode()+b'\n'+output)
    except ImportError:
        sys.stdout.buffer.write(b'{"error":"ASSET_PROCESS_ISOLATION_UNAVAILABLE"}\n')
    except AssetError as error:
        sys.stdout.buffer.write(json.dumps({'error':str(error)}).encode()+b'\n')
    except (MemoryError,OverflowError):
        sys.stdout.buffer.write(b'{"error":"ASSET_RESOURCE_LIMIT"}\n')
    except Exception:
        # Parser details and source bytes must never reach clients or logs.
        sys.stdout.buffer.write(b'{"error":"ASSET_PROCESS_FAILED"}\n')

if __name__=='__main__':
    main()
