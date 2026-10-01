"""Step 3 of the H-25 order: reclassify the try-class locals of the H-24 corrected census with the H-25 await information.
For every H-24 production local whose construct is `try` (and, for completeness, every H-24 local with an await-wrapped
write): join its writes with the H-25 records at the same (consumer, file, write line) to learn the awaited callable, its
class (trusted row / library without row / first-party / other) and the disposal context (disposed in finally / somewhere /
not in the member). Output: lab/h25/tryfinally-reclass.json and a printed table. Descriptive; no finding is claimed."""
import json, glob, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
h25={}
for f in glob.glob(f'{S}/lab/h25/census/*.h25.json'):
    d=json.load(open(f))
    for r in d['records']: h25.setdefault((d['repo'],r['file'],r['line']),r)
rows=[]
for f in sorted(glob.glob(f'{S}/lab/h24/census2/*.h24.json')):
    d=json.load(open(f)); seen=set()
    for r in d['records']:
        k=(r['file'],r['line'],r['local'])
        if k in seen or r['kind']!='production' or r['construct']!='try': continue
        seen.add(k)
        ws=[]
        for w in r['writes']:
            a=h25.get((d['repo'],r['file'],w['line']))
            ws.append({'line':w['line'],'h24_kind':w['kind'],'await':bool(a),'callable':(a or {}).get('callable') or w.get('callee'),'trusted_row':(a or {}).get('trusted_row'),'first_party':(a or {}).get('first_party'),'logical_disposable':(a or {}).get('logical_disposable'),'callable_assembly':(a or {}).get('callable_assembly')})
        anyA=[a for a in (h25.get((d['repo'],r['file'],w['line'])) for w in r['writes']) if a]
        disp_fin=any(a['disposed_in_finally'] for a in anyA) if anyA else None; disp_any=any(a['disposed_somewhere'] for a in anyA) if anyA else None
        kinds=sorted({('trusted' if x['trusted_row'] else 'first_party' if x['first_party'] else 'library_no_row' if (x['logical_disposable'] and x['await']) else x['h24_kind']) for x in ws})
        rows.append({'repo':d['repo'],'file':r['file'],'line':r['line'],'local':r['local'],'type':r['type'],'member':r['member'],'write_count':r['write_count'],'initializer':r['initializer'],'writes':ws,'write_classes':kinds,'any_await':bool(anyA),'disposed_in_finally':disp_fin,'disposed_somewhere':disp_any,
                     'ownership_reading':('clean: awaited value disposed in finally' if disp_fin else 'disposed elsewhere in the member' if disp_any else 'NOT disposed in the member (candidate for a finding, needs triage)' if anyA else 'no await write (sync kinds only)')})
c=collections.Counter(r['ownership_reading'] for r in rows); k=collections.Counter('+'.join(r['write_classes']) for r in rows)
out={'schema':'own.net/h25/tryfinally-reclass/v1','try_class_production_locals':len(rows),'ownership_readings':dict(c),'write_class_combinations':dict(k),'single_write_null_init':sum(1 for r in rows if r['write_count']==1 and r['initializer']=='none_or_null'),'rows':rows}
json.dump(out,open(f'{S}/lab/h25/tryfinally-reclass.json','w'),indent=1)
print(json.dumps({x:y for x,y in out.items() if x!='rows'},indent=1))
for r in rows: print(f"  {r['repo'].split('/')[-1]:18s} {r['file'].split('/')[-1]:34s}:{r['line']:<5d} {r['local']:14s} w={r['write_count']} init={r['initializer']:12s} {'+'.join(r['write_classes']):28s} {r['ownership_reading']}")
