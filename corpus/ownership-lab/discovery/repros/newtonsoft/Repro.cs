using Newtonsoft.Json; using Newtonsoft.Json.Linq;
public static class Repro {
    public static void CreateReaderLeak() { var o = JObject.Parse("{\"a\":1}"); JsonReader reader = o.CreateReader(); reader.Read(); }   // JTokenReaderTest:56 etc. (BENIGN: dispose-optional)
}
