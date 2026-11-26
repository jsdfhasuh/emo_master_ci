"""Fixed, non-gating public ingress; authorized artifact digests verified by private run 45769764324."""
import json
import os
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

PRODUCT = 1343796337
BASE = '48b30191884ad5ef5d96e8d26591104d16d54a58'
PR = '45769545809'
MANUAL = '45769315376'
# artifact ID, ZIP digest, ZIP size, head, execution, branch, origin workflow id/path/blob
PAIRS = {
    MANUAL: ('15093262997','342b6fce612a063ae82236f4ad4cf4e91858fc8fd9fb50872214459c7fccd0b6',353,'d97afd8f99ccbb660acb6e9e0b03ead0502886b8','d97afd8f99ccbb660acb6e9e0b03ead0502886b8','dot/source-manual-receipt-pilot',341122678,'ci.yml','b99b2e6c4bfdb0b00b9ec920eee28acfad2f5407'),
    PR: ('15092934678','290ca946fe4b97f5eae563cfad136557433e9ff0d8f38c1dc7bb6f615f8a422f',388,'2afc355f8516c9ed0b56b885e54b301fbc42ff3a','7231957cc2402b743425d2005d88889792068348','dot/mainline-ci-migration-20261124',431177979,'product-source-shadow-request.yml','06b25edb140bf4ba1814fb463b187b9f835cda14')
}

def need(ok):
    if not ok: raise ValueError('identity refused')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None

def get(path):
    req = Request('https://api.github.com/repos/jsdfhasuh/emo_master/'+path,
                  headers={'X-GitHub-Api-Version':'2022-11-28','Accept':'application/vnd.github+json'})
    with build_opener(NoRedirect()).open(req, timeout=15) as r:
        data = r.read(1048577)
        need(len(data) <= 1048576)
        return json.loads(data)

def bind(run, artifact, api):
    need(run in PAIRS)
    art, digest, size, head, execution, branch, wid, filename, blob = PAIRS[run]
    need(artifact == art)
    path = '.github/workflows/'+filename
    row = api('actions/runs/'+run)
    event = 'pull_request' if run == PR else 'workflow_dispatch'
    need(all(row[k] == v for k,v in dict(id=int(run),run_attempt=1,event=event,
        workflow_id=wid,path=path,head_branch=branch,head_sha=head,status='completed',conclusion='success').items()))
    need(row['repository']['id'] == row['head_repository']['id'] == PRODUCT)
    a = api('actions/artifacts/'+art)
    need(a['id'] == int(art) and a['expired'] is False and a['digest']=='sha256:'+digest and
         a['size_in_bytes']==size and a['name']==f'ci-request-{run}-1' and
         a['workflow_run']['id']==int(run) and a['workflow_run']['repository_id']==PRODUCT and
         a['workflow_run']['head_repository_id']==PRODUCT and a['workflow_run']['head_sha']==head)
    ref = lambda name: api('git/ref/'+name)['object']['sha']
    need(ref('heads/'+branch)==head)
    if run == PR:
        links = row['pull_requests']
        need(len(links)==1 and links[0]['number']==26 and links[0]['head']['sha']==head and links[0]['base']['sha']==BASE)
        p = api('pulls/26')
        need(p['state']=='open' and p['number']==26 and p['mergeable'] is True and
             p['head']['repo']['id']==p['base']['repo']['id']==PRODUCT and
             p['head']['ref']==branch and p['head']['sha']==head and
             p['base']['ref']=='main' and p['base']['sha']==ref('heads/main')==BASE and
             p['merge_commit_sha']==ref('pull/26/merge')==execution)
        need([x['sha'] for x in api('git/commits/'+execution)['parents']]==[BASE,head])
    else:
        need(row['pull_requests']==[])
    need(api('contents/'+path+'?ref='+execution)['sha']==blob)
    return execution

if __name__=='__main__':
    try:
        execution=bind(sys.argv[1],sys.argv[2],get)
        with open(os.environ['GITHUB_OUTPUT'],'a') as f: print('execution_sha='+execution,file=f)
    except Exception:
        sys.exit('source_event=identity_refused')
