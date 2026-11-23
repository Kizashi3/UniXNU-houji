#!/usr/bin/env python3
"""Install the bounded houji observer on the pinned r30 GUI kernel source."""
import argparse,hashlib,json
from pathlib import Path

def digest(data):return hashlib.sha256(data).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu',type=Path,required=True);a=p.parse_args()
 source=Path(__file__).resolve().parents[1]/'native/userland-sampler';m=json.loads((source/'manifest.json').read_text())
 sampler=(source/'sweet_sample.c').read_bytes();task=(source/'sweet_sample_task.inc').read_bytes()
 if digest(sampler)!=m['new_trial_sampler_sha256'] or digest(task)!=m['new_task_function_sha256']:raise ValueError('Observer sources changed; review manifest')
 target=a.xnu/'bsd/dev/sweet_sample.c';exception=a.xnu/'osfmk/kern/exception.c';old=target.read_bytes();text=exception.read_text()
 begin=text.index('void\nsweet_sample_task(const char *name, int pid, task_t task)');end=text.index('\n#endif /* ARM64_BOARD_CONFIG_SWEET */',begin)
 if digest(old) not in [m['old_trial_sampler_sha256'],m['new_trial_sampler_sha256'],*m.get('previous_trial_sampler_sha256',[])]:raise ValueError('Unexpected trial sampler')
 if digest(text[begin:end].encode()) not in (m['old_task_function_sha256'],m['new_task_function_sha256']):raise ValueError('Unexpected task sampler')
 # Both inputs verified before either source is changed. No device access.
 target.write_bytes(sampler);exception.write_text(text[:begin]+task.decode()+text[end:]);print('Observer installed; user stack reads run after task_unlock')
if __name__=='__main__':main()
