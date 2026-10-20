"""Bounded error classification: no raw response bodies, IDs or secrets in reports."""
from collections import Counter
import httpx


def classify_response(response, expected_receipts=None):
    if response.status_code>=500:return 'http_5xx',Counter()
    if response.status_code>=400:return 'http_4xx',Counter()
    if response.status_code!=200:return 'unexpected_http',Counter()
    if expected_receipts is None:return 'passed',Counter()
    try:receipts=response.json()['receipts']
    except (ValueError,KeyError,TypeError):return 'malformed_response',Counter()
    if not isinstance(receipts,list) or len(receipts)!=expected_receipts:return 'receipt_count_mismatch',Counter()
    if any(not isinstance(r,dict) or not isinstance(r.get('status'),str) for r in receipts):return 'malformed_response',Counter()
    # Map unknown statuses to a bounded label, never log arbitrary server content.
    known={'accepted','duplicate','rejected','verification_required'}
    statuses=Counter(r['status'] if r['status'] in known else 'unknown' for r in receipts)
    return ('passed' if statuses['accepted']==expected_receipts else 'business_or_receipt_rejection'),statuses


def classify_exception(error):
    if isinstance(error,httpx.TimeoutException):return 'transport_timeout'
    if isinstance(error,httpx.ConnectError):return 'connection_error'
    if isinstance(error,httpx.HTTPError):return 'transport_error'
    return 'client_exception'
