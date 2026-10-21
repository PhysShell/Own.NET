class A {
  void M(System.Windows.Controls.Button b) { b.Click += H; /*probe:k8c-wpf*/ }
  void N() { var d = new System.Windows.Forms.OpenFileDialog(); /*probe:k8c-winforms*/ }
  void H(object s, System.Windows.RoutedEventArgs e) { }
}
