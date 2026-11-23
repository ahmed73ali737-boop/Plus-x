"""Private retrieval and minimal verification; immutable issued rows are never updated."""
import hmac
from app.application.ports import persistence
from app.application.self_certificate_crypto import token_hash,fingerprint
from app.domain import fail, NotFound, Unavailable, DomainError

def certificate_integrity(row,final_asset,thumbnail_asset):
    return fingerprint({'certificate':{k:v for k,v in row.items() if k!='integrity_hash'},
        'final_sha256':final_asset['sha256'],'thumbnail_sha256':thumbnail_asset['sha256']})

def issued_assets(tx,row):
    values=[]
    for ident,kind in ((row['final_asset_id'],'final'),(row['thumbnail_asset_id'],'thumbnail')):
        asset=persistence.self_certificates.issued_asset(tx,ident,row['owner_account_id'],kind)
        if not asset:fail('FINAL_FILE_UNAVAILABLE', Unavailable)
        values.append(asset)
    return values

def by_token(tx,keys,token):
    ident,version=keys.verify('receive',token)
    row=persistence.self_certificates.certificate_by_id(tx,ident,version)
    if not row or not hmac.compare_digest(row['delivery_token_hash'],token_hash(token)):fail('NOT_FOUND', NotFound)
    return row

def public_certificate(tx,row,store,keys,origin,private=False):
    status='valid'
    try:
        final,thumbnail=issued_assets(tx,row)
        if not hmac.compare_digest(row['integrity_hash'],certificate_integrity(row,final,thumbnail)):status='integrity_error'
        store.verified_path(final);store.verified_path(thumbnail)
    except DomainError:status='integrity_error'
    link=persistence.self_certificates.link_of(tx,row['link_id'],row['owner_account_id'])
    if not link:status='integrity_error'
    result=dict(serial=row['serial'],name_printed=row['name_printed'],event_name=link['event_name_snapshot'] if link else '',
        issued_at=row['issued_at_utc'],status=status,basis='self_declaration',
        verification_url=origin+'/certificates/verify/'+row['serial'])
    if private:
        token=keys.token('receive',row['id'],row['key_version'])
        result.update(image_url='/api/public/self-certificates/receive/'+token+'/image',
            download_url='/api/public/self-certificates/receive/'+token+'/download',
            share_text=link['share_text_snapshot'] if link else '')
    return result


def by_serial(tx,serial):
    row=persistence.self_certificates.certificate_by_serial(tx,serial)
    if not row:fail('NOT_FOUND', NotFound)
    return row
