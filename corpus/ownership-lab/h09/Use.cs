using Lib;
public static class Use
{
    public static void Leak()
    {
        var r = Factory.Make();     // fresh under LibA; cached under LibB
        r.ToString();
    }
}
