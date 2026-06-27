using System.Net.Sockets;

static class AcceptSocketLeak
{
    static bool Serve(TcpListener listener)
    {
        using var sock = listener.AcceptSocket();   // disposed at scope exit -> clean
        return sock.Connected;
    }
}
