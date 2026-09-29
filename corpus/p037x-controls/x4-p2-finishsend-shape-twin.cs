// P-037-X Stage 4 positive control X4-P2 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// a SHAPE TWIN of the frozen case 2 (dotnet/runtime HttpClient.FinishSend at 49e04fa) — NOT the
// frozen input and never counted as its recovery. The producer PrepareCancellationTokenSource,
// the consumer FinishSend, the catch-side HandleFailure and four callers keep the frozen control
// flow (tuple deconstruction, try/catch/finally, an untracked nullable response in the first
// owned slot) with ONE change: the linked-CTS factory call is an object creation, because
// CancellationTokenSource.CreateLinkedTokenSource is outside the extractor's owning-factory table
// (an R boundary named in Stage 3, deliberately left untouched here).
using System;
using System.Threading;
using System.Threading.Tasks;

sealed class Response : IDisposable
{
    public void Dispose() { }
}

sealed class Request
{
    public string Name => "r";
}

sealed class Client : IDisposable
{
    private CancellationTokenSource _pendingRequestsCts = new CancellationTokenSource();
    private readonly TimeSpan _timeout = TimeSpan.FromSeconds(100);
    private static readonly TimeSpan s_infiniteTimeout = Timeout.InfiniteTimeSpan;

    public void Dispose()
    {
        _pendingRequestsCts.Dispose();
    }

    private static Task<Response?> SendCore(Request request, CancellationToken token) =>
        Task.FromResult<Response?>(new Response());

    private static Response? SendSync(Request request, CancellationToken token) => new Response();

    private static bool Telemetry() => DateTime.Now.Ticks % 2 == 0;

    private async Task<string> GetStringAsyncCore(Request request, CancellationToken cancellationToken)
    {
        bool telemetryStarted = Telemetry();
        bool responseContentTelemetryStarted = false;

        (CancellationTokenSource cts, bool disposeCts, CancellationTokenSource pendingRequestsCts) = PrepareCancellationTokenSource(cancellationToken);
        Response? response = null;
        try
        {
            response = await SendCore(request, cts.Token).ConfigureAwait(false);
            if (Telemetry() && telemetryStarted)
            {
                responseContentTelemetryStarted = true;
            }
            return request.Name;
        }
        catch (Exception e)
        {
            HandleFailure(e, telemetryStarted, response, cts, cancellationToken, pendingRequestsCts);
            throw;
        }
        finally
        {
            FinishSend(response, cts, disposeCts, telemetryStarted, responseContentTelemetryStarted);
        }
    }

    private async Task<byte[]> GetByteArrayAsyncCore(Request request, CancellationToken cancellationToken)
    {
        bool telemetryStarted = Telemetry();
        bool responseContentTelemetryStarted = false;

        (CancellationTokenSource cts, bool disposeCts, CancellationTokenSource pendingRequestsCts) = PrepareCancellationTokenSource(cancellationToken);
        Response? response = null;
        try
        {
            response = await SendCore(request, cts.Token).ConfigureAwait(false);
            return Array.Empty<byte>();
        }
        catch (Exception e)
        {
            HandleFailure(e, telemetryStarted, response, cts, cancellationToken, pendingRequestsCts);
            throw;
        }
        finally
        {
            FinishSend(response, cts, disposeCts, telemetryStarted, responseContentTelemetryStarted);
        }
    }

    private async Task<Response> GetStreamAsyncCore(Request request, CancellationToken cancellationToken)
    {
        bool telemetryStarted = Telemetry();

        (CancellationTokenSource cts, bool disposeCts, CancellationTokenSource pendingRequestsCts) = PrepareCancellationTokenSource(cancellationToken);
        Response? response = null;
        try
        {
            response = await SendCore(request, cts.Token).ConfigureAwait(false);
            return response!;
        }
        catch (Exception e)
        {
            HandleFailure(e, telemetryStarted, response, cts, cancellationToken, pendingRequestsCts);
            throw;
        }
        finally
        {
            FinishSend(response, cts, disposeCts, telemetryStarted, responseContentTelemetryStarted: false);
        }
    }

    public Response Send(Request request, CancellationToken cancellationToken)
    {
        bool telemetryStarted = Telemetry();

        (CancellationTokenSource cts, bool disposeCts, CancellationTokenSource pendingRequestsCts) = PrepareCancellationTokenSource(cancellationToken);
        Response? response = null;
        try
        {
            response = SendSync(request, cts.Token);
            return response!;
        }
        catch (Exception e)
        {
            HandleFailure(e, telemetryStarted, response, cts, cancellationToken, pendingRequestsCts);
            throw;
        }
        finally
        {
            FinishSend(response, cts, disposeCts, telemetryStarted, responseContentTelemetryStarted: false);
        }
    }

    private void HandleFailure(Exception e, bool telemetryStarted, Response? response, CancellationTokenSource cts, CancellationToken cancellationToken, CancellationTokenSource pendingRequestsCts)
    {
        response?.Dispose();
        if (cts.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            if (pendingRequestsCts.IsCancellationRequested)
            {
                return;
            }
        }
    }

    private static void FinishSend(Response? response, CancellationTokenSource cts, bool disposeCts, bool telemetryStarted, bool responseContentTelemetryStarted)
    {
        if (Telemetry() && telemetryStarted)
        {
            if (responseContentTelemetryStarted)
            {
                Console.WriteLine(response);
            }
        }

        if (disposeCts)
        {
            cts.Dispose();
        }
    }

    private (CancellationTokenSource TokenSource, bool DisposeTokenSource, CancellationTokenSource PendingRequestsCts) PrepareCancellationTokenSource(CancellationToken cancellationToken)
    {
        CancellationTokenSource pendingRequestsCts = _pendingRequestsCts;

        bool hasTimeout = _timeout != s_infiniteTimeout;
        if (hasTimeout || cancellationToken.CanBeCanceled)
        {
            CancellationTokenSource cts = new CancellationTokenSource();
            if (hasTimeout)
            {
                cts.CancelAfter(_timeout);
            }

            return (cts, DisposeTokenSource: true, pendingRequestsCts);
        }

        return (pendingRequestsCts, DisposeTokenSource: false, pendingRequestsCts);
    }
}
