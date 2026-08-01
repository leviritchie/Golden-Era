namespace GoldenEraModInstaller;

internal sealed record InstallerProgress(
    string Phase,
    string Detail,
    double? FractionComplete,
    long? BytesCompleted = null,
    long? BytesTotal = null)
{
    public static InstallerProgress Indeterminate(string phase, string detail) =>
        new(phase, detail, FractionComplete: null);

    public static InstallerProgress OfBytes(string phase, string detail, long completed, long total)
    {
        var fraction = total > 0 ? Math.Clamp(completed / (double)total, 0d, 1d) : 0d;
        return new(phase, detail, fraction, completed, total);
    }
}
