"""Stage D witness synthesiser: builds H-10 witness rows for candidates from per-library environment templates and a
small argument synthesiser (string, int, bool, enum, Stream, byte[], TimeSpan, Encoding, CancellationToken). Candidates
whose arguments cannot be synthesised are routed to UNWITNESSABLE_ARGS; libraries without an environment to UNWITNESSABLE_ENV."""
import json, sys, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
PKG={'SkiaSharp':[('SkiaSharp','4.153.1'),('SkiaSharp.NativeAssets.Linux','4.153.1')],'SSH.NET':[('SSH.NET','2026.0.0')],'StackExchange.Redis':[('StackExchange.Redis','3.3.1')],'Npgsql':[('Npgsql','10.0.3')],'LibGit2Sharp':[('LibGit2Sharp','0.32.0')],'MQTTnet':[('MQTTnet','5.2.0.1603'),('MQTTnet.Server','5.2.0.1603')],'MailKit':None,'RabbitMQ.Client':None}
# receiver setup per declaring type: (setup code, receiver expression) ; None -> not constructible here
ENV={
 'Renci.SshNet.SftpClient':('var sftp = new Renci.SshNet.SftpClient("127.0.0.1", 2222, "u", "p"); sftp.Connect(); System.IO.File.WriteAllText("/tmp/wit-existing.txt", "x");','sftp'),
 'Renci.SshNet.SshClient':('var ssh = new Renci.SshNet.SshClient("127.0.0.1", 2222, "u", "p"); ssh.Connect();','ssh'),
 'Renci.SshNet.ScpClient':('var scp = new Renci.SshNet.ScpClient("127.0.0.1", 2222, "u", "p"); scp.Connect();','scp'),
 'StackExchange.Redis.ConnectionMultiplexer':('var mux = StackExchange.Redis.ConnectionMultiplexer.Connect("127.0.0.1:6390");','mux'),
 'Npgsql.NpgsqlConnection':('var conn = new Npgsql.NpgsqlConnection("PGCS"); conn.Open(); using (var c0 = new Npgsql.NpgsqlCommand("create table if not exists wit_t(id int primary key, v text)", conn)) c0.ExecuteNonQuery();','conn'),
 'Npgsql.NpgsqlDataSource':('var ds = Npgsql.NpgsqlDataSource.Create("PGCS");','ds'),
 'Npgsql.NpgsqlMultiHostDataSource':('var mds = new Npgsql.NpgsqlDataSourceBuilder("PGCS").BuildMultiHost();','mds'),
 'Npgsql.NpgsqlCommand':('var conn = new Npgsql.NpgsqlConnection("PGCS"); conn.Open(); var cmd = new Npgsql.NpgsqlCommand("select 1", conn);','cmd'),
 'Npgsql.NpgsqlBatch':('var conn = new Npgsql.NpgsqlConnection("PGCS"); conn.Open(); var batch = new Npgsql.NpgsqlBatch(conn); batch.BatchCommands.Add(new Npgsql.NpgsqlBatchCommand("select 1"));','batch'),
 'Npgsql.NpgsqlDataReader':('var conn = new Npgsql.NpgsqlConnection("PGCS"); conn.Open(); var cmd0 = new Npgsql.NpgsqlCommand("select \'abc\'::bytea, \'abc\'::text", conn); var rdr = cmd0.ExecuteReader(); rdr.Read();','rdr'),
 'Npgsql.NpgsqlCommandBuilder':('var conn = new Npgsql.NpgsqlConnection("PGCS"); conn.Open(); using (var c0 = new Npgsql.NpgsqlCommand("create table if not exists wit_t(id int primary key, v text)", conn)) c0.ExecuteNonQuery(); var da = new Npgsql.NpgsqlDataAdapter("select * from wit_t", conn); var cb = new Npgsql.NpgsqlCommandBuilder(da);','cb'),
 'LibGit2Sharp.Repository':('var dir = System.IO.Directory.CreateTempSubdirectory().FullName; LibGit2Sharp.Repository.Init(dir); var repo = new LibGit2Sharp.Repository(dir);','repo'),
 'LibGit2Sharp.RemoteCollection':('var dir = System.IO.Directory.CreateTempSubdirectory().FullName; LibGit2Sharp.Repository.Init(dir); var repo = new LibGit2Sharp.Repository(dir); repo.Network.Remotes.Add("origin", "https://example.invalid/r.git"); int rn = 0; var rc = repo.Network.Remotes;','rc'),
 'SkiaSharp.SKBitmap':('var bmp = new SkiaSharp.SKBitmap(4, 4);','bmp'),
 'SkiaSharp.SKImage':('var img = SkiaSharp.SKImage.FromBitmap(new SkiaSharp.SKBitmap(4, 4));','img'),
 'SkiaSharp.SKSurface':('var surf = SkiaSharp.SKSurface.Create(new SkiaSharp.SKImageInfo(4, 4));','surf'),
 'SkiaSharp.SKPixmap':('var pm = new SkiaSharp.SKBitmap(4, 4).PeekPixels();','pm'),
 'SkiaSharp.SKCanvas':('var cv = SkiaSharp.SKSurface.Create(new SkiaSharp.SKImageInfo(4, 4)).Canvas;','cv'),
 'SkiaSharp.SKPaint':('var paint = new SkiaSharp.SKPaint();','paint'),
 'SkiaSharp.SKPath':('var path = new SkiaSharp.SKPath(); path.AddRect(new SkiaSharp.SKRect(0, 0, 2, 2));','path'),
 'SkiaSharp.SKPathBuilder':('var pb = new SkiaSharp.SKPathBuilder(); pb.AddRect(new SkiaSharp.SKRect(0, 0, 2, 2));','pb'),
 'SkiaSharp.SKData':('var data = SkiaSharp.SKData.CreateCopy(new byte[] { 1, 2, 3 });','data'),
 'SkiaSharp.SKTypeface':('var tf = SkiaSharp.SKTypeface.Default;','tf'),
 'SkiaSharp.SKFont':('var font = new SkiaSharp.SKFont();','font'),
 'SkiaSharp.SKFontManager':('var fm = SkiaSharp.SKFontManager.Default;','fm'),
 'SkiaSharp.SKCodec':('var codec = SkiaSharp.SKCodec.Create(new System.IO.MemoryStream(Convert.FromBase64String("PNG1")));','codec'),
 'SkiaSharp.SKPictureRecorder':('var rec = new SkiaSharp.SKPictureRecorder(); rec.BeginRecording(new SkiaSharp.SKRect(0, 0, 4, 4));','rec'),
 'SkiaSharp.SKPicture':('var rec0 = new SkiaSharp.SKPictureRecorder(); rec0.BeginRecording(new SkiaSharp.SKRect(0, 0, 4, 4)); var pic = rec0.EndRecording();','pic'),
 'SkiaSharp.SKTextBlobBuilder':('var tbb = new SkiaSharp.SKTextBlobBuilder(); tbb.AddRun(new ushort[] { 1 }, new SkiaSharp.SKFont());','tbb'),
 'SkiaSharp.SKRoundRect':('var rr = new SkiaSharp.SKRoundRect(new SkiaSharp.SKRect(0, 0, 4, 4), 1);','rr'),
 'SkiaSharp.SKRegion':('var region = new SkiaSharp.SKRegion(new SkiaSharp.SKRectI(0, 0, 4, 4));','region'),
 'SkiaSharp.SKColorSpace':('var cs = SkiaSharp.SKColorSpace.CreateSrgb();','cs'),
 'SkiaSharp.SKShader':('var sh = SkiaSharp.SKShader.CreateColor(SkiaSharp.SKColors.Red);','sh'),
 'SkiaSharp.SKStream':('var sks = new SkiaSharp.SKMemoryStream(new byte[] { 1, 2, 3 });','sks'),
 'SkiaSharp.SKMemoryStream':('var sks = new SkiaSharp.SKMemoryStream(new byte[] { 1, 2, 3 });','sks'),
 'SkiaSharp.SKRuntimeEffect':('var eff = SkiaSharp.SKRuntimeEffect.CreateShader("half4 main(float2 p) { return half4(1); }", out var err0);','eff'),
 'SkiaSharp.SKRuntimeShaderBuilder':('var rsb = new SkiaSharp.SKRuntimeShaderBuilder(SkiaSharp.SKRuntimeEffect.CreateShader("half4 main(float2 p) { return half4(1); }", out var err1));','rsb'),
 'SkiaSharp.SKRuntimeColorFilterBuilder':('var rcb = new SkiaSharp.SKRuntimeColorFilterBuilder(SkiaSharp.SKRuntimeEffect.CreateColorFilter("half4 main(half4 c) { return c; }", out var err2));','rcb'),
 'SkiaSharp.SKRuntimeBlenderBuilder':('var rbb = new SkiaSharp.SKRuntimeBlenderBuilder(SkiaSharp.SKRuntimeEffect.CreateBlender("half4 main(half4 s, half4 d) { return s; }", out var err3));','rbb'),
 'SkiaSharp.SKDrawable':None, 'SkiaSharp.SKDocument':None,
}
def arg(t, i):
    t=t.replace('?','')
    m={'string':'"/tmp/wit-existing.txt"' if i==0 else '"x"','int':'1','long':'1L','bool':'false','byte[]':'new byte[16]','System.IO.Stream':'Ms()','System.TimeSpan':'System.TimeSpan.FromSeconds(1)','System.Text.Encoding':'System.Text.Encoding.UTF8','System.Threading.CancellationToken':'default','System.IO.FileMode':'System.IO.FileMode.OpenOrCreate','System.IO.FileAccess':'System.IO.FileAccess.ReadWrite','uint':'1u','float':'1f','double':'1.0','System.ReadOnlySpan<byte>':'new byte[16]','System.Memory<byte>':'new byte[16]',
       'System.Data.IsolationLevel':'System.Data.IsolationLevel.ReadCommitted','System.Data.CommandBehavior':'System.Data.CommandBehavior.Default','System.Data.CommandBehavior?':'null',
       'SkiaSharp.SKImageInfo':'new SkiaSharp.SKImageInfo(4, 4)','SkiaSharp.SKBitmap':'new SkiaSharp.SKBitmap(4, 4)','SkiaSharp.SKImage':'SkiaSharp.SKImage.FromBitmap(new SkiaSharp.SKBitmap(4, 4))','SkiaSharp.SKPixmap':'new SkiaSharp.SKBitmap(4, 4).PeekPixels()','SkiaSharp.SKPaint':'new SkiaSharp.SKPaint()','SkiaSharp.SKPath':'new SkiaSharp.SKPath()','SkiaSharp.SKData':'SkiaSharp.SKData.CreateCopy(Convert.FromBase64String("PNG1"))','SkiaSharp.SKEncodedImageFormat':'SkiaSharp.SKEncodedImageFormat.Png','SkiaSharp.SKRect':'new SkiaSharp.SKRect(0, 0, 4, 4)','SkiaSharp.SKRectI':'new SkiaSharp.SKRectI(0, 0, 4, 4)','SkiaSharp.SKPoint':'SkiaSharp.SKPoint.Empty','SkiaSharp.SKColor':'SkiaSharp.SKColors.Red','SkiaSharp.SKColor[]':'new[] { SkiaSharp.SKColors.Red, SkiaSharp.SKColors.Blue }','float[]':'new float[] { 1f, 2f }','SkiaSharp.SKShaderTileMode':'SkiaSharp.SKShaderTileMode.Clamp','SkiaSharp.SKMatrix':'SkiaSharp.SKMatrix.Identity','SkiaSharp.SKSizeI':'new SkiaSharp.SKSizeI(2, 2)','SkiaSharp.SKSamplingOptions':'SkiaSharp.SKSamplingOptions.Default','SkiaSharp.SKFont':'new SkiaSharp.SKFont()','SkiaSharp.SKTypeface':'SkiaSharp.SKTypeface.Default','SkiaSharp.SKFontStyle':'SkiaSharp.SKFontStyle.Normal','SkiaSharp.SKFontStyleWeight':'SkiaSharp.SKFontStyleWeight.Normal','SkiaSharp.SKFontStyleWidth':'SkiaSharp.SKFontStyleWidth.Normal','SkiaSharp.SKFontStyleSlant':'SkiaSharp.SKFontStyleSlant.Upright','SkiaSharp.SKColorSpace':'SkiaSharp.SKColorSpace.CreateSrgb()','SkiaSharp.SKColorType':'SkiaSharp.SKColorType.Rgba8888','SkiaSharp.SKAlphaType':'SkiaSharp.SKAlphaType.Premul','SkiaSharp.SKStream':'new SkiaSharp.SKMemoryStream(Convert.FromBase64String("PNG1"))','SkiaSharp.SKWStream':'new SkiaSharp.SKDynamicMemoryWStream()','SkiaSharp.SKShader':'SkiaSharp.SKShader.CreateColor(SkiaSharp.SKColors.Red)','SkiaSharp.SKColorFilter':'SkiaSharp.SKColorFilter.CreateBlendMode(SkiaSharp.SKColors.Red, SkiaSharp.SKBlendMode.SrcOver)','SkiaSharp.SKImageFilter':'SkiaSharp.SKImageFilter.CreateBlur(1, 1)','SkiaSharp.SKBlendMode':'SkiaSharp.SKBlendMode.SrcOver','SkiaSharp.SKPathEffect':'SkiaSharp.SKPathEffect.CreateDash(new float[] { 1f, 1f }, 0)','SkiaSharp.SKPicture':'(new SkiaSharp.SKPictureRecorder()).BeginRecording(new SkiaSharp.SKRect(0, 0, 4, 4)) is var _c0 ? default(SkiaSharp.SKPicture) : null','SkiaSharp.SKRoundRect':'new SkiaSharp.SKRoundRect(new SkiaSharp.SKRect(0, 0, 4, 4), 1)','SkiaSharp.SKRegion':'new SkiaSharp.SKRegion(new SkiaSharp.SKRectI(0, 0, 4, 4))','char':"'x'",'System.ReadOnlySpan<char>':'"x"','ushort[]':'new ushort[] { 1 }','SkiaSharp.SKSurfaceProperties':'new SkiaSharp.SKSurfaceProperties(SkiaSharp.SKPixelGeometry.Unknown)','SkiaSharp.SKPixelGeometry':'SkiaSharp.SKPixelGeometry.Unknown','SkiaSharp.SKTextAlign':'SkiaSharp.SKTextAlign.Left','SkiaSharp.SKTextEncoding':'SkiaSharp.SKTextEncoding.Utf8','System.IntPtr':'System.IntPtr.Zero','nint':'0','System.Func<SkiaSharp.SKCanvas, SkiaSharp.SKRect, bool>':'null'}
    if t in m and m[t]=='(new SkiaSharp.SKPictureRecorder()).BeginRecording(new SkiaSharp.SKRect(0, 0, 4, 4)) is var _c0 ? default(SkiaSharp.SKPicture) : null': return None
    m.update({'SkiaSharp.SKPathOp':'SkiaSharp.SKPathOp.Union','SkiaSharp.SKBlurStyle':'SkiaSharp.SKBlurStyle.Normal','ulong':'1UL','Npgsql.TargetSessionAttributes':'Npgsql.TargetSessionAttributes.Any','SkiaSharp.SKClipOperation':'SkiaSharp.SKClipOperation.Intersect','SkiaSharp.SKPathFillType':'SkiaSharp.SKPathFillType.Winding','SkiaSharp.SKPathDirection':'SkiaSharp.SKPathDirection.Clockwise','SkiaSharp.SKHighContrastConfig':'new SkiaSharp.SKHighContrastConfig()','SkiaSharp.SKColorChannel':'SkiaSharp.SKColorChannel.R','SkiaSharp.SKShaderTileMode?':'null','SkiaSharp.SKPathEffect1DStyle':'SkiaSharp.SKPathEffect1DStyle.Translate','SkiaSharp.SKTrimPathEffectMode':'SkiaSharp.SKTrimPathEffectMode.Normal','SkiaSharp.SKBlendMode?':'null','SkiaSharp.SKCubicResampler':'SkiaSharp.SKCubicResampler.Mitchell','SkiaSharp.SKFilterMode':'SkiaSharp.SKFilterMode.Linear','SkiaSharp.SKMipmapMode':'SkiaSharp.SKMipmapMode.None','SkiaSharp.SKPoint3':'new SkiaSharp.SKPoint3(0, 0, 1)','SkiaSharp.SKPointI':'new SkiaSharp.SKPointI(0, 0)','SkiaSharp.SKSize':'new SkiaSharp.SKSize(2, 2)','byte':'(byte)1','SkiaSharp.SKColorF':'new SkiaSharp.SKColorF(1, 0, 0)','SkiaSharp.SKColorF[]':'new[] { new SkiaSharp.SKColorF(1, 0, 0), new SkiaSharp.SKColorF(0, 0, 1) }','float?':'null','int?':'null','SkiaSharp.SKRect?':'null','SkiaSharp.SKRectI?':'null','SkiaSharp.SKColorSpace?':'null','SkiaSharp.SKPaint?':'null','SkiaSharp.SKMatrix?':'null','string?':'null','System.IO.TextWriter?':'null','SkiaSharp.SKImageInfo?':'null','SkiaSharp.SKFont?':'null','SkiaSharp.SKTypeface?':'null','SkiaSharp.SKShader?':'null','SkiaSharp.SKImageFilter?':'null','SkiaSharp.SKColorFilter?':'null','SkiaSharp.SKPathEffect?':'null','SkiaSharp.SKMaskFilter?':'null','SkiaSharp.SKPicture?':'null','SkiaSharp.SKSurfaceProperties?':'null'})
    if t in m: return m[t]
    if t.endswith('?') and not t[:-1] in ('int','float','bool','long','double','uint','ulong','byte','char'): return 'null'
    return None
