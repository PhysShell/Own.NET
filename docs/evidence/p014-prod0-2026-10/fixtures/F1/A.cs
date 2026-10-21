class A {
  void M() {
#if NET8_0
    System.Console.WriteLine("SDK branch");
#else
    System.Console.WriteLine("branch measured without defines");
#endif
  }
}
