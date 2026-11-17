#!/bin/bash
# usage: wait-run.sh <short-sha> [max-minutes]
set -u
SHA=$1
LIMIT=${2:-40}
export GH_TOKEN=public
for i in $(seq 1 $((LIMIT*2))); do
  J=$(gh api -H "Authorization: none" "repos/Kizashi3/UniXNU-houji/actions/runs?per_page=10" 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('API_ERR - - -'); raise SystemExit
for r in d.get('workflow_runs',[]):
    if r['head_sha'].startswith('$SHA'):
        print(r['run_number'], r['status'], r['conclusion'], r['id']); break
else:
    print('NONE - - -')
")
  set -- $J
  N=$1; S=$2; C=$3; ID=$4
  echo "$(date +%H:%M) run=$N status=$S conclusion=$C"
  if [ "$S" = "completed" ]; then
    if [ "$C" != "success" ]; then
      gh api -H "Authorization: none" "repos/Kizashi3/UniXNU-houji/actions/runs/$ID/jobs" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for j in d['jobs']:
    for s in j['steps']:
        if s['conclusion'] not in ('success','skipped',None):
            print('FAILED STEP:', s['name'])
"
    fi
    echo "DONE $C run=$N"
    exit 0
  fi
  sleep 30
done
echo TIMEOUT