uni=json.load(open(f'{S}/lab/sc/stagec-universe.json'))['universe']; api={}
for pid in {u['package'] for u in uni}:
    for f in json.load(open(f'{D}/libs/{pid}/api.json'))['factories']: api.setdefault(f['callable'],[]).append(f)
PNG='iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAEklEQVR42mNk+M9Qz0AEYBxWCgB6dwOZbqmn8AAAAABJRU5ErkJggg=='
rows=[]; routed={}
# per-callable argument overrides that encode a documented protocol (label-independent): PostgreSQL COPY command texts,
# libgit2 remote names; array sizes are read back from the previous run's argument exceptions ("length of N", "Exactly N")
CALLARG={'Npgsql.NpgsqlConnection.BeginBinaryImport':{0:'"COPY wit_t FROM STDIN (FORMAT BINARY)"'},'Npgsql.NpgsqlConnection.BeginBinaryImportAsync':{0:'"COPY wit_t FROM STDIN (FORMAT BINARY)"'},
 'Npgsql.NpgsqlConnection.BeginBinaryExport':{0:'"COPY wit_t TO STDOUT (FORMAT BINARY)"'},'Npgsql.NpgsqlConnection.BeginBinaryExportAsync':{0:'"COPY wit_t TO STDOUT (FORMAT BINARY)"'},
 'Npgsql.NpgsqlConnection.BeginTextImport':{0:'"COPY wit_t FROM STDIN"'},'Npgsql.NpgsqlConnection.BeginTextImportAsync':{0:'"COPY wit_t FROM STDIN"'},
 'Npgsql.NpgsqlConnection.BeginTextExport':{0:'"COPY wit_t TO STDOUT"'},'Npgsql.NpgsqlConnection.BeginTextExportAsync':{0:'"COPY wit_t TO STDOUT"'},
 'Npgsql.NpgsqlConnection.BeginRawBinaryCopy':{0:'"COPY wit_t TO STDOUT (FORMAT BINARY)"'},'Npgsql.NpgsqlConnection.BeginRawBinaryCopyAsync':{0:'"COPY wit_t TO STDOUT (FORMAT BINARY)"'},
 'LibGit2Sharp.RemoteCollection.Rename':{0:'"origin"',1:'"upstream"'},'LibGit2Sharp.RemoteCollection.Add':{0:'"second"',1:'"https://example.invalid/s.git"'},'LibGit2Sharp.RemoteCollection.Update':{0:'"origin"'}}
