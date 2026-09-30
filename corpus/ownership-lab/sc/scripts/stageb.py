"""Stage B analysis: rows from whole-source derivation joined with the factory-surface census -> weighted semantic
coverage (all / used surface / unweighted) per library and pooled; the non-provable remainder with its call counts."""
import json, os, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
LIBS=['SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp']
cen=json.load(open(f'{S}/lab/sc/surface-census.json'))['rows']; cnt={r['callable']:r for r in cen}
out={}; pooled=collections.Counter()
for pid in LIBS:
    L=f'{D}/libs/{pid}'; w=json.load(open(f'{L}/rows-whole.json')); api=json.load(open(f'{L}/api.json'))
    old={e['callable'] for e in json.load(open(f'{L}/rows-applied.json'))['entries']} if os.path.exists(f'{L}/rows-applied.json') else set()
    surface=sorted({f['callable'] for f in api['factories']}); rows={r['callable'] for r in w['rows'] if r['effect']=='return_fresh_owned'}
    def m(c): r=cnt.get(c); return (r['line_matches'] if r else 0)
    tot=sum(m(c) for c in surface); cov=sum(m(c) for c in surface if c in rows)
    used=[c for c in surface if m(c)>=10]; utot=sum(m(c) for c in used); ucov=sum(m(c) for c in used if c in rows)
    rem=sorted([c for c in used if c not in rows], key=lambda c:-m(c))
    out[pid]={'files':w['files'],'whole_set_ok':w['whole_set_ok'],'seconds':w['seconds'],'surface_callables':len(surface),'rows_whole':len(rows),'rows_subset_before':len(old),'rows_new_vs_subset':sorted(rows-old),'rows_lost_vs_subset':sorted(old-rows),
        'weighted_coverage_all':round(cov/tot,3) if tot else None,'weighted_coverage_used':round(ucov/utot,3) if utot else None,'unweighted_coverage':round(len(rows)/len(surface),3) if surface else None,
        'used_callables':len(used),'used_with_row':sum(1 for c in used if c in rows),'total_matches':tot,'covered_matches':cov,'non_provable_used_top':[(c,m(c)) for c in rem[:15]],'non_provable_used_count':len(rem)}
    pooled['tot']+=tot; pooled['cov']+=cov; pooled['utot']+=utot; pooled['ucov']+=ucov; pooled['surf']+=len(surface); pooled['rows']+=len(rows); pooled['used']+=len(used); pooled['usedrow']+=sum(1 for c in used if c in rows); pooled['rem']+=len(rem)
out['_pooled']={'weighted_coverage_all':round(pooled['cov']/pooled['tot'],3),'weighted_coverage_used':round(pooled['ucov']/pooled['utot'],3),'unweighted_coverage':round(pooled['rows']/pooled['surf'],3),'surface':pooled['surf'],'rows':pooled['rows'],'used':pooled['used'],'used_with_row':pooled['usedrow'],'non_provable_used':pooled['rem']}
json.dump(out,open(f'{S}/lab/sc/stageb-results.json','w'),indent=1)
for pid in LIBS: r=out[pid]; print(f"{pid:22s} files {r['files']:4d} surface {r['surface_callables']:4d} rows {r['rows_whole']:3d} (subset {r['rows_subset_before']:3d}) cov_all {r['weighted_coverage_all']} cov_used {r['weighted_coverage_used']} unw {r['unweighted_coverage']} used {r['used_callables']} used_with_row {r['used_with_row']} remainder {r['non_provable_used_count']}")
print('POOLED', out['_pooled'])
