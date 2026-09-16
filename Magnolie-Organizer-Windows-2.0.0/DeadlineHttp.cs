using System.Net;

namespace MagnolieOrganizer.Windows;

// Unlike HttpClient.Timeout with ResponseHeadersRead, this lifetime owns the body too.
internal sealed class DeadlineHttp : DelegatingHandler
{
    private readonly CancellationTokenSource lifetime = new();
    private readonly TimeSpan timeout;
    private readonly long maximum;
    private int disposed;
    private DeadlineHttp(HttpMessageHandler handler, TimeSpan timeout, long maximum) : base(handler)
    { this.timeout = timeout; this.maximum = maximum; }

    internal static HttpClient Create(TimeSpan timeout, HttpMessageHandler? handler = null, long maximum = 64L * 1024 * 1024) =>
        new(new DeadlineHttp(handler ?? new HttpClientHandler { AllowAutoRedirect = false }, timeout, maximum)) { Timeout = timeout };

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
    {
        var deadline = CancellationTokenSource.CreateLinkedTokenSource(token, lifetime.Token);
        deadline.CancelAfter(timeout);
        HttpResponseMessage? response = null;
        try
        {
            response = await base.SendAsync(request, deadline.Token).ConfigureAwait(false);
            if (response.Content.Headers.ContentLength > maximum) throw new InvalidDataException(NativeLocalization.Gettext("The server response is too large."));
            response.Content = new Body(response.Content, deadline, maximum);
            return response;
        }
        catch { response?.Dispose(); deadline.Dispose(); throw; }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing && Interlocked.Exchange(ref disposed, 1) == 0) lifetime.Cancel();
        base.Dispose(disposing);
    }

    private sealed class Body : HttpContent
    {
        private readonly HttpContent original;
        private readonly CancellationTokenSource deadline;
        private readonly long maximum;
        private int disposed;
        internal Body(HttpContent original, CancellationTokenSource deadline, long maximum)
        {
            this.original = original; this.deadline = deadline; this.maximum = maximum;
            foreach (var header in original.Headers) Headers.TryAddWithoutValidation(header.Key, header.Value);
        }
        protected override bool TryComputeLength(out long length)
        { length = original.Headers.ContentLength ?? -1; return length >= 0; }
        protected override Task<Stream> CreateContentReadStreamAsync() => CreateContentReadStreamAsync(deadline.Token);
        protected override async Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken)
        {
            deadline.Token.ThrowIfCancellationRequested();
            return new ReadStream(await original.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false), deadline.Token, maximum);
        }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            SerializeToStreamAsync(stream, context, deadline.Token);
        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context, CancellationToken cancellationToken)
        {
            await using var input = await CreateContentReadStreamAsync().ConfigureAwait(false);
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token, cancellationToken);
            await input.CopyToAsync(stream, linked.Token).ConfigureAwait(false);
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing && Interlocked.Exchange(ref disposed, 1) == 0) { deadline.Cancel(); original.Dispose(); deadline.Dispose(); }
            base.Dispose(disposing);
        }
    }

    private sealed class ReadStream : Stream
    {
        private readonly Stream input;
        private readonly CancellationToken lifetime;
        private readonly CancellationTokenRegistration close;
        private readonly long maximum;
        private long count;
        internal ReadStream(Stream input, CancellationToken lifetime, long maximum)
        {
            this.input = input; this.lifetime = lifetime; this.maximum = maximum;
            close = lifetime.Register(() => { try { input.Dispose(); } catch (Exception) { } });
        }
        public override bool CanRead => true;
        public override bool CanWrite => false;
        public override bool CanSeek => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => count; set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override int Read(byte[] buffer, int offset, int count) => ReadAsync(buffer, offset, count).GetAwaiter().GetResult();
        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
            ReadAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(lifetime, cancellationToken);
            try
            {
                linked.Token.ThrowIfCancellationRequested();
                var read = await input.ReadAsync(buffer, linked.Token).ConfigureAwait(false);
                count += read; if (count > maximum) throw new InvalidDataException(NativeLocalization.Gettext("The server response is too large."));
                return read;
            }
            catch (Exception) when (linked.IsCancellationRequested) { throw new OperationCanceledException(linked.Token); }
        }
        protected override void Dispose(bool disposing) { if (disposing) { close.Dispose(); input.Dispose(); } base.Dispose(disposing); }
    }
}
