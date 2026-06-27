// Regression (CodeRabbit): an EXPRESSION-bodied cleanup whose removeEventListener
// passes an options OBJECT must still parse — the `{` of `{capture: true}` is part
// of the call, not the cleanup block, so the listener is correctly released.
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectExprCleanup.tsx --check
// Expect ZERO findings (no false-positive leak).
import { useEffect } from "react";

export function ExprCleanup() {
  useEffect(() => {
    window.addEventListener("scroll", onScroll, { capture: true });
    return () => window.removeEventListener("scroll", onScroll, { capture: true });
  }, []);

  // a MULTI-LINE expression-bodied cleanup must not be cut at the first newline
  // after `=>` (which would leave an empty cleanup and a false leak).
  useEffect(() => {
    el.addEventListener("resize", onResize);
    return () =>
      el.removeEventListener("resize", onResize);
  }, []);

  return <div>expr cleanup</div>;
}
