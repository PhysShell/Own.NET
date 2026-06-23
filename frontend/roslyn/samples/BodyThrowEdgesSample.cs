using System.IO;

namespace Own.Samples;

// P-016 throw tier — the OPT-IN `--body-throw-edges` firehose: body-level "any call may throw"
// dispose-not-called-on-throw, matching CodeQL's cs/dispose-not-called-on-throw on the no-try
// slice. OFF by default (it is CA2000-noisy — it flags even harmless MemoryStream dispose-on-
// throw); the oracle enables it to measure full recall without shifting the shipped low-FP
// default. The leak verdict below holds ONLY under --body-throw-edges; by default this file is
// silent. Kept in its own file so CI can run it in BOTH modes — running it against the default
// FlowLocalsSample would flood every acquire/use/dispose sample under the flag.
public class BodyThrowEdgesSample
{
    // acquire; a may-throw call; dispose — no try. Under --body-throw-edges the WriteByte call is
    // a throw point that skips the Dispose, so `mtbd` leaks on that exceptional path -> OWN001
    // "may not be disposed on every path". Default (flag off): SILENT — a body-level call is not
    // treated as a leak point (the shipped posture stays below CA2000).
    public void MayThrowLeaks()
    {
        var mtbd = new MemoryStream();
        mtbd.WriteByte(1);
        mtbd.Dispose();
    }

    // control: NOTHING between acquire and dispose can throw (adjacent), so even under the flag
    // there is no throw point to skip the Dispose -> SILENT in both modes. Proves the edge needs
    // an intervening may-throw statement — the flag is not "flag any undisposed-looking local".
    public void AdjacentDisposeClean()
    {
        var adc = new MemoryStream();
        adc.Dispose();
    }
}
