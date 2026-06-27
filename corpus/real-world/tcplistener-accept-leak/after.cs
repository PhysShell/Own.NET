using System.Net.Sockets;

// FIX: own the accepted client for the scope with `using`, so it is disposed on every exit path.
static class AcceptLeak
{
    static bool Serve(TcpListener listener)
    {
        using var client = listener.AcceptTcpClient();   // disposed at scope exit -> clean
        return client.Connected;
    }
}
