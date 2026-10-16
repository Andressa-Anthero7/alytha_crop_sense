"""Shared pacing of Copernicus requests, with bounded rate-limit retries."""
import math
import threading
import time
from contextlib import contextmanager
from urllib.error import HTTPError


class RateGate:
    def __init__(self,interval=5,clock=time.monotonic,sleep=time.sleep):
        self.interval=interval;self.clock=clock;self.sleep=sleep
        self.lock=threading.RLock();self.next_at=0

    def wait(self):
        while self.next_at>self.clock():self.sleep(min(30,self.next_at-self.clock()))

    @contextmanager
    def open(self,request,opener,timeout=120,prepare=None,milliseconds=True):
        with self.lock:
            response=None
            for attempt in range(3):
                self.wait()
                if prepare:prepare(request)
                # Token renewal uses this same reentrant gate and may reserve a new slot.
                self.wait()
                try:
                    response=opener(request,timeout=timeout);break
                except HTTPError as exc:
                    self.next_at=self.clock()+self.interval
                    if exc.code!=429:raise
                    delay=30*(2**attempt)
                    try:
                        retry=float((exc.headers or {}).get('Retry-After','0'))
                        if math.isfinite(retry):delay=max(delay,retry/(1000 if milliseconds else 1))
                    except (ValueError,TypeError):pass
                    self.next_at=self.clock()+max(self.interval,delay)
                    if attempt==2:raise
                    exc.close()
            try:
                with response as opened:yield opened
            finally:
                self.next_at=max(self.next_at,self.clock()+self.interval)


RATE=RateGate()
TOKEN={'credentials':None,'value':None,'expires_at':0}
