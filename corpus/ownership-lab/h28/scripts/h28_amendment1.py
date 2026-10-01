"""H-28 prereg amendment 1 (append-only, frozen before the final aggregation): the harness cross-check is one-directional, pool
rentals leave the population. Register event."""
import json, datetime
P='/home/user/Own.NET-paperwork'; now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
am={'schema':'own.net/h28/amendment/v1','frozen_at_utc':now,'amends':'paper-eval/h28/h28-prereg-v1.json (f6db975), the harness clause and the population',
 'trigger':'the first consumer of the census (NpgsqlRest, 76 raw argument passes) showed 10 cross-check mismatches, ALL of the kind "exempt occurrence, local absent from the unit facts" (EXEMPT_POOL x6 on one pool buffer, EXEMPT_CANONICAL_FORWARD x4 on one local) and none of the kind "ESCAPE_UNTRACKED occurrence, local present"; the seam records ARGUMENT occurrences only, while the lowering also untracks a local for a return, an assignment out, a closure capture or a pool buffer passed to an escaping constructor, so "exempt => present" cannot be checked from the seam records alone',
 'changes':[
  'harness cross-check made one-directional and exact: every ESCAPE_UNTRACKED occurrence must name a local that is ABSENT from its method\'s ops in the unit facts (the recorded "untracked" is real); a mismatch in that direction = EXPERIMENT_INVALID; "exempt occurrence, local absent" is reported descriptively (count and examples) as "escaped by another route", never as a mismatch',
  'pool rentals (acquire_shape = pool: ArrayPool / MemoryPool buffers) leave the H-28 population: their argument convention is the renter-returns policy of BufferPolicies.md, not an IDisposable ownership transfer, and the seam\'s EXEMPT_POOL label does not reproduce the pool-to-escaping-constructor rule; they are counted descriptively only',
  'the primary, the secondary classes, the manual read and the gate are unchanged; all primary sites are ESCAPE_UNTRACKED, so the exact direction of the cross-check covers every counted site'],
 'before':'any population aggregate beyond the first consumer; no manual read done'}
json.dump(am,open(f'{P}/paper-eval/h28/h28-amendment-1.json','w'),indent=1)
REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'; r=json.load(open(REG))
e={'at_utc':now,'hypothesis':'H-28','event':'PREREG_AMENDMENT_1_FROZEN','summary':'harness cross-check made one-directional and exact (ESCAPE_UNTRACKED => absent from the facts; exempt-but-absent reported as escaped by another route), pool rentals leave the population; triggered by 10 exempt-but-absent records on the first consumer, 0 in the exact direction; primary, classes, manual read and gate unchanged','decision':'OPEN','record':'paper-eval/h28/h28-amendment-1.json'}
if not any(x.get('hypothesis')=='H-28' and x.get('event')=='PREREG_AMENDMENT_1_FROZEN' for x in r['log']): r['log'].append(e); json.dump(r,open(REG,'w'),indent=1); print('register +1')
