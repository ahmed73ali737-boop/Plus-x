"""Private retrieval and minimal verification; immutable issued rows are never updated."""
import hmac
from fastapi import HTTPException
from sqlalchemy import select
from app.self_certificates_db import certificates,assets,links
from app.application.self_certificate_crypto import token_hash,fingerprint
from app.domain import fail

def certificate_integrity(row,final_asset,thumbnail_asset):
    return fingerprint({'certificate':{k:v for k,v in row.items() if k!='integrity_hash'},
        'final_sha256':final_asset['sha256'],'thumbnail_sha256':thumbnail_asset['sha256']})

def issued_assets(conn,row):
    values=[]
    for ident,kind in ((row['final_asset_id'],'final'),(row['thumbnail_asset_id'],'thumbnail')):
        asset=conn.execute(select(assets).where(assets.c.id==ident,assets.c.owner_account_id==row['owner_account_id'],assets.c.kind==kind)).mappings().first()
        if not asset:fail('FINAL_FILE_UNAVAILABLE',503)
        values.append(dict(asset))
    return values

def by_token(conn,keys,token):
    ident,version=keys.verify('receive',token)
    row=conn.execute(select(certificates).where(certificates.c.id==ident,certificates.c.key_version==version)).mappings().first()
    if not row or not hmac.compare_digest(row['delivery_token_hash'],token_hash(token)):fail('NOT_FOUND',404)
    return dict(row)

def public_certificate(conn,row,store,keys,origin,private=False):
    status='valid'
    try:
        final,thumbnail=issued_assets(conn,row)
        if not hmac.compare_digest(row['integrity_hash'],certificate_integrity(row,final,thumbnail)):status='integrity_error'
        store.verified_path(final);store.verified_path(thumbnail)
    except HTTPException:status='integrity_error'
    link=conn.execute(select(links).where(links.c.id==row['link_id'],links.c.owner_account_id==row['owner_account_id'])).mappings().first()
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
