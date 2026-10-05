namespace Mimas.Monitor;

internal static class SignatureMatcher
{
    public static bool ExecutableMatches(ProductSignature product, string executable, string? publisher)
    {
        if (product.Executables.Count == 0 || string.IsNullOrWhiteSpace(executable)) return false;
        var name = Path.GetFileName(executable);
        if (!product.Executables.Any(value => string.Equals(NormalizeExe(value), NormalizeExe(name), StringComparison.OrdinalIgnoreCase)))
            return false;
        return PublisherMatches(product, publisher);
    }

    public static bool WindowMatches(ProductSignature product, string title, string executable, string? publisher)
    {
        if (title.Length == 0 || product.WindowTitles.Count == 0) return false;
        // A title alone is not a reliable native-app signature: browser tabs can
        // display the same title and are checked separately by the extension.
        if (product.Executables.Count == 0 && product.Publishers.Count == 0) return false;
        if (product.Executables.Count > 0 && !ExecutableMatches(product, executable, publisher)) return false;
        if (product.Executables.Count == 0 && !PublisherMatches(product, publisher)) return false;
        return product.WindowTitles.Any(alias => TitleMatches(alias, title));
    }

    private static bool PublisherMatches(ProductSignature product, string? publisher) =>
        product.Publishers.Count == 0 || (publisher is not null && product.Publishers.Any(value =>
            string.Equals(value.Trim(), publisher.Trim(), StringComparison.OrdinalIgnoreCase)));

    private static string NormalizeExe(string name) => name.Trim().EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
        ? name.Trim() : name.Trim() + ".exe";

    private static bool TitleMatches(string alias, string title)
    {
        alias = alias.Trim();
        if (alias.Length < 8) return false; // A generic short title is not a trustworthy signature.
        if (alias.EndsWith('*'))
        {
            var prefix = alias[..^1].TrimEnd();
            return prefix.Length >= 8 && title.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
        }
        return string.Equals(alias, title.Trim(), StringComparison.OrdinalIgnoreCase);
    }
}
