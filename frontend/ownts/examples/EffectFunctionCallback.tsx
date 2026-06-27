// Transpiled-ES5 shape: `useEffect(function () { … return function () { … } }, …)`.
// Proves the parser handles `function` callbacks AND `return function` cleanups —
// a correctly-matched ES5 cleanup stays silent, while a real capture-flag mismatch
// (the react-scroll-to-bottom@4.2.0 bug) is caught for the right reason. Run:
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectFunctionCallback.tsx --check
// Expect exactly ONE OWN001 (the capture-mismatched focus listener).
import { useEffect } from "react";

export function Composer({ target }: { target: HTMLElement }) {
  // Correctly cleaned ES5 effect: same handler, same (default) capture -> silent.
  useEffect(function () {
    window.addEventListener("resize", onResize);
    return function () {
      window.removeEventListener("resize", onResize);
    };
  }, []);

  // Real leak: added with { capture: true } but removed with the default (false)
  // capture, so the listener is never actually removed (react-scroll-to-bottom bug).
  useEffect(function () {
    target.addEventListener("focus", handleFocus, { capture: true, passive: true });
    return function () {
      return target.removeEventListener("focus", handleFocus);
    };
  }, [target]);

  return <div>composer</div>;
}
