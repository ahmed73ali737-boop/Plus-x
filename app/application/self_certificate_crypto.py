"""Persistent, versioned HMAC capabilities. Never log or return signing keys."""
import base64,hashlib,hmac,json,os,re,secrets,time
from pathlib import Path
from app.domain import fail
from app.application.self_certificate_keys import bounded_json,VersionedKeys

PART=re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
REMEMBER_SECONDS=365*24*60*60

class Keyring:
    def __init__(self,path,allow_create=False):
        self.path=Path(path)
        if not self.path.exists() and allow_create:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            raw=json.dumps({'current':'v1','keys':{'v1':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}}).encode()
            temporary=self.path.with_name(self.path.name+'.'+secrets.token_hex(8)+'.tmp')
            descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                try:os.link(temporary,self.path)
                except FileExistsError:pass
            finally:temporary.unlink(missing_ok=True)
        try:
            data=bounded_json(self.path,4*1024*1024)
            self.current=data['current']
            if not isinstance(self.current,str) or not PART.fullmatch(self.current):raise ValueError()
            self.keys=VersionedKeys(self.path,data['keys'],PART)
            if self.current not in self.keys:raise ValueError()
            self.keys[self.current]
        except (OSError,ValueError,KeyError,TypeError):
            fail('CERTIFICATE_KEYS_UNAVAILABLE',503)

    def sign(self,purpose,value,version=None):
        version=version or self.current
        try:key=self.keys.get(version)
        except (OSError,ValueError,KeyError,TypeError):fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE',503)
        if key is None:fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE',503)
        message=(purpose+'\0'+value).encode()
        return base64.urlsafe_b64encode(hmac.digest(key,message,'sha256')).decode().rstrip('=')

    def token(self,purpose,ident,version=None):
        version=version or self.current
        if not isinstance(ident,str) or not PART.fullmatch(ident):fail('TOKEN_INVALID',404)
        return version+'.'+ident+'.'+self.sign(purpose,ident,version)

    def verify(self,purpose,token):
        if not isinstance(token,str) or len(token)>220:fail('NOT_FOUND',404)
        parts=token.split('.')
        if len(parts)!=3 or not all(PART.fullmatch(p) for p in parts):fail('NOT_FOUND',404)
        version,ident,signature=parts
        if version not in self.keys:fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE',503)
        if not hmac.compare_digest(signature,self.sign(purpose,ident,version)):fail('NOT_FOUND',404)
        return ident,version

    def nonce(self,browser_id,link_id):
        epoch=str(int(time.time())//900)
        value=browser_id+':'+link_id+':'+epoch
        return self.current+'.'+epoch+'.'+self.sign('request-nonce',value)

    def check_nonce(self,nonce,browser_id,link_id):
        if not isinstance(nonce,str) or len(nonce)>180:fail('REQUEST_NONCE_INVALID',403)
        parts=nonce.split('.')
        if len(parts)!=3:fail('REQUEST_NONCE_INVALID',403)
        version,epoch,signature=parts
        if not epoch.isdigit() or abs(int(time.time())//900-int(epoch))>1:fail('REQUEST_NONCE_EXPIRED',403)
        if version not in self.keys or not hmac.compare_digest(signature,self.sign('request-nonce',browser_id+':'+link_id+':'+epoch,version)):
            fail('REQUEST_NONCE_INVALID',403)

def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
