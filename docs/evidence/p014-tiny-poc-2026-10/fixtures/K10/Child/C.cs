namespace ChildNs { public class Src { public event System.EventHandler Changed; public void R() => Changed?.Invoke(this, System.EventArgs.Empty); } }
