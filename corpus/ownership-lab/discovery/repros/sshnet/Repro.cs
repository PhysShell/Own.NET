using Renci.SshNet;
public static class Repro {
    public static void CommandLeak(SshClient client) { var command = client.CreateCommand("ls"); command.Execute(); }   // SshClientTests:97/:105, ConnectivityTests:397
    public static void ShellLeak(SshClient client, Stream i, Stream o, Stream e) { var shell = client.CreateShell(i, o, e); shell.Start(); }   // SshTests:182/:207
}
