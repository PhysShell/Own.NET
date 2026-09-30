using MQTTnet;
public static class Repro {
    public static async Task ClientLeak(MqttClientFactory f) { var lowLevelClient = f.CreateLowLevelMqttClient(); await lowLevelClient.DisconnectAsync(CancellationToken.None); }   // LowLevelMqttClient_Tests:44
}
