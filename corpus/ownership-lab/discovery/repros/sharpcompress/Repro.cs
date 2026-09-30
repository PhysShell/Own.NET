using SharpCompress.Archives; using SharpCompress.Archives.Zip; using SharpCompress.Readers.Zip; using SharpCompress.Common;
public static class Repro {
    public static void CreateLeak(Stream s) { var archive = ZipArchive.Create(); archive.SaveTo(s, CompressionType.None); }   // ZipArchiveTests:392
    public static void ReaderLeak(Stream entry) { var zipReader = ZipReader.Open(entry); while (zipReader.MoveToNextEntry()) { } }   // ZipReaderTests:377
}
