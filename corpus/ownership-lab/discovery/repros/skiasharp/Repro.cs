using SkiaSharp;
public static class Repro {
    public static void DecodeLeak(string path) { var bmp = SKBitmap.Decode(path); var w = bmp.Width; }            // SKBitmapTest:143 / :338 / SKCodecTest:323
    public static void AsStreamLeak(byte[] bytes) { var data = SKData.CreateCopy(bytes); var stream = data.AsStream(); stream.ReadByte(); data.Dispose(); }   // SKDataTest:46 / :59
    public static void TextPathLeak(SKFont font) { var textPath = font.GetTextPath("x", SKPoint.Empty); var w = textPath.TightBounds.Width; }   // SKFontTest:325
    public static void Clean(string path) { using var bmp = SKBitmap.Decode(path); var w = bmp.Width; }
}
