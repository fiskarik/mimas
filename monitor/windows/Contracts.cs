using System.Text.Json.Serialization;

namespace Mimas.Monitor;

internal sealed class CatalogResponse
{
    [JsonPropertyName("version")] public long Version { get; init; }
    [JsonPropertyName("products")] public List<ProductSignature> Products { get; init; } = [];
}

internal sealed class ProductSignature
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("domains")] public List<string> Domains { get; init; } = [];
    [JsonPropertyName("executables")] public List<string> Executables { get; init; } = [];
    [JsonPropertyName("window_titles")] public List<string> WindowTitles { get; init; } = [];
    [JsonPropertyName("publishers")] public List<string> Publishers { get; init; } = [];
}

internal sealed class ClaimResponse
{
    [JsonPropertyName("token")] public string Token { get; init; } = "";
    [JsonPropertyName("session_id")] public string SessionId { get; init; } = "";
    [JsonPropertyName("expires_at")] public double ExpiresAt { get; init; }
}

internal sealed class ObservationEvent(string productId, string kind, string state)
{
    [JsonPropertyName("event_id")] public string EventId { get; } = Guid.NewGuid().ToString("N");
    [JsonPropertyName("product_id")] public string ProductId { get; } = productId;
    [JsonPropertyName("kind")] public string Kind { get; } = kind;
    [JsonPropertyName("state")] public string State { get; } = state;
}

internal readonly record struct ObservationKey(string ProductId, string Kind);
