"""Streaming seven-column CSV/XLSX exports from one database snapshot."""
import csv,os,tempfile,zipfile,re
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from app.application.ports import persistence
from app.application.self_certificate_access import require_capability
from app.application.audit_service import new_id
from app.application.self_certificate_clock import utc_now,lease_now
from app.application.self_certificate_worker import later
from app.domain import Conflict, Gone, NotFound, fail
from app.application.self_certificate_metrics import timed,record

HEADERS=['ترتيب المشارك','الاسم','رقم الهاتف','النموذج','الفعالية','التاريخ','الحالة']
STATUS={'registered':'مسجل','processing':'قيد التوليد','failed':'متعثر','issued':'صادر'}
MAX_SHEET_ROWS=1_048_575
EXPORT_RETENTION=timedelta(days=7)

def export_projection(row):
    return {k:row[k] for k in ('id','status','cutoff','snapshot_taken_at','expected_rows','snapshot_version')}


@timed('export_snapshot')
def request_export(tx,user,body):
    owner=require_capability(tx,user,'requests.export')
    if not isinstance(body,dict) or set(body)-{'format','idempotency_key'} or body.get('format') not in ('csv','xlsx'):
        fail('EXPORT_FORMAT_INVALID')
    key=body.get('idempotency_key')
    if key is not None and (not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key)):
        fail('EXPORT_INPUT_INVALID')
    fingerprint=sha256(('snapshot-v2:'+body['format']).encode()).hexdigest()
    store=persistence.self_certificates
    def previous():
        row=store.export_by_key(tx,owner['id'],key)
        if row:
            if row['input_hash']!=fingerprint:fail('IDEMPOTENCY_CONFLICT', Conflict)
            return export_projection(row)
    if key is not None:
        existing=previous()
        if existing:return existing
    at=utc_now()
    row=dict(id=new_id(),owner_account_id=owner['id'],format=body['format'],cutoff=at,status='pending',created_at=at,attempts=0,
        snapshot_version=2,snapshot_taken_at=at,expected_rows=None,idempotency_key=key,input_hash=fingerprint)
    if not store.add_export_if_absent(tx,row):
        if key is not None:
            existing=previous()
            if existing:return existing
        raise RuntimeError('EXPORT_INSERT_CONFLICT')
    # Capture values as well as membership; never pin an open database
    # transaction across a queue.
    row['expected_rows']=store.snapshot_export(tx,row['id'],owner['id'])
    record('export_rows',amount=row['expected_rows'])
    return export_projection(row)


def safe_csv(value,phone=False):
    value=str(value)
    if phone or value.lstrip().startswith(('=','+','-','@','\t','\r')):return "'"+value
    return value

def xml_text(value):
    return escape(''.join(c for c in str(value) if c in '\t\n\r' or ord(c)>=32))

def write_xlsx(path,rows,heartbeat):
    sheet=0;row_number=0;total=0;entry=None;names=[]
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
        def start():
            nonlocal sheet,row_number,entry
            sheet+=1;row_number=0;names.append('sheet'+str(sheet)+'.xml')
            entry=archive.open('xl/worksheets/'+names[-1],'w',force_zip64=True)
            entry.write(b'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0" rightToLeft="1"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="1" width="12" customWidth="1"/><col min="2" max="2" width="38" customWidth="1"/><col min="3" max="3" width="24" customWidth="1"/><col min="4" max="5" width="34" customWidth="1"/><col min="6" max="6" width="32" customWidth="1"/><col min="7" max="7" width="20" customWidth="1"/></cols><sheetData>')
        def record(values):
            nonlocal row_number
            row_number+=1
            content='<row r="'+str(row_number)+'">'
            for i,value in enumerate(values):
                content+='<c r="'+chr(65+i)+str(row_number)+'" t="inlineStr"><is><t xml:space="preserve">'+xml_text(value)+'</t></is></c>'
            entry.write((content+'</row>').encode())
        start();record(HEADERS)
        for values in rows:
            if row_number>MAX_SHEET_ROWS:
                entry.write(b'</sheetData></worksheet>');entry.close();start();record(HEADERS)
            record(values);total+=1
            if total%500==0:heartbeat()
        entry.write(b'</sheetData></worksheet>');entry.close()
        namespace='http://schemas.openxmlformats.org/'
        archive.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="'+namespace+'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join('<Override PartName="/xl/worksheets/'+name+'" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for name in names)+'</Types>')
        archive.writestr('_rels/.rels','<Relationships xmlns="'+namespace+'package/2006/relationships"><Relationship Id="rId1" Type="'+namespace+'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml','<workbook xmlns="'+namespace+'spreadsheetml/2006/main" xmlns:r="'+namespace+'officeDocument/2006/relationships"><sheets>'+''.join('<sheet name="طلبات '+str(i)+'" sheetId="'+str(i)+'" r:id="rId'+str(i)+'"/>' for i in range(1,sheet+1))+'</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="'+namespace+'package/2006/relationships">'+''.join('<Relationship Id="rId'+str(i)+'" Type="'+namespace+'officeDocument/2006/relationships/worksheet" Target="worksheets/'+name+'"/>' for i,name in enumerate(names,1))+'</Relationships>')
    return total

