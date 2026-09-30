"""H-16 symbolic probe: encode ONE conditional-release obligation family in Z3 and compare with the
P-037-X selection / the labels. Records the encoding cost (lines) per site. Not an analysis."""
import z3, json
out = {}
def check_valid(name, prop, *vars_):
    s = z3.Solver(); s.add(z3.Not(prop)); r = s.check()
    out[name] = {"valid": r == z3.unsat, "counterexample": (str(s.model()) if r == z3.sat else None)}
# --- case 4 helper VerifyPersistedKey(key, ..., bool disposeKey): releases key iff disposeKey (definite)
disposeKey = z3.Bool('disposeKey')
def callee_releases(flag): return flag                       # the callee's summary Split(disposeKey)[must,no]
# site S1 (helper :59) and S2 (:378): disposeKey:false, caller's finally runs cngKey.Delete() on all paths
rel_callee = callee_releases(z3.BoolVal(False)); rel_caller = z3.BoolVal(True)
check_valid("case4_S1_S2_no_leak", z3.Or(rel_callee, rel_caller))
check_valid("case4_S1_S2_no_double", z3.Not(z3.And(rel_callee, rel_caller)))
# site S3 (AesCngTests :163): disposeKey:true; the caller's finally deletes a DIFFERENT handle (openedKey)
rel_callee3 = callee_releases(z3.BoolVal(True)); rel_caller3 = z3.BoolVal(False)   # cngKey itself: nothing in the caller
check_valid("case4_S3_no_leak", z3.Or(rel_callee3, rel_caller3))
check_valid("case4_S3_no_double", z3.Not(z3.And(rel_callee3, rel_caller3)))
# the same site with the flag UNKNOWN (a non-literal argument): neither property is valid -> the selection must say unknown
flag = z3.Bool('flag'); relc = callee_releases(flag); relr = z3.BoolVal(False)
check_valid("case4_unknown_flag_no_leak", z3.Or(relc, relr))     # expected: NOT valid (counterexample flag=false)
# laundered twin (audit C): bool s = disposeKey; if (s) key.Dispose();  -> the encoder must carry s == disposeKey
s_ = z3.Bool('s'); launder = (s_ == disposeKey)
check_valid("laundered_twin_equivalent", z3.Implies(launder, callee_releases(s_) == callee_releases(disposeKey)))
# --- multipleSinks: if (count > 10) cw.Dispose(); else con.Dispose();  with cw an alias of con
count = z3.Int('count'); rel_cw = count > 10; rel_con = z3.Not(count > 10)
check_valid("multipleSinks_exactly_one_release", z3.And(z3.Or(rel_cw, rel_con), z3.Not(z3.And(rel_cw, rel_con))))
# --- the SMT-only shape: two ifs with COMPLEMENTARY numeric guards releasing one handle
#     if (count > 10) x.Dispose();  if (count <= 10) x.Dispose();   -> a path-insensitive reading sees a
#     'neither' path (leak) and a 'both' path (double); feasibility decides both are infeasible
rel1 = count > 10; rel2 = count <= 10
check_valid("complementary_guards_no_leak", z3.Or(rel1, rel2))
check_valid("complementary_guards_no_double", z3.Not(z3.And(rel1, rel2)))
# --- a NON-complementary twin (a real bug): if (count > 10) x.Dispose();  if (count < 10) x.Dispose();  (count == 10 leaks)
rel1b = count > 10; rel2b = count < 10
check_valid("gap_guards_no_leak", z3.Or(rel1b, rel2b))          # expected: NOT valid, counterexample count = 10
json.dump(out, open('/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad/lab/h16/z3-results.json','w'), indent=1)
print(json.dumps(out, indent=1))
