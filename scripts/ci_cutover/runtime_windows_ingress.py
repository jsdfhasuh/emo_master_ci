"""Runtime candidate admission: require a unique approved manual input tuple."""
import json
import os
from windows_ingress import check, ident, require, sha
import re
from urllib.parse import quote

BUILDER='e0204fe6fe83b0f31818d88e4f296c70e230d172'

def verify(policy, msg, read):
    require(policy.get('route')=='runtime-windows' and msg.get('route')=='runtime-windows')
    request=msg.copy()
    source_ref=request.pop('source_ref')
    packager_ref=request.pop('packager_ref')
    run=read(f"/actions/runs/{ident(request['source_run'])}")
    require(run.get('event')=='workflow_dispatch')
    approved=policy['approved_inputs']
    # Only one exact reviewed pair is allowed per workflow blob. Do not infer a
    # caller's other inputs from their source/merge SHA.
    require(type(approved) is dict and set(approved)=={'source_ref','packager_ref','source_sha','builder_sha'})
    require(source_ref==approved['source_ref'] and packager_ref==approved['packager_ref'])
    require(sha(approved['source_sha'])==request['execution'] and sha(approved['builder_sha'])==BUILDER)
    require(type(source_ref) is str and len(source_ref)<=200)
    if re.fullmatch("[0-9a-f]{40}",source_ref):
        require(sha(source_ref)==request["execution"])
    else:
        require(re.fullmatch(r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9_./-]*",source_ref) and
                ".." not in source_ref and "//" not in source_ref and not source_ref.endswith((".", "/", ".lock")))
        pointer=read("/git/ref/"+quote(source_ref.removeprefix("refs/"),safe="/"))["object"]
        require(pointer.get("type")=="commit" and pointer.get("sha")==request["execution"])
    commit=read("/git/commits/"+request["execution"])
    require(commit.get("sha")==request["execution"])
    require(type(packager_ref) is str and packager_ref==BUILDER)
    execution,tag=check(policy,request,read)
    require(not tag)
    return execution

def main():
    from windows_ingress import fetch
    try:
        raw=os.environ['WORKER_REQUEST'].encode('ascii')
        require(len(raw)<=4096)
        def unique(pairs):
            d={}
            for k,v in pairs:
                require(k not in d)
                d[k]=v
            return d
        with open('controller/.github/ci-cutover/runtime-windows-public-policy.json','rb') as f:
            policy=json.load(f,object_pairs_hook=unique)
        require(policy.get('enabled') is True)
        execution=verify(policy,json.loads(raw,object_pairs_hook=unique),fetch)
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='ascii') as f:
            f.write(f'execution_sha={execution}\n')
    except Exception:
        raise SystemExit('runtime_windows_ingress=refused') from None

if __name__=='__main__':
    main()