SEQ_TYPES={'Npgsql.NpgsqlConnection','Npgsql.NpgsqlCommand','Npgsql.NpgsqlBatch','Npgsql.NpgsqlDataReader','Npgsql.NpgsqlCommandBuilder'}   # one active operation per connection (documented Npgsql protocol)
ARRN={}
PRELUDE='System.IO.MemoryStream Ms() { var s0 = new System.IO.MemoryStream(); var b0 = Convert.FromBase64String("PNG1"); s0.Write(b0, 0, b0.Length); s0.Position = 0; return s0; } '
# out/ref discards: the API listing drops the modifier; positions come from the compiler (CS1620) in the previous run
OUT={}
import os
prev=f'{S}/lab/sc/witness-results.json.partial.jsonl'
if os.path.exists(prev):
    for l in open(prev):
        try: j=json.loads(l)
        except Exception: continue
        for m in re.finditer(r"Argument (\d+) must be passed with the '(out|ref)' keyword", j.get('stderr','')): OUT.setdefault(j['callable'],{})[int(m.group(1))-1]=m.group(2)
        m2=re.search(r'(?:length of|Exactly) (\d+)', j.get('msg','') or '')
        if m2: ARRN[j['callable']]=int(m2.group(1))
for u in uni:
    pid=u['package']; c=u['callable']; typ=c.rsplit('.',1)[0]; meth=c.rsplit('.',1)[1]
    if PKG.get(pid) is None: routed[c]='UNWITNESSABLE_ENV'; continue
    if not u['is_static'] and ENV.get(typ, 'missing') is None: routed[c]='UNWITNESSABLE_RECEIVER:'+typ; continue
    chosen=None; missing=None
    for f in sorted(api.get(c,[u]), key=lambda f: len(f.get('parameters') or [])):
        params=f.get('parameters') or []; args=[arg(t,i) for i,t in enumerate(params)]
        for i0,kw in OUT.get(c,{}).items():
            if i0<len(args): args[i0]=kw+' _'
        for i0,txt in CALLARG.get(c,{}).items():
            if i0<len(args): args[i0]=txt
        if c in ARRN:
            n=ARRN[c]
            for i0,t in enumerate(params):
                if t=='float[]': args[i0]=f'new float[{n}]'
                elif t=='byte[]': args[i0]=f'new byte[{n}]'
                elif t=='SkiaSharp.SKColor[]': args[i0]='new SkiaSharp.SKColor[] { '+', '.join(['SkiaSharp.SKColors.Red']*n)+' }'
                elif t=='SkiaSharp.SKColorF[]': args[i0]='new SkiaSharp.SKColorF[] { '+', '.join(['new SkiaSharp.SKColorF(1, 0, 0)']*n)+' }'
        if all(a is not None for a in args): chosen=(params,args,bool(f.get('async_wrapped'))); break
        missing=','.join(t for t,a in zip(params,args) if a is None)
    if chosen is None: routed[c]='UNWITNESSABLE_ARGS:'+(missing or '?'); continue
    params,args,aw=chosen
    call=f'{meth}({", ".join(args)})'
    if aw: call+='.GetAwaiter().GetResult()'
    if u['is_static']: setup=''; expr=f'{typ}.{call}'
    else:
        if typ not in ENV: routed[c]='UNWITNESSABLE_RECEIVER:'+typ; continue
        setup,recv=ENV[typ]; expr=f'{recv}.{call}'
    rows.append({'id':'SC-'+re.sub(r'[^A-Za-z0-9]','',c)[-24:],'kind':'fresh','mode':'sequential' if typ in SEQ_TYPES else 'parallel','recv':(None if u['is_static'] else ENV[typ][1]),'packages':PKG[pid],'callable':c,'setup':((PRELUDE+setup).replace('PGCS','Host=/tmp/pgsc;Username=postgres;Database=postgres;Port=5432').replace('PNG1',PNG)),'expr':expr.replace('PNG1',PNG),'dispose':True,'expect':'fresh','package_id':pid})
json.dump({'rows':rows,'routed':routed},open(f'{S}/lab/sc/witsyn-rows.json','w'),indent=1)
import collections; print('witness rows',len(rows),'routed',collections.Counter(v.split(':')[0] for v in routed.values()))
