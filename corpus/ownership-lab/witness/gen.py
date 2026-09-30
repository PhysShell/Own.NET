"""H-10 runtime-witness generator: one console project per effect row; the deterministic verdict comes
from identity / disposed-state / ObjectDisposedException observations on the deployed binary."""
import json, os, subprocess, sys, time
W='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad/lab/witness'
import sys as _s; ROWS=_s.argv[1] if len(_s.argv)>1 else f'{W}/rows.json'; OUTF=_s.argv[2] if len(_s.argv)>2 else f'{W}/results.json'; rows=json.load(open(ROWS))
CSPROJ='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><Nullable>disable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>{refs}</Project>'
FRESH='''using System; using System.IO; using System.Threading;
{setup}
object Make() => {expr};
string disposedProbe = "n/a"; string err = null;
object w1, w2, w3;
try {{ w1 = Make(); w2 = Make(); w3 = Make(); }}
catch (Exception e) {{ Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ verdict = "environment-error", err = e.GetType().Name, msg = e.Message.Length > 120 ? e.Message.Substring(0, 120) : e.Message }})); return; }}
var b = w2;
bool distinct = !ReferenceEquals(w1,w2) && !ReferenceEquals(w2,w3) && !ReferenceEquals(w1,w3);
bool same = ReferenceEquals(w1,w2) && ReferenceEquals(w2,w3);
if ({dispose}) {{ try {{ ((IDisposable)w1).Dispose(); {probe} }} catch (Exception e) {{ err = e.GetType().Name; }} }}
string verdict = same ? "cached" : distinct ? "fresh" : "inconclusive";
Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ distinct, same, disposedProbe, err, verdict, asm = w1.GetType().Assembly.ManifestModule.ModuleVersionId.ToString(), type = w1.GetType().FullName }}));
'''
TERM='''using System; using System.IO; using System.Threading;
string outcome; string err = null;
try {{
  var r = {create};
  {release}
  try {{ {use} outcome = "no_throw"; }} catch (ObjectDisposedException) {{ outcome = "ObjectDisposedException"; }} catch (Exception e) {{ outcome = "other:" + e.GetType().Name; }}
}} catch (Exception e) {{ outcome = "environment-error"; err = e.GetType().Name; }}
string verdict = outcome == "ObjectDisposedException" ? "terminal" : outcome == "no_throw" ? "not_observed" : outcome == "environment-error" ? "environment-error" : "inconclusive";
Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ outcome, err, verdict }}));
'''
env=dict(os.environ); env['PATH']='/root/.dotnet:'+env['PATH']; env['DOTNET_CLI_TELEMETRY_OPTOUT']='1'; env['DOTNET_NOLOGO']='1'
results=[]
for r in rows:
    d=f'{W}/{r["id"]}'; os.makedirs(d, exist_ok=True)
    import os as _o
    if r.get('package'): refs=f'<ItemGroup><PackageReference Include="{r["package"]}" Version="{r["version"]}" /></ItemGroup>'
    elif r.get('ref'): refs=f'<ItemGroup><Reference Include="{_o.path.splitext(_o.path.basename(r["ref"]))[0]}"><HintPath>{r["ref"]}</HintPath></Reference></ItemGroup>'
    else: refs=''
    open(f'{d}/w.csproj','w').write(CSPROJ.format(refs=refs))
    if r['kind']=='fresh':
        src=FRESH.format(setup=r.get('setup',''), expr=r['expr'], dispose='true' if r.get('dispose') else 'false', probe=r.get('probe',''))
    else:
        src=TERM.format(create=r['create'], release=r['release'], use=r['use'])
    open(f'{d}/Program.cs','w').write(src)
    t=time.time()
    p=subprocess.run(['dotnet','run','-c','Release','--project',f'{d}/w.csproj'],capture_output=True,text=True,env=env,timeout=600)
    line=[l for l in p.stdout.splitlines() if l.startswith('WITNESS ')]
    res={'id':r['id'],'callable':r['callable'],'expect':r['expect'],'seconds':round(time.time()-t,1)}
    if line: res.update(json.loads(line[-1][8:]))
    else: res.update({'verdict':'build-or-run-error','stderr':(p.stderr+p.stdout)[-600:]})
    results.append(res); print(json.dumps(res)); sys.stdout.flush()
json.dump(results, open(OUTF,'w'), indent=1)
print('WITNESS_DONE')
