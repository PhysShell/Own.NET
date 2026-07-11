// issue #228 — an Application-derived subscriber whose event source is an APP-SCOPED
// RESOLVER RESULT (curated: PaletteHelper.GetThemeManager), not a literal static member.
// The source is process-lived (bound to the app's own state), so the subscription
// promotes nothing — but SubscriptionSourceKind honestly tiers a call-result receiver
// "injected", which used to warn. Real-world shape: MaterialDesignInXamlToolkit
// MahMaterialDragablzMashUp App.xaml.cs:10,22 (found by the issue #201 oracle sweep).
//
// The exemption is deliberately NARROW (see the rejected `clsIsStatic` broadening in
// docs/notes/oracle-known-fps.md): subscriber must be the Application class itself,
// the resolver must be on the curated list, and the handler must be a METHOD GROUP of
// that class — three negative controls below pin each edge.
using System;

namespace OwnSamples.AppScoped
{
    // Stand-in for System.Windows.Application: IsProcessLivedApplication matches the
    // base NAME syntactically (WPF assemblies do not resolve on the Linux runner).
    public class Application { }

    public class ThemeManagerLike
    {
        public event EventHandler? ThemeChanged;
        public void Raise() => ThemeChanged?.Invoke(this, EventArgs.Empty);
    }

    // Stand-in for MaterialDesignThemes.Wpf.PaletteHelper — the curated resolver,
    // matched by (containing-type, method) = (PaletteHelper, GetThemeManager).
    public class PaletteHelper
    {
        static readonly ThemeManagerLike Manager = new();
        public ThemeManagerLike? GetThemeManager() => Manager;
    }

    // Same shape, NON-curated name -> never exempted.
    public class OtherHelper
    {
        static readonly ThemeManagerLike Manager = new();
        public ThemeManagerLike? GetOtherService() => Manager;
    }

    // POSITIVE (silent): App + curated resolver via `is`-pattern local + method-group
    // handler of the App class — the exact MaterialDesign shape.
    public class App : Application
    {
        public void OnStartup()
        {
            var helper = new PaletteHelper();
            if (helper.GetThemeManager() is { } themeManager)
                themeManager.ThemeChanged += ThemeManager_ThemeChanged;   // silent (#228)
        }

        void ThemeManager_ThemeChanged(object? sender, EventArgs e) { }
    }

    // POSITIVE (silent): the direct-invocation receiver form, no intermediate local.
    public class DirectApp : Application
    {
        public void OnStartup()
        {
            new PaletteHelper().GetThemeManager()!.ThemeChanged += OnTheme;   // silent (#228)
        }

        void OnTheme(object? sender, EventArgs e) { }
    }

    // CONTROL 1 (flagged): the SAME curated shape from a class that is NOT the
    // Application — the subscriber gate must stay `clsIsApp`, byte-for-byte.
    public class NotAnApp
    {
        public void Wire()
        {
            var helper = new PaletteHelper();
            if (helper.GetThemeManager() is { } themeManager)
                themeManager.ThemeChanged += OnTheme;                     // OWN001 warning
        }

        void OnTheme(object? sender, EventArgs e) { }
    }

    // CONTROL 2 (flagged): App + curated source, but the handler is a LAMBDA capturing
    // an enclosing local — pinning that local to app lifetime is the exact hole that
    // sank the `clsIsStatic` broadening; a lambda must never pass the handler gate.
    public class LambdaApp : Application
    {
        public void OnStartup()
        {
            var counter = new int[1];
            if (new PaletteHelper().GetThemeManager() is { } themeManager)
                themeManager.ThemeChanged += (s, e) => counter[0]++;      // OWN001 warning
        }
    }

    // CONTROL 3 (flagged): App + method-group handler, but a NON-curated resolver —
    // membership is a curated allowlist, not "any call result inside App".
    public class CuratedOnlyApp : Application
    {
        public void OnStartup()
        {
            if (new OtherHelper().GetOtherService() is { } service)
                service.ThemeChanged += OnTheme;                          // OWN001 warning
        }

        void OnTheme(object? sender, EventArgs e) { }
    }
}
