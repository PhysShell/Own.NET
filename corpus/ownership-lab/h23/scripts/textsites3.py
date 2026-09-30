"""Descriptive per-site listing of the bare-identifier, production, row-family textual assignment sites over the kept frozen
clones (the 'why is textual > semantic' explanation): for each site the rhs method name, whether it collides with an ADO
convention name, the receiver expression, and a brace-depth estimate of statement nesting (depth 1 = straight-line in the
method body, > 1 = inside a nested block). Heuristic, textual only, never used as a count of anything."""
import json,re,glob,os,collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
ADO={'CreateCommand','BeginTransaction','ExecuteReader','ExecuteReaderAsync','CreateConnection','Open','OpenAsync'}
SIG=re.compile(r'^\s*(?:public|private|protected|internal|static|virtual|override|async|partial|\s)+[\w<>\[\],\.\?]+\s+\w+\s*\(')
out={}
for f in sorted(glob.glob(f'{S}/lab/sc/e2/*.e2.json')):
    d=json.load(open(f)); W=f'{E}/'+d['repo'].replace('/','__')
    if not os.path.isdir(W): continue
    tm={}
    for rel,p in d['per_project'].items():
        for t in (p.get('targets') or {}).values():
            for r in t['resolved']:
                if r['status'] in ('identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'): tm.setdefault(r['callable'].rsplit('.',1)[1],set()).add(r['callable'])
    if not tm: continue
    rx=re.compile(r'^\s*(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?!=)(?P<rhs>[^;]*?\b(?P<recv>[\w\.\(\)]*)\.(?P<m>'+'|'.join(sorted(map(re.escape,tm)))+r')\s*\()')
    sites=[]
    for src in sorted(glob.glob(f'{W}/**/*.cs',recursive=True)):
        if '/obj/' in src or '/bin/' in src or TESTP.search(os.path.relpath(src,W)): continue
        try: lines=open(src,encoding='utf-8',errors='ignore').read().splitlines()
        except Exception: continue
        for i,line in enumerate(lines,1):
            m=rx.match(line)
            if not m: continue
            lhs=m.group('lhs')
            if lhs.startswith('_') or lhs in ('var',): continue
            # nesting: brace depth from the nearest preceding method-like signature
            depth=None
            for j in range(i-1,max(0,i-400),-1):
                if SIG.match(lines[j-1]) and not lines[j-1].rstrip().endswith(';'):
                    seg='\n'.join(lines[j-1:i-1]); depth=seg.count('{')-seg.count('}'); break
            recv=m.group('recv'); mname=m.group('m')
            sites.append({'file':os.path.relpath(src,W),'line':i,'text':line.strip()[:140],'lhs':lhs,'method':mname,'row_callables_with_this_name':sorted(tm[mname])[:3],'receiver':recv,'ado_name':mname in ADO,'brace_depth_from_method':depth})
    c=collections.Counter(('ado_name' if s['ado_name'] else 'row_family_name')+'|'+('nested' if (s['brace_depth_from_method'] or 0)>1 else 'straight_or_unknown') for s in sites)
    out[d['repo']]={'count':len(sites),'classes':dict(c),'sites':sites}
    print(d['repo'],len(sites),dict(c))
json.dump(out,open(f'{S}/lab/sc/textsites3.json','w'),indent=1)
