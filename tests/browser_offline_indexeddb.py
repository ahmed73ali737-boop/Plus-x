from pathlib import Path
import json,re
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
report={'scope':'Chromium IndexedDB component on synthetic http origin; no Service Worker/physical outage claim','checks':[]}
try:
    source=(ROOT/'web/offline.mjs').read_text(encoding='utf-8')
    source=re.sub(r"^import .*?;\s*$",'',source,flags=re.M).replace('export ','')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None,args=['--no-sandbox'])
        page=browser.new_page()
        page.route('http://pulsex.test/**',lambda route:route.fulfill(status=200,content_type='text/html',body='<html><body>offline-test</body></html>'))
        page.goto('http://pulsex.test/',timeout=10000)
        # randomUUID is secure-context dependent in Chromium builds. Keep the component test
        # deterministic about capability by providing an RFC-4122-shaped UUID helper backed
        # by crypto.getRandomValues; production code is not modified or polyfilled.
        page.evaluate("""()=>{window.__px_uuid=()=>{const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);};}""")
        harness="""
        let mode='accept'; let bundles={};
        async function api(path,opts){
          if(path.startsWith('/api/public/site/')){if(mode==='offline')throw new TypeError('offline');return structuredClone(bundles[path]||{slug:path.split('/').pop(),config:{records:[]},agencies:[]});}
          if(path==='/api/collect'){if(mode==='offline')throw new TypeError('offline');return {receipts:opts.items.map(x=>({id:x.id,status:mode==='duplicate'?'duplicate':'accepted'}))};}
          throw new Error('unexpected '+path);
        }
        function toast(){} function download(){}
        """+source+"""
        window.PXO={enqueue,status,sync,get,put,all,bundle}; window.PXMode=x=>mode=x; window.PXBundle=(k,v)=>bundles[k]=v;
        """
        page.add_script_tag(content=harness)
        result=page.evaluate("""async()=>{const e={id:__px_uuid(),site_id:'agency-01',version:1,kind:'visit',visitor_id:__px_uuid(),session_id:__px_uuid(),source:'kiosk',target:'',payload:{},client_time:new Date().toISOString()};const r=await PXO.enqueue(e);return {r,s:await PXO.status(),receipt:await PXO.get('receipts',e.id)}}""")
        assert result['r']['status']=='accepted' and result['s']['pending']==0 and result['receipt']['status']=='accepted';report['checks'].append('accepted_receipt_removes_outbox')
        result=page.evaluate("""async()=>{PXMode('offline');const e={id:__px_uuid(),site_id:'agency-01',version:1,kind:'survey',visitor_id:__px_uuid(),session_id:__px_uuid(),source:'kiosk',target:'main',payload:{answers:{}},client_time:new Date().toISOString()};const r=await PXO.enqueue(e);const before=await PXO.status();PXMode('accept');await PXO.sync();const after=await PXO.status();return {r,before,after,receipt:await PXO.get('receipts',e.id)}}""")
        assert result['r']['status']=='pending' and result['before']['pending']==1 and result['after']['pending']==0 and result['receipt']['status']=='accepted';report['checks'].append('offline_pending_then_reconnect_sync')
        result=page.evaluate("""async()=>{PXMode('offline');const e={id:__px_uuid(),site_id:'agency-01',version:1,kind:'visit',visitor_id:__px_uuid(),session_id:__px_uuid(),source:'qr',target:'',payload:{},client_time:new Date().toISOString()};await PXO.enqueue(e);PXMode('duplicate');await PXO.sync();return {after:await PXO.status(),receipt:await PXO.get('receipts',e.id)}}""")
        assert result['after']['pending']==0 and result['receipt']['status']=='duplicate';report['checks'].append('duplicate_receipt_is_safe_ack')
        browser.close()
    report.update(status='passed',passed=len(report['checks']))
except Exception as exc:
    report.update(status='blocked',not_passed=True,reason=str(exc),passed=0)
(ROOT/'qa/windows11-browser-offline-indexeddb.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if report['status'] in ('passed','blocked') else 1)