def claim_export(engine):
    store=persistence.self_certificates
    with persistence.transactions.write(engine) as tx:
        at=lease_now(tx)
        store.fail_exhausted_exports(tx,at)
        row=store.next_export(tx,at)
        if not row:return None
        token=new_id()
        if not store.lease_export(tx,row,token,later(600,at),at):return None
        return {**row,'lease_owner':token,'attempts':row['attempts']+1}

def live_export(tx,job):
    return persistence.self_certificates.live_export(tx,job,lease_now(tx))

def _snapshot_values(source):
    for row in source:
        yield [row['ordinal'],row['participant_name_original'],row['phone_original'],row['model_name_snapshot'],
            row['event_name_snapshot'],row['submitted_at_utc'],STATUS[row['status']]]

def _write_csv(path,rows,heartbeat):
    count=0
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(HEADERS)
        for row in rows:
            writer.writerow([safe_csv(v,i==2) for i,v in enumerate(row)]);count+=1
            if count%500==0:heartbeat()
    return count

@timed('export')
def process_export(engine,store):
    job=claim_export(engine)
    if not job:return False
    rows_store=persistence.self_certificates
    transactions=persistence.transactions
    path=None
    def heartbeat():
        if not rows_store.supports_lease_heartbeat(engine):return
        with transactions.write(engine) as tx:
            if not live_export(tx,job):fail('EXPORT_LEASE_LOST', Conflict)
            rows_store.update_export(tx,job['id'],dict(lease_until=later(600,lease_now(tx))))
    try:
        descriptor,temp=tempfile.mkstemp(prefix='export-',suffix='.tmp',dir=store.root);os.close(descriptor);path=Path(temp)
        with rows_store.snapshot_rows(engine,job) as source:
            if job['format']=='xlsx':count=write_xlsx(path,_snapshot_values(source),heartbeat)
            else:count=_write_csv(path,_snapshot_values(source),heartbeat)
        if count!=job['expected_rows']:fail('EXPORT_SNAPSHOT_INVALID', Conflict)
        heartbeat()
        stored=store.put_file(path)
        mime='text/csv' if job['format']=='csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        asset=dict(id=new_id(),owner_account_id=job['owner_account_id'],kind='export',**stored,mime=mime,width=None,height=None,
            source_kind=job['format'],original_size_bytes=stored['size_bytes'],source_metadata={'cutoff':job['cutoff'],'snapshot_version':job['snapshot_version'],'expected_rows':job['expected_rows']},created_at=utc_now())
        with transactions.write(engine) as tx:
            if not live_export(tx,job):return True
            rows_store.add_asset(tx,asset)
            rows_store.update_export(tx,job['id'],dict(status='done',asset_id=asset['id'],row_count=count,
                lease_owner=None,lease_until=None,error_code=None))
    except Exception:
        with transactions.write(engine) as tx:
            if live_export(tx,job):
                retry=job['attempts']<3
                rows_store.update_export(tx,job['id'],dict(status='pending' if retry else 'failed',
                    lease_owner=None,lease_until=later(5*job['attempts'],lease_now(tx)) if retry else None,error_code='EXPORT_RETRY' if retry else 'EXPORT_FAILED'))
    finally:
        if path:path.unlink(missing_ok=True)
    return True

def expire_exports(engine,store,*,batch_size=100):
    """Expire only completed export artifacts seven days after file creation."""
    if not 1<=batch_size<=1000:raise ValueError('UNSAFE_EXPORT_EXPIRY_BATCH')
    cutoff=(datetime.now(timezone.utc)-EXPORT_RETENTION).isoformat()
    rows_store=persistence.self_certificates
    keys=[]
    with persistence.transactions.write(engine) as tx:
        for row in rows_store.expirable_exports(tx,cutoff,batch_size):
            if rows_store.expire_export(tx,row['id'],row['asset_id']):
                keys.append(row['storage_key'])
    with persistence.transactions.write(engine) as tx:
        expired_failed=rows_store.expire_abandoned_exports(tx,cutoff,batch_size)
    removed=0;errors=0
    for key in keys:
        if store.remove_unreferenced_file(key):removed+=1
        else:errors+=1
    return {'expired':len(keys),'removed_files':removed,'file_errors':errors,'expired_failed_snapshots':expired_failed}

def is_expired(created_at,now=None):
    created=datetime.fromisoformat(created_at)
    if created.tzinfo is None:created=created.replace(tzinfo=timezone.utc)
    return created<=((now or datetime.now(timezone.utc))-EXPORT_RETENTION)


def owned_exports(tx,owner_id,offset,limit):
    result=[]
    for value in persistence.self_certificates.exports_page(tx,owner_id,offset,limit):
        value['expires_at']=(datetime.fromisoformat(value['file_created_at'])+EXPORT_RETENTION).isoformat() if value['file_created_at'] else None
        result.append(value)
    return result

def downloadable_export(tx,user,ident):
    """The export row and its file asset, when the owner may download it now."""
    from app.application import self_certificate_repository as repo

    row=persistence.self_certificates.export(tx,user['id'],ident)
    if not row:fail('NOT_FOUND', NotFound)
    if row['error_code']=='EXPORT_EXPIRED':fail('EXPORT_EXPIRED', Gone)
    if row['status']!='done':fail('EXPORT_NOT_READY', Conflict)
    asset=repo.owned_asset(tx,user,row['asset_id'],'export')
    if is_expired(asset['created_at']):fail('EXPORT_EXPIRED', Gone)
    return row,asset
