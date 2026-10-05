using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Mimas.Monitor;

internal sealed class MonitorApi : IDisposable
{
    private readonly HttpClient client;
    private string token = "";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public MonitorApi(string baseUrl)
    {
        var uri = new Uri(baseUrl.TrimEnd('/') + "/", UriKind.Absolute);
        if (uri.Scheme != Uri.UriSchemeHttps && !(uri.Scheme == Uri.UriSchemeHttp &&
            (uri.Host == "localhost" || uri.Host == "127.0.0.1")))
            throw new ArgumentException("Монитор подключается только по HTTPS (HTTP разрешён лишь для localhost).");
        client = new HttpClient { BaseAddress = uri, Timeout = TimeSpan.FromSeconds(90) };
    }

    public async Task<ClaimResponse> ClaimAsync(string code, CancellationToken cancellationToken)
    {
        using var response = await client.PostAsJsonAsync("api/monitor/claim", new { code, component = "helper" }, Json, cancellationToken);
        await RequireSuccess(response, cancellationToken);
        var claim = await response.Content.ReadFromJsonAsync<ClaimResponse>(Json, cancellationToken);
        if (string.IsNullOrWhiteSpace(claim?.Token)) throw new InvalidOperationException("Сервер не вернул токен подключения.");
        token = claim.Token;
        return claim;
    }

    public async Task<CatalogResponse> CatalogAsync(CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Get, "api/monitor/catalog", null, cancellationToken);
        var catalog = await response.Content.ReadFromJsonAsync<CatalogResponse>(Json, cancellationToken);
        if (catalog is null) throw new InvalidOperationException("Сервер не вернул каталог помощников.");
        return catalog;
    }

    public async Task HeartbeatAsync(CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Post, "api/monitor/heartbeat", new { }, cancellationToken);
    }

    public async Task SendObservationAsync(ObservationEvent observation, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Post, "api/monitor/observations", observation, cancellationToken);
    }

    public async Task DisconnectAsync(CancellationToken cancellationToken)
    {
        if (token.Length == 0) return;
        using var response = await SendAsync(HttpMethod.Post, "api/monitor/disconnect", new { }, cancellationToken);
        token = "";
    }

    private async Task<HttpResponseMessage> SendAsync(HttpMethod method, string path, object? value, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, path);
        request.Headers.Add("X-Monitor-Token", token);
        if (value is not null) request.Content = JsonContent.Create(value, options: Json);
        var response = await client.SendAsync(request, cancellationToken);
        try { await RequireSuccess(response, cancellationToken); return response; }
        catch { response.Dispose(); throw; }
    }

    private static async Task RequireSuccess(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode) return;
        if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
            throw new MonitorUnauthorizedException();
        if (response.StatusCode == HttpStatusCode.Conflict)
            throw new MonitorSessionEndedException();
        // Do not echo server response bodies: they can accidentally contain tokens or user data.
        await Task.CompletedTask;
        throw new HttpRequestException($"MIMAS вернул HTTP {(int)response.StatusCode}.", null, response.StatusCode);
    }

    public void Dispose() => client.Dispose();
}

internal sealed class MonitorUnauthorizedException() : Exception("Срок подключения истёк. Получите новый код в MIMAS.");
internal sealed class MonitorSessionEndedException() : Exception("Интервью завершено. Проверка остановлена.");
