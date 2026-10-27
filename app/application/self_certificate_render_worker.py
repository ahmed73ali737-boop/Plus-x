"""Fresh renderer child: limits and read allowlist applied before untrusted decoding."""
import json,sys,time
from app.application.self_certificate_storage import CertificateStore
from app.application.self_certificate_rendering import render

def render_payload(data):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        resource.setrlimit(resource.RLIMIT_NPROC,(0,0))
        resource.setrlimit(resource.RLIMIT_FSIZE,(80_020_000,80_020_000))
        store=CertificateStore(data['root'])
        # Read and hash only the two server-authorized opaque assets before
        # untrusted image decoding; no file descriptors remain open.
        background=store.read(data['background'])
        stamp=store.read(data['stamp']) if data['stamp'] else None
        from app.application import self_certificate_fonts as fonts,self_certificate_branding as brand
        fonts.prepare_isolated_resources(data['revision']['font_manifest'])
        brand.prepare_isolated_resources(data['revision']['branding_manifest'])
        from app.application.self_certificate_sandbox import confine
        confine()
        started=time.perf_counter()
        image=render(data['revision'],background,stamp,data['layout'])
        if len(image)>80_000_000:raise MemoryError()
        return json.dumps({'mime':'image/png','render_seconds':time.perf_counter()-started}).encode()+b'\n'+image
    except Exception:
        return b'{"error":"CERTIFICATE_RENDER_FAILED"}\n'

def main():
    try:
        data=json.loads(sys.stdin.buffer.read(200_001))
        sys.stdout.buffer.write(render_payload(data))
    except Exception:
        sys.stdout.buffer.write(b'{"error":"CERTIFICATE_RENDER_FAILED"}\n')
if __name__=='__main__':
    main()
