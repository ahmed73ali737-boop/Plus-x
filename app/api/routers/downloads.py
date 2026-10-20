"""Public APK distribution is withdrawn pending investigation of a user security warning."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

APK_NAME='Eventna-Android-Preview-1.0.3.apk'


def verify_preview_artifact(root: Path):
    """Integrity audit of the withdrawn binary, never a distribution approval."""
    folder=root/'artifacts'/'android'
    try:
        evidence=json.loads((folder/'BUILD_EVIDENCE.json').read_text(encoding='utf-8'))
        content=(folder/APK_NAME).read_bytes()
        if not content or len(content)!=evidence['apk_bytes'] or hashlib.sha256(content).hexdigest()!=evidence['apk_sha256']:
            raise ValueError('artifact mismatch')
        if evidence['signing']!='disposable_debug_key_not_production' or evidence['package']!='com.pulsex.app.preview':
            raise ValueError('unexpected artifact contract')
        return evidence
    except (OSError,ValueError,KeyError,TypeError):
        raise HTTPException(status_code=503,detail='ANDROID_PREVIEW_UNAVAILABLE')


def create_download_router(root: Path):
    router=APIRouter(tags=['downloads'])
    @router.get('/api/downloads/android')
    def android_metadata():
        return {'available':False,'channel':'withdrawn','security_status':'review_required',
                'reason':'ANDROID_SECURITY_REVIEW_REQUIRED','web_url':'/',
                'reported_apk_sha256':'6d1b47087f1e93c29917e6a8a482dc8fc9af4db056c8b42d2c2d96b753f66e87'}
    @router.api_route('/downloads/eventna-android-preview.apk',methods=['GET','HEAD'],include_in_schema=False)
    @router.api_route('/downloads/pulsex-android-preview.apk',methods=['GET','HEAD'],include_in_schema=False)
    def download_android():
        raise HTTPException(status_code=410,detail='ANDROID_SECURITY_REVIEW_REQUIRED',
                            headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    return router
