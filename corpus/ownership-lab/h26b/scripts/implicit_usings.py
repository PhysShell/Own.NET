"""SDK implicit global usings for a project (what the build would generate into obj/<Project>.GlobalUsings.g.cs):
Microsoft.NET.Sdk: System, System.Collections.Generic, System.IO, System.Linq, System.Net.Http, System.Threading,
System.Threading.Tasks; Microsoft.NET.Sdk.Web adds the ASP.NET Core / Microsoft.Extensions namespaces;
Microsoft.NET.Sdk.Worker adds Microsoft.Extensions.*; plus <Using Include="..."/> and minus <Using Remove="..."/> items
from the project file and every Directory.Build.props above it; nothing when ImplicitUsings is not enabled."""
import os, re, xml.etree.ElementTree as ET
BASE=['System','System.Collections.Generic','System.IO','System.Linq','System.Net.Http','System.Threading','System.Threading.Tasks']
WEB=['Microsoft.AspNetCore.Builder','Microsoft.AspNetCore.Hosting','Microsoft.AspNetCore.Http','Microsoft.AspNetCore.Routing','Microsoft.Extensions.Configuration','Microsoft.Extensions.DependencyInjection','Microsoft.Extensions.Hosting','Microsoft.Extensions.Logging']
WORKER=['Microsoft.Extensions.Configuration','Microsoft.Extensions.DependencyInjection','Microsoft.Extensions.Hosting','Microsoft.Extensions.Logging']
def props_chain(csproj):
    out=[]; d=os.path.dirname(os.path.abspath(csproj))
    while True:
        p=os.path.join(d,'Directory.Build.props')
        if os.path.exists(p): out.append(p)
        if d==os.path.dirname(d): break
        d=os.path.dirname(d)
    return out[::-1]   # outermost first
def implicit_usings(csproj):
    try: root=ET.parse(csproj).getroot()
    except Exception: return None
    sdk=(root.attrib.get('Sdk') or '')
    enabled=None; add=[]; rem=[]
    for f in props_chain(csproj)+[csproj]:
        try: r=ET.parse(f).getroot()
        except Exception: continue
        for e in r.iter():
            tag=e.tag.split('}')[-1]
            if tag=='ImplicitUsings' and (e.text or '').strip().lower() in ('enable','true'): enabled=True
            if tag=='ImplicitUsings' and (e.text or '').strip().lower() in ('disable','false'): enabled=False
            if tag=='Using' and e.attrib.get('Include'): add.append(e.attrib['Include'].strip())
            if tag=='Using' and e.attrib.get('Remove'): rem.append(e.attrib['Remove'].strip())
    if not enabled: return []
    ns=list(BASE)
    if sdk.startswith('Microsoft.NET.Sdk.Web'): ns+=WEB
    elif sdk.startswith('Microsoft.NET.Sdk.Worker'): ns+=WORKER
    ns+= [a for a in add if not a.startswith('static ') and '=' not in a]
    return [n for n in dict.fromkeys(ns) if n not in rem]
if __name__=='__main__':
    import sys
    for p in sys.argv[1:]: print(p, implicit_usings(p))
