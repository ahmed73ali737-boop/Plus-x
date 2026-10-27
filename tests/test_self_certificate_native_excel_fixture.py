"""Create harmless native-Excel QA files using the real request/export routes."""
from pathlib import Path
from tests.test_self_certificate_http import system,A,new_link,prepare,submit

def test_prepare_native_excel_files(system,tmp_path):
    app,clients=system
    staff=clients();link,_=new_link(staff)
    for name,phone in [('محمد أحمد العمري','0770123456'),('John Michael Smith','+967771234567'),('=1+1','0771234567')]:
        browser,token,prepared=prepare(app,link)
        assert submit(browser,token,prepared,name=name,phone=phone).status_code==202
    from tests.certificate_test_support import evidence_root
    folder=evidence_root(tmp_path)/'native-excel';folder.mkdir(exist_ok=True)
    for fmt in ('csv','xlsx'):
        job=staff.post(A+'/exports',json={'format':fmt}).json()
        assert app.state.self_certificate_runtime.export()
        result=staff.get(A+'/exports/'+job['id']+'/download')
        assert result.status_code==200
        (folder/('synthetic-certificate-export.'+fmt)).write_bytes(result.content)
