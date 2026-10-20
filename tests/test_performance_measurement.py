import httpx
import pytest
from performance_support import classify_exception, classify_response


@pytest.mark.parametrize('code,body,count,category',[
    (200,{'receipts':[]},1,'receipt_count_mismatch'),
    (200,{'receipts':[{'status':'accepted'}]},1,'passed'),
    (200,{'receipts':[{'status':'rejected'}]},1,'business_or_receipt_rejection'),
    (200,{'receipts':[{}]},1,'malformed_response'),
    (200,{},1,'malformed_response'),
    (403,{},None,'http_4xx'),(503,{},None,'http_5xx'),
],ids=['empty-is-not-success','accepted','rejected-row','missing-status','missing-list','auth','server'])
def test_error_units_remain_explainable(code,body,count,category):
    result,statuses=classify_response(httpx.Response(code,json=body),count)
    assert result==category
    assert sum(statuses.values()) in (0,count or 0)


def test_transport_failures_do_not_expose_exception_text():
    for error,expected in [(httpx.ReadTimeout('secret'),'transport_timeout'),(httpx.ConnectError('secret'),'connection_error'),(ValueError('secret'),'client_exception')]:
        assert classify_exception(error)==expected


def test_unavailable_process_metrics_are_blocked_not_fabricated(monkeypatch):
    import load_profiles,psutil
    def inaccessible(pid):raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(load_profiles.psutil,'Process',inaccessible)
    result=load_profiles.resources(12345)
    assert result=={'available':False,'reason':'PROCESS_TREE_UNAVAILABLE','exception_type':'NoSuchProcess'}
    assert 'rss' not in result
