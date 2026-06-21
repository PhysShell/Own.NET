// BEFORE (buggy). Reduced from ShareX @ ed2a864 —
// ShareX.HelpersLib/Helpers/WebHelpers.cs:191 (GetRandomUnusedPort), found by mining
// (docs/notes/real-world-mining.md).
//
// A TcpListener is started to grab a free port, then Stop()'d — but TcpListener is
// IDisposable (since .NET Core 3.0) and Stop() is NOT Dispose(): the listener's socket
// handle is not released, so the listener leaks. The CA2000 / CodeQL cs/local-not-disposed
// class. (The real method wraps the Start/return in a try/finally with the Stop in the
// finally; reduced here to the straight-line essence — the leak is the missing Dispose,
// not the control flow.) Uses real System.Net.Sockets types (BCL, no ref pack).
using System.Net;
using System.Net.Sockets;

static class PortFinder
{
    static int GetRandomUnusedPort()
    {
        TcpListener listener = new TcpListener(IPAddress.Loopback, 0);   // <-- OWN001: never disposed
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();   // Stop() releases the listen socket but is NOT Dispose() -> the listener leaks
        return port;
    }
}
