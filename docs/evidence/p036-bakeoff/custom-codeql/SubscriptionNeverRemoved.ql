/**
 * @name Event subscription never removed (naive, bakeoff custom query)
 * @description A `+=` on an event of another object whose handler is never `-=`'d
 *              anywhere in the subscribing class. This is the PRE-#278 Owen rule
 *              ("any matching -= in the class releases"), written in QL for the
 *              P-036 bakeoff to measure CodeQL expressiveness. It is NOT stock.
 * @kind problem
 * @problem.severity warning
 * @id ownnet/p036/subscription-never-removed
 */

import csharp

/** The method a handler expression denotes (method group, possibly wrapped in `new Handler(M)`). */
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

from AddEventExpr add, Event ev, RefType cls
where
  ev = add.getTarget() and
  cls = add.getEnclosingCallable().getDeclaringType() and
  not selfOwnedQualifier(add) and
  not exists(RemoveEventExpr rem |
    rem.getTarget() = ev and
    rem.getEnclosingCallable().getDeclaringType() = cls and
    handlerMethod(rem.getRightOperand()) = handlerMethod(add.getRightOperand())
  )
select add,
  "Event '" + ev.getName() + "' subscribed here is never unsubscribed in '" + cls.getName() + "'."
