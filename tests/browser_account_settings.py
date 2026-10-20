"""Native HTTP browser journey: preferences, admin delivery and recipient inbox."""
import json, os, socket, tempfile, threading, time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright
from app.server import create_app


def run():
    temporary=tempfile.TemporaryDirectory(prefix='eventna-account-browser-')
    # HTTP requests run concurrently; a file DB gives them separate connections.
    app=create_app('sqlite:///'+(Path(temporary.name)/'account.sqlite').as_posix(),origin='http://127.0.0.1:4387',seed_demo=True)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=4387,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1',4387),timeout=.1):break
        except OSError:time.sleep(.05)
    evidence=Path('artifacts/account-settings');evidence.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or None,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:4387/start')
            page.get_by_role('button',name='المظهر والإشعارات',exact=True).click()
            page.get_by_label('المظهر',exact=True).select_option('dark')
            page.get_by_label('حجم النص',exact=True).select_option('large')
            page.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
            assert page.locator('html').get_attribute('data-appearance')=='dark'
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(evidence/'mobile-settings.png'))
            page.reload();assert page.locator('html').get_attribute('data-appearance')=='dark'
            admin=next(x for x in app.state.seed_credentials if x['email']=='admin@pulsex.test')
            response=context.request.post('http://127.0.0.1:4387/api/auth/login',data={'email':admin['email'],'password':admin['password']})
            assert response.status==200
            page.set_viewport_size({'width':1440,'height':1000})
            page.goto('http://127.0.0.1:4387/admin')
            page.get_by_role('button',name='الإعدادات والإشعارات',exact=True).click()
            page.get_by_label('بريد المستلم',exact=True).fill(admin['email'])
            page.get_by_label('العنوان',exact=True).fill('رسالة الاختبار')
            page.get_by_label('الرسالة',exact=True).fill('تم إرسال هذه الرسالة من لوحة الإدارة')
            page.get_by_role('button',name='إرسال إلى صندوق الحساب').click()
            page.get_by_text('وصلت الرسالة إلى صندوق الحساب.',exact=True).wait_for()
            page.get_by_role('heading',name='رسالة الاختبار').wait_for()
            page.get_by_role('button',name='تحديد كمقروء',exact=True).click()
            page.get_by_role('button',name='تحديد كمقروء',exact=True).wait_for(state='detached')
            page.screenshot(path=str(evidence/'admin-inbox.png'),full_page=True)
            assert not errors, errors
            (evidence/'browser-result.json').write_text(json.dumps({'status':'passed','http':'native uvicorn + SQLite','checks':['guest theme persistence','mobile overflow 390px','login without OTP','admin send','inbox read receipt','no JS page errors']},indent=2))
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
        temporary.cleanup()

if __name__=='__main__':run()
