using System.Net.Sockets;

// A Socket returned by TcpListener.AcceptSocket() is a fresh owned IDisposable the caller must
// dispose; dropping it leaks the accepted connection. The listener is a borrowed parameter, so the
// ONLY leak is `sock`.
static class AcceptSocketLeak
{
    static bool Serve(TcpListener listener)
    {
        var sock = listener.AcceptSocket();   // fresh owned Socket -> OWN001 (never disposed)
        return sock.Connected;                 // used, but never disposed -> leak
    }
}
