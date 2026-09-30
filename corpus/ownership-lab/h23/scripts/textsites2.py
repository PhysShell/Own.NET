"""Descriptive breakdown of the textual assignment-shaped sites over the kept scan clones: the assignment TARGET class
(member: dotted or underscore-prefixed; bare: a plain identifier, local or field), object-initializer members, compound
assignments, and whether the method name also belongs to a convention-covered ADO callable (name collision). Textual only."""
import json,re,glob,os,collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
ADO={'CreateCommand','BeginTransaction','ExecuteReader','ExecuteReaderAsync','CreateConnection','Open','OpenAsync'}
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
    rx=re.compile(r'^\s*(?P<lhs>[A-Za-z_][\w\.\[\]]*)\s*(?P<op>\?\?=|\+=|=)\s*(?!=)(?P<rhs>[^;]*?\b(?P<recv>[\w\.]*)\.(?P<m>'+'|'.join(sorted(map(re.escape,tm)))+r')\s*\()')
    c=collections.Counter(); ex=collections.defaultdict(list)
    for src in glob.glob(f'{W}/**/*.cs',recursive=True):
        if '/obj/' in src or '/bin/' in src: continue
        kind='test' if TESTP.search(os.path.relpath(src,W)) else 'production'
        try: lines=open(src,encoding='utf-8',errors='ignore').read().splitlines()
        except Exception: continue
        for i,line in enumerate(lines,1):
            m=rx.match(line)
            if not m or line.strip().startswith(('var ','using ')) or re.match(r'^\s*[A-Z][\w<>\[\],\.?]*\s+\w+\s*=',line): continue
            lhs=m.group('lhs'); mname=m.group('m')
            if m.group('op')!='=': tgt='compound'
            elif line.rstrip().endswith(',') or (i<len(lines) and not line.rstrip().endswith(';')): tgt='initializer_or_multiline'
            elif '.' in lhs or lhs.startswith('_') or '[' in lhs: tgt='member_or_indexer'
            else: tgt='bare_identifier'
            coll='ado_name_collision' if mname in ADO and not re.search(r'Npgsql\w*\.|DataSource',m.group('rhs')) else 'row_family'
            c[(kind,tgt,coll)]+=1
            if len(ex[(kind,tgt,coll)])<2: ex[(kind,tgt,coll)].append(f'{os.path.relpath(src,W)}:{i}: {line.strip()[:100]}')
    out[d['repo']]={'counts':{'|'.join(k):v for k,v in c.items()},'examples':{'|'.join(k):v for k,v in ex.items()}}
    print(d['repo'].split('/')[-1], {'|'.join(k):v for k,v in sorted(c.items())})
json.dump(out,open(f'{S}/lab/sc/textsites2.json','w'),indent=1)
