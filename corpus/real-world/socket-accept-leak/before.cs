using System.Net.Sockets;

// A Socket returned by Socket.Accept() is a fresh owned IDisposable the caller must dispose;
// dropping it leaks the accepted connection (handle held until finalization). The listening
// socket is a borrowed parameter, so the ONLY leak is `conn`.
static class SocketAcceptLeak
{
    static bool Serve(Socket listener)
    {
        var conn = listener.Accept();   // fresh owned Socket -> OWN001 (never disposed)
        return conn.Connected;           // used, but never disposed -> leak
    }
}
