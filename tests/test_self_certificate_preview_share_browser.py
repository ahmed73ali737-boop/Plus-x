"""Real Chromium geometry and synthetic share boundaries; no external posts are sent."""
from io import BytesIO
from pathlib import Path
import hashlib,json,os,time
import pytest
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from tests.test_self_certificate_browser_improvements import browser_server
from tests.test_self_certificate_http import PASSWORD,A

def evidence(tmp_path,name):
    folder=Path(os.environ.get('PX_CERTIFICATE_TEST_EVIDENCE_DIR') or tmp_path)/'ux-width-share'/name
    folder.mkdir(parents=True,exist_ok=True)
    return folder

def wait_until(check,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Browser state did not settle before deadline')

def geometry(dialog):
    return dialog.locator('.selfcert-viewport').evaluate("""el=>{
      const style=getComputedStyle(el),stage=el.querySelector('.selfcert-stage'),box=stage.getBoundingClientRect();
      return {width:box.width,height:box.height,availableWidth:el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),
       availableHeight:el.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom),
       scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight};
    }""")

@pytest.mark.parametrize('kind,size',[('PNG',(600,900)),('PNG',(1200,800)),('PNG',(800,800)),('JPEG',(600,900)),('JPEG',(1200,800)),('JPEG',(800,800)),('PDF',(600,900)),('PDF',(1200,800)),('PDF',(800,800)),('PNG',(480,720))])
def test_editor_width_fit_scroll_zoom_and_original_geometry(browser_server,tmp_path,kind,size):
    folder=evidence(tmp_path,'editor-'+kind+'-'+str(size[0]));checks=[];errors=[]
    out=BytesIO();Image.new('RGB',size,'white').save(out,format=kind,resolution=150)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':1366,'height':768},locale='ar-YE')
        auth=context.request.post(browser_server+'/api/auth/login',data={'email':'self-a@example.test','password':PASSWORD});assert auth.status==200
        headers={'Origin':browser_server,'X-CSRF':auth.json()['csrf']}
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
        page.goto(browser_server+'/certificates');page.get_by_role('button',name='إضافة نموذج شهادة',exact=True).click()
        dialog=page.get_by_role('dialog');zoom=dialog.get_by_label('تكبير المعاينة',exact=True)
        expect(zoom).to_have_value('width')
        with page.expect_response(lambda r:'/design-options?' in r.url) as options:
            dialog.get_by_label('خلفية PNG أو JPEG أو PDF',exact=True).set_input_files({'name':'fixture.'+kind.lower(),'mimeType':'application/pdf' if kind=='PDF' else 'image/'+kind.lower(),'buffer':out.getvalue()})
        meta=options.value.json();ratio=meta['width']/meta['height']
        save=dialog.get_by_role('button',name='حفظ النموذج',exact=True);expect(save).to_be_enabled(timeout=30000)
        g=wait_until(lambda:(v if abs((v:=geometry(dialog))['width']-v['availableWidth'])<=2 else None))
        assert abs(g['width']/g['height']/ratio-1)<.005
        assert g['scrollWidth']<=g['clientWidth']+2
        checks.append('width-fit preserves ratio and consumes available width')
        if size[0]<size[1]:
            assert g['scrollHeight']>g['clientHeight']
            dialog.locator('.selfcert-viewport').evaluate('el=>el.scrollTop=el.scrollHeight')
            assert save.is_visible();checks.append('portrait scroll stays inside viewport with save visible')
        for width,height in [(1920,900),(1366,768),(1093,600),(910,600),(683,600)]:
            page.set_viewport_size({'width':width,'height':height})
            g=wait_until(lambda:(v if abs((v:=geometry(dialog))['width']-v['availableWidth'])<=2 else None))
            assert g['scrollWidth']<=g['clientWidth']+2
            checks.append('responsive width '+str(width))
        page.set_viewport_size({'width':1366,'height':768})
        zoom.select_option('fit')
        wait_until(lambda:(v if (v:=geometry(dialog))['width']<=v['availableWidth']+2 and v['height']<=v['availableHeight']+2 else None))
        for mode in ('0.5','0.75','1'):
            zoom.select_option(mode)
            wait_until(lambda:abs(geometry(dialog)['width']-meta['width']*float(mode))<=2)
        zoom.select_option('width');wait_until(lambda:abs((v:=geometry(dialog))['width']-v['availableWidth'])<=2)
        checks.append('whole-page and native percentage modes are independent')
        name=dialog.locator('.selfcert-name-box');name.scroll_into_view_if_needed()
        before=float(name.evaluate("el=>parseFloat(el.style.left)"));name.focus();name.press('ArrowRight')
        after=float(name.evaluate("el=>parseFloat(el.style.left)"));assert abs((after-before)*meta['width']/100-1)<.02
        dialog.get_by_role('button',name='تراجع عن تعديل',exact=True).click()
        wait_until(lambda:abs(float(name.evaluate("el=>parseFloat(el.style.left)"))-before)<.001)
        name.scroll_into_view_if_needed();bounds=name.bounding_box();stage_width=geometry(dialog)['width']
        page.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2);page.mouse.down();page.mouse.move(bounds['x']+bounds['width']/2+12,bounds['y']+bounds['height']/2);page.mouse.up()
        moved=float(name.evaluate("el=>parseFloat(el.style.left)"))
        assert abs((moved-before)*meta['width']/100-round(12*meta['width']/stage_width))<=1
        checks.append('pointer and keyboard movement use original pixels after scroll')
        handle=name.get_by_role('button',name='تحجيم مساحة الاسم بالأسهم',exact=True)
        native_width=float(name.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100
        handle.focus();handle.press('ArrowRight')
        assert abs(float(name.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100-native_width-1)<.02
        dialog.get_by_role('button',name='تراجع عن تعديل',exact=True).click()
        wait_until(lambda:abs(float(name.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100-native_width)<.02)
        dialog.get_by_role('button',name='إعادة تعديل',exact=True).click()
        wait_until(lambda:abs(float(name.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100-native_width-1)<.02)
        checks.append('name resize and undo/redo retain native pixel units')
        if kind=='JPEG':
            stamp_data=BytesIO();Image.new('RGBA',(120,60),(20,100,120,180)).save(stamp_data,format='PNG')
            dialog.get_by_label('ختم PNG اختياري',exact=True).set_input_files({'name':'stamp.png','mimeType':'image/png','buffer':stamp_data.getvalue()})
            expect(save).to_be_enabled(timeout=30000)
            stamp=dialog.locator('.selfcert-stamp-box');stamp.scroll_into_view_if_needed();stamp.focus()
            old_x=float(stamp.evaluate("el=>parseFloat(el.style.left)"));stamp.press('Shift+ArrowLeft')
            assert abs((old_x-float(stamp.evaluate("el=>parseFloat(el.style.left)")))*meta['width']/100-10)<.02
            old_width=float(stamp.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100
            stamp.get_by_role('button',name='تحجيم مساحة الختم بالأسهم',exact=True).press('ArrowLeft')
            assert abs(float(stamp.evaluate("el=>parseFloat(el.style.width)"))*meta['width']/100-old_width+1)<.02
            stamp.scroll_into_view_if_needed();box=stamp.bounding_box();old_x=float(stamp.evaluate("el=>parseFloat(el.style.left)"))
            page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(box['x']+box['width']/2-10,box['y']+box['height']/2);page.mouse.up()
            assert abs((old_x-float(stamp.evaluate("el=>parseFloat(el.style.left)")))*meta['width']/100-round(10*meta['width']/geometry(dialog)['width']))<=1
            checks.append('stamp keyboard move/resize and pointer movement keep native pixels')
        dialog.get_by_label('اسم النموذج',exact=True).fill('عرض مصطنع '+kind);dialog.get_by_label('اسم النموذج',exact=True).press('Tab')
        expect(save).to_be_enabled(timeout=30000)
        page.screenshot(path=str(folder/'editor-width.png'))
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(A+'/models')) as saved:
            save.click()
        model=saved.value.json();dialog.wait_for(state='detached')
        asset=context.request.get(browser_server+A+'/assets/'+model['revision']['background_asset_id'])
        assert asset.status==200;asset_hash=hashlib.sha256(asset.body()).hexdigest()
        page.get_by_role('button',name='فتح وتعديل',exact=True).first.click();dialog=page.get_by_role('dialog')
        expect(dialog.get_by_role('button',name='حفظ النموذج',exact=True)).to_be_enabled(timeout=30000)
        expect(dialog.get_by_label('تكبير المعاينة',exact=True)).to_have_value('width')
        again=context.request.get(browser_server+A+'/models/'+model['id']).json()
        assert again['revision']['config']==model['revision']['config']
        assert hashlib.sha256(context.request.get(browser_server+A+'/assets/'+model['revision']['background_asset_id']).body()).hexdigest()==asset_hash
        checks.append('reopening/resizing does not change saved geometry or background bytes')
        assert not errors,errors
        (folder/'result.json').write_text(json.dumps({'status':'passed','kind':kind,'size':size,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
        context.close();browser.close()

def certificate(base,text,status='valid'):
    return {'serial':'SC'+'AB12'*8,'name_printed':'مشارك مصطنع لاختبار الواجهة محمد أحمد علي حسن العمري English Participant','event_name':'فعالية تجريبية',
        'issued_at':'2026-10-28T10:41:00+00:00','status':status,'basis':'self_declaration',
        'verification_url':base+'/certificates/verify/'+'SC'+'AB12'*8,
        'image_url':'/api/public/self-certificates/receive/synthetic-private-capability/image','download_url':'/api/public/self-certificates/receive/synthetic-private-capability/download','share_text':text}

def public_fixture(page,base,value):
    out=BytesIO();Image.new('RGB',(600,900),'white').save(out,format='PNG');raw=out.getvalue()
    page.route('**/api/public/self-certificates/receive/synthetic-private-capability',lambda r:r.fulfill(json=value))
    page.route('**/api/public/self-certificates/verify/*',lambda r:r.fulfill(json={k:v for k,v in value.items() if k not in ('share_text','download_url','image_url')}))
    page.route('**/api/public/self-certificates/receive/synthetic-private-capability/image',lambda r:r.fulfill(body=raw,content_type='image/png'))
    page.route('**/api/public/self-certificates/receive/synthetic-private-capability/download',lambda r:r.fulfill(body=raw,headers={'Content-Type':'image/png','Content-Disposition':'attachment; filename=synthetic-certificate.png','Content-Length':str(len(raw))}))
    page.goto(base+'/certificates/receive/synthetic-private-capability')
    expect(page.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True)).to_be_visible()
    return raw

def test_participant_header_and_share_text_absence_on_all_fallbacks(browser_server,tmp_path):
    folder=evidence(tmp_path,'participant');text='نص ثابت مصطنع للمشاركة 🔖 عربي English';checks=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':390,'height':844},accept_downloads=True,service_workers='block')
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("""window.__shares=[];window.__opens=[];window.__clipboard=0;
        window.open=(url)=>{window.__opens.push(url);return null;};
        Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>{window.__clipboard++;return Promise.resolve();}}});
        Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});
        Object.defineProperty(navigator,'share',{configurable:true,value:data=>{window.__shares.push({text:data.text,files:data.files?.map(f=>({name:f.name,size:f.size,type:f.type})),activation:navigator.userActivation.isActive});return Promise.resolve();}});""")
        value=certificate(browser_server,text);raw=public_fixture(page,browser_server,value)
        assert page.locator('textarea').count()==0 and text not in page.content() and text not in page.locator('main').aria_snapshot()
        assert page.get_by_role('button',name='نسخ نص المشاركة',exact=True).count()==0
        expect(page.get_by_role('heading',name='رمز التحقق الخاص بالشهادة',exact=True)).to_be_visible()
        expect(page.locator('.selfcert-serial')).to_have_text(value['serial'])
        assert page.locator('.selfcert-serial').evaluate("el=>getComputedStyle(el).direction")=='ltr'
        for width in (320,360,390,414,1366):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(folder/'participant.png'),full_page=True)
        checks.append('no share-text DOM or copy control; labeled code fits phone widths')
        # DOM text injection cannot become the source of the outbound share payload.
        page.locator('.selfcert-verification .muted').evaluate("el=>el.textContent='تعديل محلي مصطنع'")
        for target in ('واتساب','إكس','فيسبوك'):
            page.get_by_role('button',name=target,exact=True).click()
        urls=page.evaluate('window.__opens');assert len(urls)==3
        from urllib.parse import urlparse,parse_qs
        assert parse_qs(urlparse(urls[0]).query)['text']==[text+'\n'+value['verification_url']]
        assert parse_qs(urlparse(urls[1]).query)['text']==[text]
        assert parse_qs(urlparse(urls[2]).query)=={'u':[value['verification_url']]}
        checks.append('named links pass fixed full text where supported and public verify only')
        device=page.get_by_role('button',name='مشاركة الصورة عبر الجهاز',exact=True);device.click()
        ready=page.get_by_role('button',name='مشاركة الصورة الجاهزة عبر الجهاز',exact=True);expect(ready).to_be_enabled(timeout=15000)
        assert page.evaluate('window.__shares.length')==0
        ready.click();share=page.evaluate('window.__shares[0]')
        assert share['text']==text+'\n'+value['verification_url'] and share['activation']
        assert share['files'][0]['size']==len(raw) and share['files'][0]['type']=='image/png'
        assert 'synthetic-private-capability' not in share['text']
        checks.append('fresh click shares original file and snapshot text without private capability')
        page.evaluate("Object.defineProperty(navigator,'share',{configurable:true,value:()=>Promise.reject(new DOMException('cancel','AbortError'))})")
        ready.click();expect(page.locator('.notice').last).to_contain_text('أُلغيت المشاركة')
        page.evaluate("Object.defineProperty(navigator,'share',{configurable:true,value:undefined})")
        ready.click();expect(page.locator('.notice').last).to_contain_text('غير متاحة')
        assert text not in page.content() and page.locator('textarea').count()==0
        checks.append('cancel and unavailable paths never reveal or copy text')
        page.evaluate("Object.defineProperty(navigator,'share',{configurable:true,value:()=>Promise.resolve()});Object.defineProperty(navigator,'canShare',{configurable:true,value:data=>!data.text})")
        ready.click();expect(page.locator('.notice').last).to_contain_text('الصورة وحدها')
        download=page.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True)
        assert download.get_attribute('download')=='' and download.get_attribute('href')==value['download_url']
        assert bytes(page.evaluate('url=>fetch(url).then(r=>r.arrayBuffer()).then(b=>Array.from(new Uint8Array(b)))',value['download_url']))==raw
        assert page.evaluate('window.__clipboard')==0
        checks.append('file-only fallback and original download keep clipboard untouched')
        page.get_by_role('link',name='فتح صفحة التحقق',exact=True).click()
        expect(page.locator('.selfcert-serial')).to_have_text(value['serial'])
        assert page.locator('.selfcert-share,.selfcert-result,textarea').count()==0
        assert text not in page.content()
        checks.append('public verification has no private image/download/share controls')
        page.screenshot(path=str(folder/'verification.png'),full_page=True)
        assert not errors,errors
        (folder/'result.json').write_text(json.dumps({'status':'passed','checks':checks,'limitations':['Share destinations mocked; no physical phone acceptance']},ensure_ascii=False,indent=2),encoding='utf-8')
        context.close();browser.close()

def test_long_text_single_preparation_rejection_and_invalid_header(browser_server,tmp_path):
    folder=evidence(tmp_path,'edge-cases');text='نص طويل ثابت 🔖 '*150
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':390,'height':844},service_workers='block');page=context.new_page()
        page.add_init_script("""window.__shares=[];window.__opens=[];window.__downloads=0;window.__pending=[];
        const original=window.fetch;window.fetch=(url,init)=>{if(String(url).includes('/api/public/self-certificates/receive/synthetic-private-capability/download')){window.__downloads++;return new Promise(resolve=>window.__pending.push(()=>resolve(original(url,init))));}return original(url,init);};
        window.open=url=>{window.__opens.push(url);};
        Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});
        Object.defineProperty(navigator,'share',{configurable:true,value:data=>{window.__shares.push(data.text);return Promise.resolve();}});""")
        value=certificate(browser_server,text);public_fixture(page,browser_server,value)
        page.get_by_role('button',name='إكس',exact=True).click()
        expect(page.get_by_role('button',name='واتساب',exact=True)).to_be_disabled()
        assert page.evaluate('window.__downloads')==1 and page.evaluate('window.__opens.length')==0
        page.evaluate('window.__pending.splice(0).forEach(resolve=>resolve())')
        ready=page.get_by_role('button',name='مشاركة الصورة إلى إكس',exact=True);expect(ready).to_be_enabled(timeout=15000)
        ready.click();assert page.evaluate('window.__shares[0]')==text+'\n'+value['verification_url']
        assert page.evaluate('window.__downloads')==1 and text not in page.content()
        page.evaluate("Object.defineProperty(navigator,'share',{configurable:true,value:undefined})")
        ready.click();expect(page.locator('.notice').last).to_contain_text('أطول')
        assert text not in page.content()
        # Fresh page with a browser that rejects PNG never exposes the text.
        page.reload();expect(page.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True)).to_be_visible()
        page.evaluate("Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>false})")
        page.get_by_role('button',name='إنستغرام',exact=True).click()
        page.evaluate('window.__pending.splice(0).forEach(resolve=>resolve())')
        expect(page.locator('.notice').last).to_contain_text('لا يشارك ملفات PNG')
        assert page.locator('textarea').count()==0
        page.reload();expect(page.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True)).to_be_visible()
        page.unroute('**/api/public/self-certificates/receive/synthetic-private-capability/download')
        page.route('**/api/public/self-certificates/receive/synthetic-private-capability/download',lambda r:r.fulfill(status=503,body='synthetic unavailable'))
        device=page.get_by_role('button',name='مشاركة الصورة عبر الجهاز',exact=True);device.click()
        page.evaluate('window.__pending.splice(0).forEach(resolve=>resolve())')
        expect(page.locator('.notice').last).to_contain_text('ملف الشهادة غير متاح')
        expect(device).to_be_enabled()
        assert text not in page.content()
        page.evaluate("""() => { const oldTimeout=window.setTimeout;window.setTimeout=(fn,ms,...args)=>oldTimeout(fn,ms===35000?40:ms,...args);
          window.fetch=(url,init)=>new Promise((resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('timed out','AbortError')),{once:true})); }""")
        device.click();expect(page.locator('.notice').last).to_contain_text('مهلة تجهيز الصورة')
        expect(device).to_be_enabled()
        page.unroute('**/api/public/self-certificates/receive/synthetic-private-capability')
        page.route('**/api/public/self-certificates/receive/synthetic-private-capability',lambda r:r.fulfill(json=certificate(browser_server,text,'integrity_error')))
        page.reload();expect(page.locator('.selfcert-validity')).to_contain_text('تعذر')
        assert page.locator('.selfcert-share,.selfcert-result,textarea').count()==0
        assert page.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True).count()==0
        page.screenshot(path=str(folder/'invalid.png'),full_page=True)
        page.route('**/api/public/self-certificates/verify/missing-code',lambda r:r.fulfill(status=404,json={'detail':'NOT_FOUND'}))
        page.goto(browser_server+'/certificates/verify/missing-code')
        expect(page.get_by_role('button',name='إعادة المحاولة',exact=True)).to_be_visible()
        assert page.locator('.is-valid,.selfcert-share,.selfcert-result,textarea').count()==0
        (folder/'result.json').write_text(json.dumps({'status':'passed','long_text_untruncated':True,'single_preparation':True,'unsupported_png':True,'invalid_has_no_actions':True}),encoding='utf-8')
        context.close();browser.close()
