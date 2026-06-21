// AFTER (fixed): scope the listener with `using` so it is disposed (Stop() alone does not
// dispose it). Disposed on every path -> silent.
using System.Net;
using System.Net.Sockets;

static class PortFinder
{
    static int GetRandomUnusedPort()
    {
        using TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }
}
