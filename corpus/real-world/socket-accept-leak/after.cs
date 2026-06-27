using System.Net.Sockets;

static class SocketAcceptLeak
{
    static bool Serve(Socket listener)
    {
        using var conn = listener.Accept();   // disposed at scope exit -> clean
        return conn.Connected;
    }
}
