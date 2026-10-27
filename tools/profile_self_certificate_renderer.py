"""Synthetic A/B renderer rehearsal; no configured database or real participant."""
import argparse,hashlib,json,os,statistics,tempfile,time,resource
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from app.application.self_certificate_storage import CertificateStore
from app.application import self_certificate_worker as worker
from app.application import self_certificate_rendering as rendering,self_certificate_fonts as fonts,self_certificate_branding as brand

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=18)
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    if not 1<=args.rounds<=1000 or not 1<=args.workers<=6:raise RuntimeError('PROFILE_ARGUMENT_INVALID')
    with tempfile.TemporaryDirectory(prefix='certificate-render-profile-') as temporary:
        store=CertificateStore(temporary)
        output=BytesIO();Image.new('RGB',(1200,800),'white').save(output,format='PNG')
        raw=output.getvalue()
        asset={**store.put(raw),'id':'synthetic-bg','owner_account_id':'synthetic-owner','kind':'background'}
        revision=dict(id='synthetic-revision',owner_account_id='synthetic-owner',schema_version=2,renderer_version=rendering.VERSION,config=rendering.default_config(1200,800),branding_manifest=brand.system_profile(1200,800))
        revision['font_manifest']=fonts.manifest(revision['config']['font_id'])
        layout=rendering.fit_name('مشارك اختبار الحمل',revision['config'],revision['font_manifest'],revision['branding_manifest'])
        expected=rendering.render(revision,raw,None,layout)
        results=[]
        for mode in ('subprocess','supervisor'):
            print('Profiling executor='+mode,flush=True)
            os.environ['PX_SELF_CERTIFICATE_RENDER_EXECUTOR']=mode
            def one(_):
                start=time.perf_counter()
                actual=worker.render_isolated(store,revision,asset,None,layout)
                assert actual==expected,'RENDER_BYTES_CHANGED'
                return time.perf_counter()-start
            start=time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                durations=list(pool.map(one,range(args.rounds)))
            print('Completed executor='+mode,flush=True)
            results.append(dict(executor=mode,rounds=args.rounds,workers=args.workers,total_seconds=time.perf_counter()-start,
                request_p95_seconds=sorted(durations)[int(.95*(len(durations)-1))],minimum_seconds=min(durations),maximum_seconds=max(durations),
                original_dimensions=[1200,800],bytes_identical=True))
        report={'synthetic_only':True,'results':results,'png_sha256':hashlib.sha256(expected).hexdigest(),
            'parent_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'limits':'Renderer A/B only; not 1000-request acceptance, end-to-end P95 or whole-container peak memory.'}
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
if __name__=='__main__':main()
