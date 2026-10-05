using Mimas.Monitor;

if (args.Contains("--self-test"))
{
    SelfTests.Run();
    return;
}

if (!OperatingSystem.IsWindows())
{
    Console.Error.WriteLine("Windows-помощник MIMAS работает только в Windows.");
    return;
}

var server = Environment.GetEnvironmentVariable("MIMAS_MONITOR_URL") ?? "https://mimas-staging.onrender.com";
Console.WriteLine("MIMAS — проверка известных помощников во время интервью");
Console.WriteLine("Проверяются названия процессов и окон. На сервер уходят только совпавшие продукты и тип события.");
Console.WriteLine("Для остановки нажмите Ctrl+C. Код подключения возьмите в интервью MIMAS.");
Console.Write("Одноразовый код Windows-помощника: ");
var code = Console.ReadLine()?.Trim();
if (string.IsNullOrWhiteSpace(code))
{
    Console.Error.WriteLine("Код не введён.");
    return;
}

using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, eventArgs) => { eventArgs.Cancel = true; cancellation.Cancel(); };
using var api = new MonitorApi(server);
try
{
    var claim = await api.ClaimAsync(code, cancellation.Token);
    code = null; // Do not retain or print the one-time secret.
    var catalog = await api.CatalogAsync(cancellation.Token);
    var scanner = new Win32Scanner(catalog);
    var detected = new HashSet<ObservationKey>();
    var pending = new Queue<ObservationEvent>();
    var nextHeartbeat = DateTime.MinValue;
    var nextCatalogRefresh = DateTime.UtcNow.AddMinutes(5);
    var lastNetworkWarning = DateTime.MinValue;
    Console.WriteLine($"Подключено к интервью {claim.SessionId}. В каталоге {catalog.Products.Count} продуктов.");

    while (!cancellation.IsCancellationRequested)
    {
        try
        {
            if (DateTime.UtcNow >= nextCatalogRefresh)
            {
                catalog = await api.CatalogAsync(cancellation.Token);
                scanner.SetCatalog(catalog);
                nextCatalogRefresh = DateTime.UtcNow.AddMinutes(5);
            }
            if (DateTime.UtcNow >= nextHeartbeat)
            {
                await api.HeartbeatAsync(cancellation.Token);
                nextHeartbeat = DateTime.UtcNow.AddSeconds(15);
            }

            var current = MonitorDetector.Detect(catalog, scanner.Capture());
            foreach (var key in current.Except(detected))
            {
                pending.Enqueue(new ObservationEvent(key.ProductId, key.Kind, "detected"));
                Console.WriteLine($"Обнаружено: {catalog.Products.First(product => product.Id == key.ProductId).Name} ({key.Kind}).");
            }
            foreach (var key in detected.Except(current))
                pending.Enqueue(new ObservationEvent(key.ProductId, key.Kind, "cleared"));
            detected = current;

            while (pending.TryPeek(out var observation))
            {
                await api.SendObservationAsync(observation, cancellation.Token);
                pending.Dequeue();
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { break; }
        catch (Exception error) when (error is MonitorUnauthorizedException or MonitorSessionEndedException)
        {
            Console.Error.WriteLine(error.Message);
            break;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException)
        {
            if (DateTime.UtcNow - lastNetworkWarning > TimeSpan.FromSeconds(30))
            {
                Console.Error.WriteLine($"Связь с MIMAS прервана: {error.Message} Повторяем подключение.");
                lastNetworkWarning = DateTime.UtcNow;
            }
            if (pending.Count > 1000)
            {
                Console.Error.WriteLine("Очередь событий переполнена; переподключите помощник.");
                break;
            }
        }
        try { await Task.Delay(TimeSpan.FromSeconds(3), cancellation.Token); }
        catch (OperationCanceledException) { break; }
    }
}
catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
catch (Exception error)
{
    Console.Error.WriteLine($"Не удалось подключиться к MIMAS: {error.Message}");
}
finally
{
    using var shutdown = new CancellationTokenSource(TimeSpan.FromSeconds(5));
    try { await api.DisconnectAsync(shutdown.Token); }
    catch (Exception error) when (error is HttpRequestException or TaskCanceledException or
                                  MonitorUnauthorizedException or MonitorSessionEndedException)
    {
        // Network loss and expired sessions still allow the candidate to stop locally.
    }
}
