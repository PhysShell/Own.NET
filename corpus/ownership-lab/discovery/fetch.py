"""discovery S1: acquire the exact binary (nupkg from the NuGet flat container), its nuspec repository pin, the
highest-TFM lib assembly and its identity (MVID/sha256). usage: fetch.py <PackageId> <version>"""
import sys, os, json, hashlib, zipfile, urllib.request, re, subprocess
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'
pid, ver = sys.argv[1], sys.argv[2]
d=f'{S}/lab/disc/libs/{pid}'; os.makedirs(d, exist_ok=True)
nupkg=f'{d}/{pid.lower()}.{ver}.nupkg'
if not os.path.exists(nupkg):
    urllib.request.urlretrieve(f'https://api.nuget.org/v3-flatcontainer/{pid.lower()}/{ver}/{pid.lower()}.{ver}.nupkg', nupkg)
sha=hashlib.sha256(open(nupkg,'rb').read()).hexdigest()
z=zipfile.ZipFile(nupkg)
spec=[n for n in z.namelist() if n.endswith('.nuspec')][0]; xml=z.read(spec).decode('utf-8','replace')
repo=re.search(r'<repository[^>]*url="([^"]+)"[^>]*commit="([^"]+)"', xml) or re.search(r'<repository[^>]*commit="([^"]+)"[^>]*url="([^"]+)"', xml)
url=commit=None
if repo:
    a,b=repo.group(1),repo.group(2); (url,commit)=(a,b) if a.startswith('http') else (b,a)
tfms=['net8.0','net9.0','net10.0','net7.0','net6.0','netstandard2.1','netstandard2.0','net462','net461','net45']
libs=[n for n in z.namelist() if n.startswith('lib/') and n.endswith('.dll')]
chosen=None
for t in tfms:
    c=[n for n in libs if n.split('/')[1]==t]
    if c: chosen=c; break
if chosen is None and libs: chosen=libs
out=[]
if chosen:
    for n in chosen:
        p=f'{d}/lib/{n.split("/")[1]}/{os.path.basename(n)}'; os.makedirs(os.path.dirname(p), exist_ok=True); open(p,'wb').write(z.read(n)); out.append(p)
main=[p for p in out if os.path.basename(p).lower()==f'{pid.lower()}.dll'] or out[:1]
ident=None
if main:
    r=subprocess.run(['dotnet',f'{R}/frontend/roslyn/OwnSharp.AsmId/bin/Release/net8.0/ownsharp-asmid.dll',main[0]],capture_output=True,text=True,env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1'})
    try: ident=json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: ident={'error':r.stderr[-300:]}
rec={'package':pid,'version':ver,'nupkg_sha256':sha,'repository_url':url,'repository_commit':commit,'lib_files':out,'main_assembly':main[0] if main else None,'identity':ident,'xmldoc':[n for n in z.namelist() if n.endswith('.xml') and n.startswith('lib/')][:3]}
json.dump(rec, open(f'{d}/acquire.json','w'), indent=1); print(json.dumps({k:rec[k] for k in ('package','version','repository_url','repository_commit','main_assembly')}), 'mvid=', (ident or {}).get('mvid'))
