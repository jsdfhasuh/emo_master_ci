"""Fixed public ingress for the current manual request; no private credential."""
import json
import os
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

PRODUCT = 1343796337
BASE = '48b30191884ad5ef5d96e8d26591104d16d54a58'
PR = '45769545809'
MANUAL = '45784197740'
# artifact ID, ZIP digest, ZIP size, head, execution, branch, origin workflow id/path/blob
PAIRS = {
    MANUAL: ('15099621786','bf57c0e9d5c03fd6ee152241c1240451510ba12709581e5423c2fe53d6190208',357,'5da12339c74b3517ea12946747c3f72c2c8ed98d','5da12339c74b3517ea12946747c3f72c2c8ed98d','dot/mainline-ci-migration-20261124',431177979,'product-source-shadow-request.yml','06b25edb140bf4ba1814fb463b187b9f835cda14'),
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
        need(row['actor']['id']==row['triggering_actor']['id']==49879362)
        # An explicit workflow_dispatch on this branch can carry PR association
        # metadata. That association is not an event or merge execution identity.
        links = row['pull_requests']
        need(type(links) is list and len(links)==1)
        linked=links[0]
        need(linked['number']==26 and linked['head']['repo']['id']==linked['base']['repo']['id']==PRODUCT
             and linked['head']['ref']==branch and linked['head']['sha']==head
             and linked['base']['ref']=='main' and linked['base']['sha']==ref('heads/main')==BASE)
    need(api('contents/'+path+'?ref='+execution)['sha']==blob)
    return execution

if __name__=='__main__':
    try:
        execution=bind(sys.argv[1],sys.argv[2],get)
        with open(os.environ['GITHUB_OUTPUT'],'a') as f: print('execution_sha='+execution,file=f)
    except Exception:
        sys.exit('source_event=identity_refused')
