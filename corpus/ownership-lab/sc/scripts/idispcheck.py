"""Overlap check for one consumer project: build it with IDisposableAnalyzers 4.0.8 (offline NuGet cache) and the SDK's
NetAnalyzers (CA2000) through a temporary Directory.Build.props placed next to the project; the props imports the
repository's own Directory.Build.props above it (so nothing of the build is lost) and uses VersionOverride under Central
Package Management. Collect IDISP*/CA2000/CA2213/CA1816 warnings with file:line. usage: idispcheck.py <csproj> <out.json>"""
import sys, os, subprocess, re, json
proj, out = sys.argv[1], sys.argv[2]; d=os.path.dirname(os.path.abspath(proj)); props=os.path.join(d,'Directory.Build.props'); had=os.path.exists(props)
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1'}
def above(name, start):
    p=os.path.dirname(start)
    while True:
        c=os.path.join(p,name)
        if os.path.exists(c): return c
        if p==os.path.dirname(p) or p=='/': return None
        p=os.path.dirname(p)
bak=open(props).read() if had else None
cpm=above('Directory.Packages.props', d) is not None
parent=None if had else above('Directory.Build.props', d)
imp=f'<Import Project="{parent}" />' if parent else ''
inner=(re.search(r'<Project[^>]*>(.*)</Project>',bak,re.S).group(1) if had else '')
ref='<PackageReference Include="IDisposableAnalyzers" VersionOverride="4.0.8" PrivateAssets="all" />' if cpm else '<PackageReference Include="IDisposableAnalyzers" Version="4.0.8" PrivateAssets="all" />'
open(props,'w').write('<Project>'+imp+inner+'<PropertyGroup><EnableNETAnalyzers>true</EnableNETAnalyzers><AnalysisLevel>latest</AnalysisLevel><AnalysisMode>All</AnalysisMode><TreatWarningsAsErrors>false</TreatWarningsAsErrors><WarningsAsErrors></WarningsAsErrors><RunAnalyzersDuringBuild>true</RunAnalyzersDuringBuild><CentralPackageVersionOverrideEnabled>true</CentralPackageVersionOverrideEnabled></PropertyGroup><ItemGroup>'+ref+'</ItemGroup></Project>')
try:
    r=subprocess.run(['dotnet','build',proj,'-nologo','-c','Release','--no-incremental','-p:WarningLevel=4','-p:ContinuousIntegrationBuild=false'],capture_output=True,text=True,env=env,timeout=1800)
    txt=r.stdout+r.stderr
finally:
    if had: open(props,'w').write(bak)
    else: os.remove(props)
W=re.compile(r'^(.*?)\((\d+),(\d+)\): warning (IDISP\d+|CA2000|CA2213|CA1816): (.*?) \[',re.M)
warns=sorted({(m.group(1),int(m.group(2)),m.group(4),m.group(5)[:120]) for m in W.finditer(txt)})
json.dump({'project':proj,'cpm':cpm,'parent_props':parent,'build_rc':r.returncode,'warnings':warns,'tail':txt[-800:]},open(out,'w'),indent=1)
print('IDISP_DONE',proj,'rc',r.returncode,'warnings',len(warns))
