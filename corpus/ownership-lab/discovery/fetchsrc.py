"""discovery S4: fetch the resource-bearing source files at the nuspec-pinned commit from raw.githubusercontent.com.
usage: fetchsrc.py <PackageId> <owner/repo> <commit> <path> [<path> ...]   (cap 25 files; digests recorded)"""
import sys, os, json, hashlib, urllib.request
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
pid, repo, commit, paths = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:][:25]
d=f'{S}/lab/disc/libs/{pid}/src'; os.makedirs(d, exist_ok=True); rec=[]
for p in paths:
    url=f'https://raw.githubusercontent.com/{repo}/{commit}/{p}'; out=f'{d}/{p.replace("/","__")}'
    try:
        with urllib.request.urlopen(url, timeout=60) as r: data=r.read()
        open(out,'wb').write(data); rec.append({'path':p,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    except Exception as e:
        rec.append({'path':p,'error':str(e)[:80]})
json.dump({'package':pid,'repo':repo,'commit':commit,'files':rec}, open(f'{S}/lab/disc/libs/{pid}/s4-source.json','w'), indent=1)
ok=[r for r in rec if 'sha256' in r]; print(pid, 'fetched', len(ok), 'of', len(rec), 'errors:', [r['path'] for r in rec if 'error' in r])
