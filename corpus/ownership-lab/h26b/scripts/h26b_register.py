"""Append the H-26B gate event and the H-27 step-3 value event to the append-only hypothesis register, from the census
record (paper-eval/h26/h26b-census-v1.json). Never edits or removes entries."""
import json, datetime
P='/home/user/Own.NET-paperwork'; REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'
c=json.load(open(f'{P}/paper-eval/h26/h26b-census-v1.json')); t=c['totals']; g=c['gate']; v=c['h27_step3_value']; lf=t['lease_families_frozen_pair']; sp=t['Q2b_primary_split_by_receiver_typing']
bt=[x for x in sp if x.startswith('base_typed_receiver')][0]; st=[x for x in sp if x.startswith('same_type_receiver')][0]
r=json.load(open(REG)); now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
have={(e.get('hypothesis'),e.get('event')) for e in r['log']}
ev=[{'at_utc':now,'hypothesis':'H-26B','event':'CENSUS_GATE_EVALUATED',
 'summary':(f"{t['consumers']} consumers / {t['units']} production units (corrected environment; the 2 units whose first run failed were re-run with the cross-file model fix, {t['extractor_failures_final']} failures remain): "
            f"{t['sites_raw']} raw / {t['sites_unique']} TFM-collapsed disposable-returning library call sites, {t['production_unique']} production; "
            f"Q2b (framework-declared member) production sites {t['Q2b_production']}, frozen primary (CONCRETE_LOCAL_CONSTRUCTION or CONCRETE_FIELD) {g['primary']} = {g['share']} of Q2b; "
            f"descriptive: wider construction provenance {t['Q2b_construction_provenance_wider']}, static-type-concrete receivers {t['Q2b_static_type_concrete']} ({t['Q2b_static_type_concrete_share']}); "
            f"of the primary only {sp[bt]} sites have a receiver whose static type differs from the concrete type (all IEnumerable<T>.GetEnumerator), {sp[st]} already carry the concrete class as the static type, so the provenance question is empty on this population; "
            f"rows on the concrete override for primary sites: {t['Q2b_primary_with_row_on_override']}; Q2b provenance distribution {json.dumps(t['Q2b_provenance_distribution'],sort_keys=True)}"),
 'decision':g['decision']+' (frozen rule; the wider sets would not change it; the by-assembly Q2b definition over-counts the primary in favour of LEVER and it still fails)','record':'paper-eval/h26/h26b-census-v1.json'},
 {'at_utc':now,'hypothesis':'H-27','event':'VALUE_STEP3_COUNTED',
 'summary':(f"owned-handle (lease) frozen pair ExecuteReaderAsync / BeginTransactionAsync (concrete + base-typed) over the same population: {lf['production_sites']} production sites, "
            f"{lf['using_declaration']} using declarations, {lf['transferred_returned_or_stored']} transferred (returned or stored), {lf['sink_not_local']} with a non-local sink; "
            f"non-using non-transferred local sites = {v['count']} ({v['count_wide_incl_sync']} with the synchronous twins); of them {lf['value_passed_as_argument_somewhere']} pass the handle as an argument somewhere; "
            f"by callable {json.dumps(lf['value_by_callable'],sort_keys=True)}; by class {json.dumps(lf['value_by_class'],sort_keys=True)}; by consumer {json.dumps(lf['value_by_consumer'],sort_keys=True)}; by provenance {json.dumps(lf['value_by_provenance'],sort_keys=True)}"),
 'decision':v['decision']+'; step 4 opens with its OWN prereg (cheapest falsifier first: handle release x receiver lifetime census of the value sites; no lowering, no vocabulary change in that prereg)','record':'paper-eval/h26/h26b-census-v1.json'}]
new=[e for e in ev if (e['hypothesis'],e['event']) not in have]
r['log'].extend(new); json.dump(r,open(REG,'w'),indent=1); print('register +%d events'%len(new))
for e in new: print(e['hypothesis'],e['event'],'->',e['decision'][:60])
