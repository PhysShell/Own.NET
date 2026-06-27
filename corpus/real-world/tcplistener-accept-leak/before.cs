using System.Net.Sockets;

// A TcpClient returned by TcpListener.AcceptTcpClient() is a fresh owned IDisposable the caller
// must dispose; dropping it leaks the accepted connection (the socket handle is held until
// finalization) — a classic accept-loop server leak. The listener is a borrowed parameter, so the
// ONLY leak is `client`.
static class AcceptLeak
{
    static bool Serve(TcpListener listener)
    {
        var client = listener.AcceptTcpClient();   // fresh owned TcpClient -> OWN001 (never disposed)
        return client.Connected;                    // used, but never disposed -> leak
    }
}
