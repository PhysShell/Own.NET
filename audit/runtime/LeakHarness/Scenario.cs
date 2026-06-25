using System.Collections.Generic;
using System.IO;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConvention;

namespace OwnNet.Audit.Runtime
{
    /// <summary>
    /// POCO mirror of a leak-harness scenario YAML (see audit/runtime/scenarios/).
    /// The scenario is the part an AI drafts (which screen, how to open/close it);
    /// the asserts are deterministic — retained instance growth vs. a threshold.
    /// </summary>
    public sealed class Scenario
    {
        public string Name { get; set; } = "";
        public string App { get; set; } = "";          // path to the target .exe
        public int Iterations { get; set; } = 10;
        public double Threshold { get; set; } = 0.5;    // allowed retained growth / iteration
        public List<Step> Steps { get; set; } = new();
        public List<Suspect> Suspects { get; set; } = new();

        public static Scenario Load(string path)
        {
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(HyphenatedNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();
            return deserializer.Deserialize<Scenario>(File.ReadAllText(path));
        }
    }

    /// <summary>One UI action in a scenario cycle (open a screen, click, close, wait).</summary>
    public sealed class Step
    {
        public string Action { get; set; } = "";   // open | click | close | wait
        public string Target { get; set; } = "";   // automation id / name of the control
        public int Ms { get; set; }                 // dwell time for `wait`
    }

    /// <summary>
    /// A type whose retained-instance count the harness watches across cycles, plus
    /// the source location and audit rule it maps to so a confirmed leak correlates
    /// with the matching static finding (Plan.md §3.5).
    /// </summary>
    public sealed class Suspect
    {
        public string Type { get; set; } = "";                       // fully-qualified CLR type
        public string Rule { get; set; } = "RUNTIME-LEAK-SUBSCRIPTION";
        public string Location { get; set; } = "";                   // source file, for correlation
        public int Line { get; set; }                                // 0 = file-level
    }
}
