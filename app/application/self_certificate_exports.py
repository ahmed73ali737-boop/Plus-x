"""Streaming seven-column CSV/XLSX exports from one database snapshot."""
import csv,io,os,tempfile,zipfile,re
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from sqlalchemy import select,insert,update,delete,or_,and_,func,literal
from sqlalchemy.exc import IntegrityError
from app.self_certificates_db import exports,requests,links,assets,export_snapshot_rows
from app.application.self_certificate_access import require_capability
from app.application.audit_service import new_id
from app.application.self_certificate_clock import utc_now,lease_now
from app.application.self_certificate_worker import later
from app.domain import fail
from app.application.self_certificate_metrics import timed,record

HEADERS=['ترتيب المشارك','الاسم','رقم الهاتف','النموذج','الفعالية','التاريخ','الحالة']
STATUS={'registered':'مسجل','processing':'قيد التوليد','failed':'متعثر','issued':'صادر'}
MAX_SHEET_ROWS=1_048_575
EXPORT_RETENTION=timedelta(days=7)

def export_projection(row):
    return {k:row[k] for k in ('id','status','cutoff','snapshot_taken_at','expected_rows','snapshot_version')}


@timed('export_snapshot')
def request_export(conn,user,body):
    owner=require_capability(conn,user,'requests.export')
    if not isinstance(body,dict) or set(body)-{'format','idempotency_key'} or body.get('format') not in ('csv','xlsx'):
        fail('EXPORT_FORMAT_INVALID')
    key=body.get('idempotency_key')
    if key is not None and (not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key)):
        fail('EXPORT_INPUT_INVALID',422)
    fingerprint=sha256(('snapshot-v2:'+body['format']).encode()).hexdigest()
    def previous():
        row=conn.execute(select(exports).where(exports.c.owner_account_id==owner['id'],exports.c.idempotency_key==key)).mappings().first()
        if row:
            if row['input_hash']!=fingerprint:fail('IDEMPOTENCY_CONFLICT',409)
            return export_projection(row)
    if key is not None:
        existing=previous()
        if existing:return existing
    at=utc_now()
    row=dict(id=new_id(),owner_account_id=owner['id'],format=body['format'],cutoff=at,status='pending',created_at=at,attempts=0,
        snapshot_version=2,snapshot_taken_at=at,expected_rows=None,idempotency_key=key,input_hash=fingerprint)
    try:
        with conn.begin_nested():
            conn.execute(insert(exports).values(**row))
    except IntegrityError:
        if key is not None:
            existing=previous()
            if existing:return existing
        raise
    # One INSERT...SELECT statement is one MVCC view. Capture values as well
    # as membership; never pin an open database transaction across a queue.
    source=select(literal(row['id']),func.row_number().over(order_by=(requests.c.submitted_at_utc,requests.c.id)),
        requests.c.owner_account_id,requests.c.id,requests.c.participant_name_original,requests.c.phone_original,
        links.c.model_name_snapshot,links.c.event_name_snapshot,requests.c.submitted_at_utc,requests.c.status).select_from(
        requests.join(links,and_(links.c.id==requests.c.link_id,links.c.owner_account_id==requests.c.owner_account_id))).where(
        requests.c.owner_account_id==owner['id'])
    conn.execute(insert(export_snapshot_rows).from_select(['export_id','ordinal','owner_account_id','source_request_id',
        'participant_name_original','phone_original','model_name_snapshot','event_name_snapshot','submitted_at_utc','status'],source))
    row['expected_rows']=conn.execute(select(func.count()).select_from(export_snapshot_rows).where(
        export_snapshot_rows.c.export_id==row['id'])).scalar_one()
    conn.execute(update(exports).where(exports.c.id==row['id']).values(expected_rows=row['expected_rows']))
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
    with engine.begin() as conn:
        at=lease_now(conn)
        exhausted=conn.execute(select(exports.c.id).where(exports.c.attempts>=3,or_(
            and_(exports.c.status=='pending',or_(exports.c.lease_until.is_(None),exports.c.lease_until<at)),
            and_(exports.c.status=='processing',exports.c.lease_until<at))).order_by(exports.c.created_at,exports.c.id)
            .limit(100).with_for_update(skip_locked=True)).all()
        for item in exhausted:
            conn.execute(update(exports).where(exports.c.id==item.id).values(status='failed',lease_owner=None,lease_until=None,error_code='EXPORT_FAILED'))
        row=conn.execute(select(exports).where(or_(
            and_(exports.c.status=='pending',or_(exports.c.lease_until.is_(None),exports.c.lease_until<at)),
            and_(exports.c.status=='processing',exports.c.lease_until<at)),exports.c.attempts<3)
            .where(exports.c.snapshot_version==2,exports.c.expected_rows.is_not(None))
            .order_by(exports.c.created_at,exports.c.id).limit(1).with_for_update(skip_locked=True)).mappings().first()
        if not row:return None
        token=new_id()
        changed=conn.execute(update(exports).where(exports.c.id==row['id'],exports.c.status==row['status'],exports.c.attempts==row['attempts'])
            .values(status='processing',lease_owner=token,lease_until=later(600,at),attempts=row['attempts']+1,started_at=at))
        return {**dict(row),'lease_owner':token,'attempts':row['attempts']+1} if changed.rowcount==1 else None

def live_export(conn,job):
    return conn.execute(select(exports.c.id).where(exports.c.id==job['id'],exports.c.status=='processing',
        exports.c.lease_owner==job['lease_owner'],exports.c.lease_until>lease_now(conn)).with_for_update()).first()

