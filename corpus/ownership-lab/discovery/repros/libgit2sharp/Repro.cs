using LibGit2Sharp;
public static class Repro {
    public static void RemoteLeak(string path) { using (var repo = new Repository(path)) { var remote = repo.Network.Remotes.Add("one", "http://example/up"); var n = remote.RefSpecs.Count(); } }   // RemoteFixture:219/:230
}
