namespace OrderBackend;

public static class Shipping
{
    /// The carrier's tracking number for an order: a pure function of its id. It is called
    /// INSIDE the Ship region, where Own.NET admits a call only when the shared heap-effect
    /// summaries prove it harmless (OwnIR `proven_call`): it touches no entity, no token, no
    /// field and no static.
    public static int TrackingNumber(int orderId) => 1_000_000 + orderId * 7_919 % 999_983;
}
