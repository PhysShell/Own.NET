// netstandard2.0 lacks the marker type C# needs for `record` and `init`.
namespace System.Runtime.CompilerServices
{
    internal static class IsExternalInit
    {
    }
}