@timed('export')
def process_export(engine,store):
    job=claim_export(engine)
    if not job:return False
    path=None
    def heartbeat():
        if engine.dialect.name!='postgresql':return
        with engine.begin() as conn:
            if not live_export(conn,job):fail('EXPORT_LEASE_LOST',409)
            conn.execute(update(exports).where(exports.c.id==job['id']).values(lease_until=later(600,lease_now(conn))))
    try:
        descriptor,temp=tempfile.mkstemp(prefix='export-',suffix='.tmp',dir=store.root);os.close(descriptor);path=Path(temp)
        with engine.connect() as conn:
            if engine.dialect.name=='postgresql':conn=conn.execution_options(isolation_level='REPEATABLE READ')
            with conn.begin():
                query=select(export_snapshot_rows).where(export_snapshot_rows.c.export_id==job['id'],
                    export_snapshot_rows.c.owner_account_id==job['owner_account_id']).order_by(export_snapshot_rows.c.ordinal)
                source=conn.execution_options(stream_results=True).execute(query).mappings().yield_per(500)
                def values():
                    for row in source:
                        yield [row['ordinal'],row['participant_name_original'],row['phone_original'],row['model_name_snapshot'],
                            row['event_name_snapshot'],row['submitted_at_utc'],STATUS[row['status']]]
                if job['format']=='xlsx':count=write_xlsx(path,values(),heartbeat)
                else:
                    count=0
                    with path.open('w',encoding='utf-8-sig',newline='') as stream:
                        writer=csv.writer(stream);writer.writerow(HEADERS)
                        for row in values():
                            writer.writerow([safe_csv(v,i==2) for i,v in enumerate(row)]);count+=1
                            if count%500==0:heartbeat()
        if count!=job['expected_rows']:fail('EXPORT_SNAPSHOT_INVALID',409)
        heartbeat()
        stored=store.put_file(path)
        mime='text/csv' if job['format']=='csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        asset=dict(id=new_id(),owner_account_id=job['owner_account_id'],kind='export',**stored,mime=mime,width=None,height=None,
            source_kind=job['format'],original_size_bytes=stored['size_bytes'],source_metadata={'cutoff':job['cutoff'],'snapshot_version':job['snapshot_version'],'expected_rows':job['expected_rows']},created_at=utc_now())
        with engine.begin() as conn:
            if not live_export(conn,job):return True
            conn.execute(insert(assets).values(**asset))
            conn.execute(update(exports).where(exports.c.id==job['id']).values(status='done',asset_id=asset['id'],row_count=count,
                lease_owner=None,lease_until=None,error_code=None))
    except Exception:
        with engine.begin() as conn:
            if live_export(conn,job):
                retry=job['attempts']<3
                conn.execute(update(exports).where(exports.c.id==job['id']).values(status='pending' if retry else 'failed',
                    lease_owner=None,lease_until=later(5*job['attempts'],lease_now(conn)) if retry else None,error_code='EXPORT_RETRY' if retry else 'EXPORT_FAILED'))
    finally:
        if path:path.unlink(missing_ok=True)
    return True

def expire_exports(engine,store,*,batch_size=100):
    """Expire only completed export artifacts seven days after file creation."""
    if not 1<=batch_size<=1000:raise ValueError('UNSAFE_EXPORT_EXPIRY_BATCH')
    cutoff=(datetime.now(timezone.utc)-EXPORT_RETENTION).isoformat()
    keys=[]
    with engine.begin() as conn:
        rows=conn.execute(select(exports.c.id,exports.c.asset_id,assets.c.storage_key)
            .select_from(exports.join(assets,exports.c.asset_id==assets.c.id))
            .where(exports.c.status=='done',assets.c.kind=='export',assets.c.created_at<=cutoff)
            .order_by(assets.c.created_at,exports.c.id).limit(batch_size).with_for_update(skip_locked=True,of=exports)).all()
        for row in rows:
            changed=conn.execute(update(exports).where(exports.c.id==row.id,exports.c.status=='done',exports.c.asset_id==row.asset_id)
                .values(status='failed',asset_id=None,error_code='EXPORT_EXPIRED',lease_owner=None,lease_until=None))
            if changed.rowcount!=1:continue
            conn.execute(delete(export_snapshot_rows).where(export_snapshot_rows.c.export_id==row.id))
            conn.execute(delete(assets).where(assets.c.id==row.asset_id,assets.c.kind=='export'))
            keys.append(row.storage_key)
    expired_failed=0
    with engine.begin() as conn:
        abandoned=conn.execute(select(exports.c.id).where(exports.c.snapshot_version==2,
            exports.c.status=='failed',exports.c.asset_id.is_(None),exports.c.error_code!='EXPORT_EXPIRED',
            exports.c.created_at<=cutoff).order_by(exports.c.created_at,exports.c.id).limit(batch_size)
            .with_for_update(skip_locked=True)).scalars().all()
        for ident in abandoned:
            conn.execute(update(exports).where(exports.c.id==ident).values(error_code='EXPORT_EXPIRED'))
            conn.execute(delete(export_snapshot_rows).where(export_snapshot_rows.c.export_id==ident))
            expired_failed+=1
    removed=0;errors=0
    for key in keys:
        if store.remove_unreferenced_file(key):removed+=1
        else:errors+=1
    return {'expired':len(keys),'removed_files':removed,'file_errors':errors,'expired_failed_snapshots':expired_failed}

def is_expired(created_at,now=None):
    created=datetime.fromisoformat(created_at)
    if created.tzinfo is None:created=created.replace(tzinfo=timezone.utc)
    return created<=((now or datetime.now(timezone.utc))-EXPORT_RETENTION)
