"""Stage E two-stage freeze, part 2: the consumer set (every censused consumer at its exact revision), the trusted
opportunities, and the trusted row identities per consumer/project/TFM, written BEFORE any OFF/ON verdict comparison.
No consumer is removed for producing no opportunity (they stay in the frozen set with zero)."""
import json, glob, os, datetime, hashlib, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'
now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
TR={'identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'}
cons=[]
for f in sorted(glob.glob(f'{S}/lab/sc/e2/*.e2.json')):
    d=json.load(open(f)); rows=collections.OrderedDict()
    for rel,p in d['per_project'].items():
        for tfm,t in (p.get('targets') or {}).items():
            for r in t['resolved']:
                if r['status'] in TR: rows.setdefault(f'{rel}|{tfm}',[]).append({k:r.get(k) for k in ('package','version','asset','runtime_asset','callable','status','source')})
    cons.append({'repo':d['repo'],'sha':d['sha'],'production_projects':d['production_projects'],'restored_ok':d['restored_ok'],'trusted_opportunities':d['units_trusted'],'trusted_opportunity_count':d['unit_count_trusted'],'unverified_count':d['unit_count_unverified'],'trusted_rows_per_project_tfm':{k:len(v) for k,v in rows.items()},'trusted_rows':rows})
floor=json.load(open(f'{S}/lab/sc/e2-floor.json'))['floor']
out={'schema':'own.net/semantic-coverage/e2-freeze/v1','frozen_at_utc':now,'consumers':cons,'floor_at_freeze':floor,'rule':'frozen before OFF/ON; OFF/ON runs on every consumer with >= 1 trusted opportunity; consumers with zero stay listed and are never replaced'}
open(f'{P}/paper-eval/semantic-coverage/e2-freeze-v1.json','w').write(json.dumps(out,indent=1))
h=hashlib.sha256(open(f'{P}/paper-eval/semantic-coverage/e2-freeze-v1.json','rb').read()).hexdigest(); print('FREEZE_WRITTEN',len(cons),'consumers sha256',h)
