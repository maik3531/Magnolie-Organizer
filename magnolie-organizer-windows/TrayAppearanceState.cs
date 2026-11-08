namespace MagnolieOrganizer.Windows;

// Native state only; pairing, settings and persisted journals are not activity.
internal enum TrayFlowerConnection { None, Notes, Kde, Both }
internal enum TrayAppearanceMode { Flower, Camera, Phone }
internal readonly record struct TrayAppearanceState(TrayFlowerConnection Connection,
    bool Synchronizing = false, TrayAppearanceMode Mode = TrayAppearanceMode.Flower)
{
    internal bool IsOriginal => this == default;
    internal static TrayAppearanceState FromOwners(bool notes, bool kde, bool synchronizing)
        => new(notes ? kde ? TrayFlowerConnection.Both : TrayFlowerConnection.Notes :
            kde ? TrayFlowerConnection.Kde : TrayFlowerConnection.None, synchronizing);
}
