"""Bounded, low-cardinality certificate metrics; no names, tokens, or owner labels."""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
import threading,time,math
_STAGES=frozenset({'export_snapshot','export','generation','render','render_child','storage','lease','history','accepted','issued','failed','retry','deduplicated','export_rows','render_busy','storage_error'})
_lock=threading.Lock()
_values=defaultdict(lambda:{'count':0,'seconds_sum':0.0,'seconds_max':0.0})
_meter=None
_counter=None
_histogram=None
_GAUGE_NAMES=frozenset({'queue_age_seconds','queue_pending','export_pending','storage_free_bytes','active_slots','failed_jobs'})
_gauges={}


def configure(provider):
    global _meter,_counter,_histogram
    if provider is not None:
        _meter=provider.get_meter('PulseX.Certificates')
        _counter=_meter.create_counter('certificates.operations',unit='{operation}')
        _histogram=_meter.create_histogram('certificates.duration',unit='s')
        from opentelemetry.metrics import Observation
        for name in _GAUGE_NAMES:
            _meter.create_observable_gauge('certificates.'+name,
                callbacks=[lambda options,n=name:[Observation(gauges().get(n,0))]])


def record(stage, seconds=None, amount=1):
    if stage not in _STAGES:
        raise ValueError('CERTIFICATE_METRIC_STAGE_INVALID')
    if type(amount) is not int or amount<0:
        raise ValueError('CERTIFICATE_METRIC_AMOUNT_INVALID')
    with _lock:
        row=_values[stage]
        row['count']+=amount
        if seconds is not None:
            row['seconds_sum']+=seconds
            row['seconds_max']=max(row['seconds_max'],seconds)
    if _counter:_counter.add(amount,{'stage':stage})
    if seconds is not None and _histogram:_histogram.record(seconds,{'stage':stage})


def snapshot():
    with _lock:return {k:dict(v) for k,v in _values.items()}


def timed(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            started=time.perf_counter()
            try:return function(*args,**kwargs)
            finally:record(stage,time.perf_counter()-started)
        return wrapped
    return decorate


def gauge(name,value):
    if name not in _GAUGE_NAMES or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0:
        raise ValueError('CERTIFICATE_METRIC_GAUGE_INVALID')
    with _lock:_gauges[name]=value

def gauges():
    with _lock:return dict(_gauges)
