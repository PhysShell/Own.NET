"""H-10 runtime-witness generator: one console project per effect row; the deterministic verdict comes
from identity / disposed-state / ObjectDisposedException observations on the deployed binary."""
import json, os, subprocess, sys, time
W='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad/lab/witness'
import sys as _s; ROWS=_s.argv[1] if len(_s.argv)>1 else f'{W}/rows.json'; OUTF=_s.argv[2] if len(_s.argv)>2 else f'{W}/results.json'; rows=json.load(open(ROWS))
CSPROJ='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>{tfm}</TargetFramework><RollForward>Major</RollForward><Nullable>disable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>{refs}</Project>'
FRESH='''using System; using System.IO; using System.Threading;
{setup}
object Make() => {expr};
string disposedProbe = "n/a"; string err = null;
object w1, w2, w3;
void DisposeIt(object o) {{ try {{ (o as IDisposable)?.Dispose(); }} catch (Exception) {{ }} }}
try {{ {makes} }}
catch (Exception e) {{ Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ verdict = "environment-error", err = e.GetType().Name, msg = e.Message.Length > 120 ? e.Message.Substring(0, 120) : e.Message }})); return; }}
if (w1 == null || w2 == null || w3 == null) {{ Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ verdict = "null-result", nulls = (w1 == null ? 1 : 0) + (w2 == null ? 1 : 0) + (w3 == null ? 1 : 0) }})); return; }}
var b = w2;
bool distinct = !ReferenceEquals(w1,w2) && !ReferenceEquals(w2,w3) && !ReferenceEquals(w1,w3);
bool same = ReferenceEquals(w1,w2) && ReferenceEquals(w2,w3);
if ({dispose}) {{ try {{ ((IDisposable)w3).Dispose(); {probe} }} catch (Exception e) {{ err = e.GetType().Name; }} }}
string verdict = same ? "cached" : distinct ? "fresh" : "inconclusive";
Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ distinct, same, disposedProbe, err, verdict, mode = "{mode}", asm = w1.GetType().Assembly.ManifestModule.ModuleVersionId.ToString(), type = w1.GetType().FullName }}));
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
RECV='''using System; using System.IO; using System.Threading;
{setup}
object Make() => {expr};
string outcome; string err = null; string probe = "unprobed";
try {{
  var r = Make();
  if (r == null) {{ outcome = "null-result"; }}
  else {{
    try {{ ((IDisposable){recv}).Dispose(); }} catch (Exception e) {{ err = "recv:" + e.GetType().Name; }}
    var t = r.GetType(); object v;
    var ph = t.GetProperty("Handle"); var pd = t.GetProperty("IsDisposed"); var pc = t.GetProperty("IsClosed");
    if (ph != null && ph.PropertyType == typeof(IntPtr)) {{ v = ph.GetValue(r); probe = ((IntPtr)v == IntPtr.Zero) ? "invalidated:Handle" : "alive:Handle"; }}
    else if (pd != null && pd.PropertyType == typeof(bool)) {{ v = pd.GetValue(r); probe = ((bool)v) ? "invalidated:IsDisposed" : "alive:IsDisposed"; }}
    else if (pc != null && pc.PropertyType == typeof(bool)) {{ v = pc.GetValue(r); probe = ((bool)v) ? "invalidated:IsClosed" : "alive:IsClosed"; }}
    outcome = probe.StartsWith("invalidated") ? "receiver_bound" : probe.StartsWith("alive") ? "independent" : "unprobed";
    try {{ ((IDisposable)r).Dispose(); }} catch (Exception e) {{ err = (err ?? "") + " dispose:" + e.GetType().Name; }}
  }}
}} catch (Exception e) {{ outcome = "environment-error"; err = e.GetType().Name + ": " + (e.Message.Length > 100 ? e.Message.Substring(0, 100) : e.Message); }}
Console.WriteLine("WITNESS " + System.Text.Json.JsonSerializer.Serialize(new {{ outcome, probe, err, verdict = outcome }}));
'''
env=dict(os.environ); env['PATH']='/root/.dotnet:'+env['PATH']; env['DOTNET_CLI_TELEMETRY_OPTOUT']='1'; env['DOTNET_NOLOGO']='1'
import shutil
PART=OUTF+'.partial.jsonl'; done={}
if os.path.exists(PART):
    for l in open(PART):
        try: j=json.loads(l); done[j['id']]=j
        except Exception: pass
results=[]
for r in rows:
    if r['id'] in done and done[r['id']].get('verdict') not in ('build-or-run-error','environment-error'): results.append(done[r['id']]); continue
    d=f'{W}/{r["id"]}'; os.makedirs(d, exist_ok=True)
    import os as _o
    refs=''
    if r.get('packages'): refs+='<ItemGroup>'+''.join(f'<PackageReference Include="{pid}" Version="{ver}" />' for pid,ver in r['packages'])+'</ItemGroup>'
    elif r.get('package'): refs+=f'<ItemGroup><PackageReference Include="{r["package"]}" Version="{r["version"]}" /></ItemGroup>'
    if r.get('ref'): refs+=f'<ItemGroup><Reference Include="{_o.path.splitext(_o.path.basename(r["ref"]))[0]}"><HintPath>{r["ref"]}</HintPath></Reference></ItemGroup>'
    if r.get('native'): refs+=f'<ItemGroup><None Include="{r["native"]}" Link="{_o.path.basename(r["native"])}" CopyToOutputDirectory="PreserveNewest" /></ItemGroup>'
    open(f'{d}/w.csproj','w').write(CSPROJ.format(refs=refs,tfm=r.get('tfm','net8.0')))
    if r['kind']=='fresh':
        mode=r.get('mode','parallel')
        makes='w1 = Make(); DisposeIt(w1); w2 = Make(); DisposeIt(w2); w3 = Make();' if mode=='sequential' else 'w1 = Make(); w2 = Make(); w3 = Make();'
        src=FRESH.format(setup=r.get('setup',''), expr=r['expr'], dispose='true' if r.get('dispose') else 'false', probe=r.get('probe',''), makes=makes, mode=mode)
    elif r['kind']=='recvprobe':
        src=RECV.format(setup=r.get('setup',''), expr=r['expr'], recv=r['recv'])
    else:
        src=TERM.format(create=r['create'], release=r['release'], use=r['use'])
    open(f'{d}/Program.cs','w').write(src)
    t=time.time()
    p=subprocess.run(['dotnet','run','-c','Release','--project',f'{d}/w.csproj'],capture_output=True,text=True,env=env,timeout=600)
    line=[l for l in p.stdout.splitlines() if l.startswith('WITNESS ')]
    res={'id':r['id'],'callable':r['callable'],'expect':r['expect'],'seconds':round(time.time()-t,1),'tfm':r.get('tfm','net8.0'),'packages':r.get('packages')}
    if line: res.update(json.loads(line[-1][8:]))
    else:
        so=(p.stderr+p.stdout); res.update({'verdict':'build-or-run-error','stderr':(so[:500]+' ... '+so[-500:]) if len(so)>1000 else so})
    import hashlib as _h; res['src_sha']=_h.sha256(src.encode()).hexdigest()[:12]
    results.append(res); print(json.dumps(res)); sys.stdout.flush(); open(PART,'a').write(json.dumps(res)+'\n')
    for sub in ('bin','obj'): shutil.rmtree(f'{d}/{sub}', ignore_errors=True)
json.dump(results, open(OUTF,'w'), indent=1)
print('WITNESS_DONE')
