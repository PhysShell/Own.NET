/**
 * @name Event subscription not released in a proven teardown context (bakeoff custom query)
 * @description A bounded QL port of Owen's landed #293/#305 extractor predicate: a `-=`
 *              credits release only when it sits in a teardown context (Dispose-family
 *              method, a handler wired to the class's own Closed/Closing/Unloaded/...
 *              event, or a method such a context transitively calls within the class)
 *              and is not guarded by a parameter of its enclosing method (with the
 *              canonical `if (disposing)` exemption and the early-return refinement).
 *              Written for the P-036 bakeoff to measure CodeQL expressiveness. NOT stock.
 * @kind problem
 * @problem.severity warning
 * @id ownnet/p036/subscription-not-released-in-teardown
 */

import csharp

Callable handlerMethod(Expr handler) {
  result = handler.(DelegateCreation).getArgument().(CallableAccess).getTarget()
  or
  result = handler.(CallableAccess).getTarget()
}

predicate selfOwnedQualifier(AddOrRemoveEventExpr e) {
  not exists(e.getLeftOperand().getQualifier())
  or
  e.getLeftOperand().getQualifier() instanceof ThisAccess
}

predicate isTeardownName(string n) {
  n = ["Dispose", "DisposeAsync", "OnClosed", "OnClosing", "OnUnloaded", "OnFormClosed", "OnFormClosing"]
}

predicate isLifecycleEventName(string n) {
  n = ["Closed", "Closing", "Unloaded", "FormClosed", "FormClosing", "Disposed"]
}

/** Teardown roots of `cls`: Dispose-family methods and handlers wired to the class's own lifecycle events. */
Callable teardownRoot(RefType cls) {
  result.getDeclaringType() = cls and
  result instanceof Method and
  isTeardownName(result.getName())
  or
  exists(AddEventExpr wire |
    wire.getEnclosingCallable().getDeclaringType() = cls and
    selfOwnedQualifier(wire) and
    isLifecycleEventName(wire.getTarget().getName()) and
    (
      result = handlerMethod(wire.getRightOperand()) and result.getDeclaringType() = cls
      or
      result = wire.getRightOperand().(LambdaExpr)
    )
  )
}

/** Teardown contexts: roots plus what they transitively call inside the class (never a destructor). */
Callable teardownContext(RefType cls) {
  result = teardownRoot(cls)
  or
  exists(Callable c | c = teardownContext(cls) and c.calls(result) |
    result.getDeclaringType() = cls or result instanceof LocalFunction
  )
}

Expr guardCondition(Element e) {
  result = e.(IfStmt).getCondition() or
  result = e.(ConditionalExpr).getCondition() or
  result = e.(SwitchStmt).getExpr() or
  result = e.(WhileStmt).getCondition() or
  result = e.(ForStmt).getCondition()
}

predicate canonicalDisposingParam(Parameter p) {
  p.getType() instanceof BoolType and
  p.getCallable().getName() = "Dispose" and
  p.getCallable().getNumberOfParameters() = 1
}

predicate negatedUse(ParameterAccess pa) {
  pa.getParent() instanceof LogicalNotExpr or
  exists(EQExpr eq | eq.getAnOperand() = pa and eq.getAnOperand().(BoolLiteral).getBoolValue() = false) or
  exists(NEExpr ne | ne.getAnOperand() = pa and ne.getAnOperand().(BoolLiteral).getBoolValue() = true)
}

/** A `-=` under an enclosing condition that names a parameter of its callable (the #278 rule 2 guard). */
predicate paramGuarded(RemoveEventExpr rem) {
  exists(Element anc, ParameterAccess pa |
    anc = rem.getParent+() and
    pa = guardCondition(anc).getAChildExpr*() and
    pa.getTarget().getCallable() = rem.getEnclosingCallable()
  |
    not (
      canonicalDisposingParam(pa.getTarget()) and
      not negatedUse(pa) and
      not anc.(IfStmt).getElse().getAChild*() = rem
    )
  )
  or
  // #305 attack A: a parameter-guarded early return lexically before the site
  exists(ReturnStmt ret, Element anc, ParameterAccess pa |
    ret.getEnclosingCallable() = rem.getEnclosingCallable() and
    ret.getLocation().getStartLine() < rem.getLocation().getStartLine() and
    anc = ret.getParent+() and
    pa = guardCondition(anc).getAChildExpr*() and
    pa.getTarget().getCallable() = rem.getEnclosingCallable() and
    not (canonicalDisposingParam(pa.getTarget()) and negatedUse(pa))
  )
}

predicate releasedInTeardown(AddEventExpr add, RefType cls) {
  exists(RemoveEventExpr rem |
    rem.getTarget() = add.getTarget() and
    handlerMethod(rem.getRightOperand()) = handlerMethod(add.getRightOperand()) and
    rem.getEnclosingCallable() = teardownContext(cls) and
    not rem.getEnclosingCallable() instanceof Destructor and
    not paramGuarded(rem)
  )
}

from AddEventExpr add, Event ev, RefType cls
where
  ev = add.getTarget() and
  cls = add.getEnclosingCallable().getDeclaringType() and
  not selfOwnedQualifier(add) and
  not releasedInTeardown(add, cls)
select add,
  "Event '" + ev.getName() + "' subscribed here has no unguarded '-=' in a proven teardown context of '" + cls.getName() + "'."
