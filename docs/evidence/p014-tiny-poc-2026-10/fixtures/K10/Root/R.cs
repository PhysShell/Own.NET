class R { ChildNs.Src s = new ChildNs.Src();
  void M() { s.Changed += H; /*probe:k10*/ }
  void H(object o, System.EventArgs e) { } }
