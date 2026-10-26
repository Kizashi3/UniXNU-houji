"""Decode complete byte-preserving startup records without discarding successes."""
import argparse,collections,hashlib,json,re
from pathlib import Path

ULOG=re.compile(rb'ULOG pid=(\d+) name=([^\s]+) ticks=([0-9a-f]+) bytes=(\d+) hex=([0-9a-f]*)\r?\n')

def lines_across_files(inputs,sources):
    pending=b''
    for path in inputs:
        state=hashlib.sha256();size=0
        with path.open('rb') as stream:
            while chunk:=stream.read(1024**2):
                state.update(chunk);size+=len(chunk)
                pieces=(pending+chunk).split(b'\n');pending=pieces.pop()
                for line in pieces:yield path,line+b'\n'
        sources.append({'path':str(path),'bytes':size,'sha256':state.hexdigest()})
    if pending:yield inputs[-1],pending

def decode(inputs,out):
    out.mkdir(parents=True,exist_ok=False); processes=out/'processes';processes.mkdir()
    handles={};counts=collections.Counter();events=[];bad=[];seen=collections.OrderedDict();sources=[];statuses=[];boot_header=False
    with (out/'kernel.log').open('wb') as kernel:
        for path,line in lines_across_files(inputs,sources):
            if b'Darwin Kernel Version ' in line:boot_header=True
            if line.startswith(b'VERMEER DEBUG: ACE5DBG001 events='):
                statuses.append({k.decode():int(v) for k,v in re.findall(rb'(events|tx|rx|log|dropped|ring_bytes)=(\d+)',line)})
            m=ULOG.fullmatch(line)
            if m:
                pid,name,ticks,length,encoded=m.groups();data=bytes.fromhex(encoded.decode())
                if len(data)!=int(length):bad.append({'file':str(path),'reason':'length mismatch'});kernel.write(line);continue
                identity=hashlib.blake2s(line,digest_size=16).digest()
                if identity in seen:counts['replayed_ulog_records']+=1;continue
                seen[identity]=None
                if len(seen)>250000:seen.popitem(last=False)
                safe=re.sub(r'[^A-Za-z0-9_.-]','_',name.decode('utf-8','replace'))+'-'+pid.decode()+'.log'
                if safe not in handles:handles[safe]=(processes/safe).open('wb')
                handles[safe].write(data);counts['ulog_records']+=1;counts['ulog_bytes']+=len(data)
            else:
                kernel.write(line)
                if line.startswith(b'ULOG '):
                    bad.append({'file':str(path),'reason':'malformed or incomplete ULOG record','prefix':line[:100].decode('ascii','replace')})
                if line.startswith((b'EXEC ',b'EXIT ',b'EXIT_REASON ',b'SMP --- ',b'VERMEER DEBUG: ',b'GIULIA LOG: ',b'GIULIA AMFI: ',b'CRASH ')):
                    events.append(line.decode('utf-8','replace').rstrip('\r\n'))
    for handle in handles.values():handle.close()
    report={'sources':sources,'process_log_files':sorted(handles),'counts':dict(counts),
            'events':events,'incomplete_records':bad,'healthy_and_failed_paths_retained':True,
            'transport_audit':{'boot_header_seen':boot_header,'status_samples':statuses,
                'max_kernel_dropped_bytes':max((s.get('dropped',0) for s in statuses),default=None),
                'ram_history_evicted_bytes':max((max(0,s.get('log',0)-s.get('ring_bytes',33554432)) for s in statuses),default=None),
                'ram_history_note':'Eviction describes retained RAM history; a continuous host capture may already contain it. Missing status is unknown, not zero loss.'}}
    (out/'index.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Decoded {counts["ulog_records"]} records into {len(handles)} process logs; incomplete records={len(bad)}')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path,help='Capture directory or one serial log')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    files=sorted(args.input.glob('serial-*.log')) if args.input.is_dir() else [args.input]
    if not files:parser.error('No serial logs')
    decode(files,args.out)
