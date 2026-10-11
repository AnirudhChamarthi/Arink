using System.Text.Json;

namespace Riskbot.App.Services;

public sealed class RecentFilesStore
{
    private const int MaxRecent = 5;
    private readonly string _path;

    public RecentFilesStore()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Riskbot");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "recent.json");
    }

    public IReadOnlyList<string> Load()
    {
        if (!File.Exists(_path))
            return [];
        try
        {
            var list = JsonSerializer.Deserialize<List<string>>(File.ReadAllText(_path)) ?? [];
            return list.Where(File.Exists).Take(MaxRecent).ToList();
        }
        catch
        {
            return [];
        }
    }

    public void Add(string filePath)
    {
        var full = Path.GetFullPath(filePath);
        var list = Load().Where(p => !string.Equals(p, full, StringComparison.OrdinalIgnoreCase)).ToList();
        list.Insert(0, full);
        File.WriteAllText(_path, JsonSerializer.Serialize(list.Take(MaxRecent).ToList()));
    }
}
