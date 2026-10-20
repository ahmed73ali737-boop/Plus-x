"""Only the pinned public Android preview may be downloaded; no arbitrary paths."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

APK_NAME='Eventna-Android-Preview-1.0.3.apk'


def create_download_router(root: Path):
    router=APIRouter(tags=['downloads'])
    folder=root/'artifacts'/'android'
    path=folder/APK_NAME
    def verified():
        try:
            evidence=json.loads((folder/'BUILD_EVIDENCE.json').read_text(encoding='utf-8'))
            content=path.read_bytes()
            if not content or len(content)!=evidence['apk_bytes'] or hashlib.sha256(content).hexdigest()!=evidence['apk_sha256']:
                raise ValueError('artifact mismatch')
            if evidence['signing']!='disposable_debug_key_not_production' or evidence['package']!='com.pulsex.app.preview':
                raise ValueError('unexpected artifact contract')
            return evidence
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(status_code=503,detail='ANDROID_PREVIEW_UNAVAILABLE')

    @router.get('/api/downloads/android')
    def android_metadata():
        e=verified()
        return {'available':True,'version':'1.0.3','channel':'preview','production_signed':False,
                'download_url':'/downloads/eventna-android-preview.apk','bytes':e['apk_bytes'],
                'sha256':e['apk_sha256'],'min_android':8,'source_revision':e['source_revision'],
                'device_tested':e.get('device_tested') is True,'server_included':False}

    @router.api_route('/downloads/eventna-android-preview.apk',methods=['GET','HEAD'],include_in_schema=False)
    @router.api_route('/downloads/pulsex-android-preview.apk',methods=['GET','HEAD'],include_in_schema=False)
    def download_android():
        e=verified()
        return FileResponse(path,filename=APK_NAME,media_type='application/vnd.android.package-archive',
                            headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-cache',
                                     'ETag':'"'+e['apk_sha256']+'"'})
    return router
