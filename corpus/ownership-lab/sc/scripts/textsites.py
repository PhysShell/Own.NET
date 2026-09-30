"""Post-scan textual recount over the kept E3 clones (frozen revisions): for each consumer, the call-site SHAPES of the
trusted-row method names in production and test projects: declaration (oracle applies), using-declaration (disposed by
construction, no opportunity), assignment to an existing local/field (oracle does not apply: H-23). Textual, not exposure."""
import json, glob, os, re, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
out={}
for f in sorted(glob.glob(f'{S}/lab/sc/e2/*.e2.json')):
    d=json.load(open(f)); W=f'{E}/'+d['repo'].replace('/','__')
    if not os.path.isdir(W): continue
    tm=set()
    for rel,p in d['per_project'].items():
        for t in (p.get('targets') or {}).values():
            for r in t['resolved']:
                if r['status'] in ('identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'): tm.add(r['callable'].rsplit('.',1)[1])
    if not tm: continue
    rx=re.compile(r'^\s*(?P<using>using\s*\(?\s*)?(?:(?P<decl>(?:var|[A-Za-z_][\w<>\[\],\.?]*\??)\s+[A-Za-z_]\w*)|(?P<asg>[A-Za-z_][\w\.]*))\s*=\s*(?!=)[^;]*?\.(?:'+'|'.join(sorted(map(re.escape,tm)))+r')\s*\(')
    c=collections.Counter()
    for src in glob.glob(f'{W}/**/*.cs',recursive=True):
        if '/obj/' in src or '/bin/' in src: continue
        kind='test' if TESTP.search(os.path.relpath(src,W)) else 'production'
        try:
            for line in open(src,encoding='utf-8',errors='ignore'):
                mm=rx.match(line)
                if mm: c[(kind,'using' if mm.group('using') else 'declaration' if mm.group('decl') else 'assignment')]+=1
        except Exception: pass
    out[d['repo']]={'sha':d['sha'],'trusted_method_names':sorted(tm),'sites':{f'{k[0]}:{k[1]}':v for k,v in sorted(c.items())}}
json.dump(out,open(f'{S}/lab/sc/textsites.json','w'),indent=1)
for r,v in out.items(): print(r,v['sites'])
