using System.Collections.Immutable;
class A { int M() { var b = ImmutableArray.CreateBuilder<int>(); b.Add(1); /*probe:k8a*/ return b.Count; } }
