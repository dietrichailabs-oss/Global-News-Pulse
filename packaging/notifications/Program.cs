using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Security;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppLifecycle;

// This process is a child of the UI, has no collector, and exits on stdin EOF.
// Windows may start it solely to deliver a click on an existing notification.
internal static class Program
{
    private static readonly object OutputLock = new();
    private static readonly ManualResetEventSlim Activation = new(false);
    private static readonly Regex ValidId = new(@"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z");
    private static readonly object ActivationLock = new();
    private static readonly Dictionary<string, long> RecentActivations = new();
    private static bool bridge;
    private static void Reply(object value)
    {
        if (!bridge) return;
        lock (OutputLock) { Console.WriteLine(JsonSerializer.Serialize(value)); Console.Out.Flush(); }
    }
    private static string Field(JsonElement doc, string name, int max = 512)
    {
        var value = doc.TryGetProperty(name, out var p) ? p.GetString() ?? "" : "";
        return new string(value.Where(c => c >= ' ' || c == '\n').Take(max).ToArray());
    }
    private static string Escape(string text) => SecurityElement.Escape(text) ?? "";
    // Both initial SDK arguments and later COM callbacks use the same validator.
    // The short window removes duplicate initial/event delivery, not later clicks.
    private static void HandleActivation(AppNotificationActivatedEventArgs args)
    {
        try
        {
            var argument = args.Argument ?? "";
            if (argument.Length > 512 || !argument.StartsWith("event=", StringComparison.Ordinal)) return;
            var value = Uri.UnescapeDataString(argument[6..]);
            if (!ValidId.IsMatch(value)) return;
            lock (ActivationLock)
            {
                var now = Environment.TickCount64;
                foreach (var key in RecentActivations.Where(x => now - x.Value > 2000).Select(x => x.Key).ToArray())
                    RecentActivations.Remove(key);
                if (RecentActivations.TryGetValue(value, out var prior) && now - prior <= 2000) return;
                if (RecentActivations.Count >= 64)
                    RecentActivations.Remove(RecentActivations.MinBy(x => x.Value).Key);
                if (bridge) Reply(new { type = "activate", event_id = value });
                else
                {
                    var path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "GlobalPulse.exe"));
                    if (!File.Exists(path)) return;
                    var start = new ProcessStartInfo(path) { UseShellExecute = false };
                    start.ArgumentList.Add("--activate");
                    start.ArgumentList.Add(value);
                    Process.Start(start);
                }
                RecentActivations[value] = now;
                Activation.Set();
            }
        }
        catch (Exception error) { Reply(new { type = "error", message = error.GetType().Name }); }
    }

    [STAThread]
    public static int Main(string[] args)
    {
        bridge = args.Contains("--bridge");
        if (bridge)
        {
            Console.SetIn(new StreamReader(Console.OpenStandardInput(), new System.Text.UTF8Encoding(false)));
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new System.Text.UTF8Encoding(false)) { AutoFlush = true });
        }
        var manager = AppNotificationManager.Default;
        try
        {
            if (args.Contains("--unregister")) { manager.UnregisterAll(); return 0; }
            manager.NotificationInvoked += (_, e) => HandleActivation(e);
            var icon = Path.Combine(AppContext.BaseDirectory, "pulse.png");
            if (File.Exists(icon)) manager.Register("Global Pulse", new Uri(icon));
            else manager.Register();
            // Register first. Depending on packaging/SDK, cold activation either
            // supplies AppNotification data here or Launch + a later COM callback.
            var initial = AppInstance.GetCurrent().GetActivatedEventArgs();
            if (initial?.Kind == ExtendedActivationKind.AppNotification && initial.Data is AppNotificationActivatedEventArgs notificationArgs)
                HandleActivation(notificationArgs);
            if (!bridge) { return Activation.Wait(TimeSpan.FromSeconds(20)) ? 0 : 2; }
            Reply(new { type = "ready", setting = manager.Setting.ToString() });
            string? line;
            while ((line = Console.ReadLine()) != null)
            {
                string alertId = "";
                if (line.Length > 16384) { Reply(new { type = "error", message = "Payload limit exceeded" }); continue; }
                try
                {
                    using var doc = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 8 });
                    var root = doc.RootElement;
                    if (Field(root, "command") == "exit") break;
                    if (Field(root, "command") != "notify") continue;
                    var id = Field(root, "event_id", 128);
                    alertId = Field(root, "alert_id", 128);
                    if (!ValidId.IsMatch(id)) throw new ArgumentException("Invalid event id");
                    if (!ValidId.IsMatch(alertId)) throw new ArgumentException("Invalid alert id");
                    var title = Escape(Field(root, "title", 150));
                    var details = Escape(Field(root, "details", 180));
                    var body = Escape(Field(root, "body", 350));
                    var launch = Escape("event=" + Uri.EscapeDataString(id));
                    var xml = $"<toast launch=\"{launch}\"><visual><binding template=\"ToastGeneric\"><text>{title}</text><text>{details}</text><text>{body}</text></binding></visual><actions><action content=\"View event\" arguments=\"{launch}\"/></actions></toast>";
                    var notification = new AppNotification(xml) { Tag = alertId[..Math.Min(alertId.Length, 64)], Group = "events" };
                    manager.Show(notification);
                    if (notification.Id == 0) throw new InvalidOperationException("Windows did not accept the notification");
                    // Submission is not proof that Windows displayed a visible toast.
                    Reply(new { type = "submitted", event_id = id, alert_id = alertId, id = notification.Id, setting = manager.Setting.ToString() });
                }
                catch (Exception error) { Reply(new { type = "error", alert_id = alertId, message = error.GetType().Name }); }
            }
            return 0;
        }
        catch (Exception error) { Reply(new { type = "error", message = error.GetType().Name, code = error.HResult }); return 1; }
        finally { try { manager.Unregister(); } catch { } }
    }
}
