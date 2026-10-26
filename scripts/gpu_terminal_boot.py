"""Bind terminal DMA experiments to one observed boot; fail after a reboot."""
import json,time,re
from gpu_terminal_live import ROOT
LEASE=ROOT/'.cache/gpu-live-lease.json'
def validate(live):
    lease=json.loads(LEASE.read_text())
    now=time.monotonic()
    elapsed=now-lease['host_monotonic']
    assert 0<=elapsed<86400,'Boot lease expired'
    uptime=int(live.command('uptime',r'GIULIA TERM: uptime_ms=(\d+)')[1])
    assert abs(uptime-lease['uptime_ms']-elapsed*1000)<5000,'Device restarted; recapture and bind new allocation evidence'
    return lease
