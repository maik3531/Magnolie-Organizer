using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace MagnolieOrganizer.Windows;

internal static class TrayAppearanceRenderer
{
    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyIcon(IntPtr icon);

    internal static Icon Create(Icon original, TrayAppearanceState state)
    {
        if (!Enum.IsDefined(state.Connection) || !Enum.IsDefined(state.Mode)) throw new ArgumentOutOfRangeException(nameof(state));
        using var bitmap = new Bitmap(256, 256);
        using (var g = Graphics.FromImage(bitmap))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            var color = state.Connection switch
            {
                TrayFlowerConnection.Notes => Color.White,
                TrayFlowerConnection.Kde => Color.FromArgb(247, 215, 119),
                TrayFlowerConnection.Both => Color.FromArgb(238, 152, 70),
                _ => Color.FromArgb(216, 178, 92)
            };
            if (state.Mode == TrayAppearanceMode.Phone)
            {
                using var leather = new SolidBrush(Color.FromArgb(85, 41, 28));
                using var paper = new SolidBrush(Color.FromArgb(233, 221, 189));
                using var gold = new Pen(Color.FromArgb(216, 178, 92), 6);
                using var outline = Rounded(57, 10, 142, 236, 23);
                g.FillPath(leather, outline); g.DrawPath(gold, outline);
                using var screen = Rounded(68, 34, 120, 183, 6);
                g.FillPath(paper, screen);
                g.DrawLine(gold, 108, 23, 148, 23); g.DrawLine(gold, 119, 232, 137, 232);
                Flower(g, Color.FromArgb(85, 41, 28));
            }
            else
            {
                // Keep every pixel outside the original central flower area.
                using var large = new Icon(original, new Size(256, 256));
                g.DrawIcon(large, new Rectangle(0, 0, 256, 256));
                if (state.Mode == TrayAppearanceMode.Camera || state.Connection != TrayFlowerConnection.None)
                {
                    using var leather = new LinearGradientBrush(new Rectangle(20, 16, 200, 222), Color.Black, Color.Black, LinearGradientMode.ForwardDiagonal);
                    leather.InterpolationColors = new ColorBlend { Positions = [0, .55f, 1],
                        Colors = [Color.FromArgb(122, 69, 48), Color.FromArgb(85, 41, 28), Color.FromArgb(54, 26, 16)] };
                    g.FillRectangle(leather, 79, 77, 84, 99);
                    if (state.Mode == TrayAppearanceMode.Camera)
                    {
                        using var pen = new Pen(color, 6) { LineJoin = LineJoin.Round };
                        g.DrawPolygon(pen, new Point[] { new(72,104), new(98,104), new(108,87), new(140,87), new(150,104), new(174,104), new(174,163), new(72,163) });
                        g.DrawEllipse(pen, 104, 113, 38, 38);
                    }
                    else Flower(g, color);
                }
            }
            if (state.Synchronizing)
            {
                using var arrows = new Pen(Color.FromArgb(247, 215, 119), 9) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round };
                g.DrawArc(arrows, 55, 60, 134, 134, 190, 135);
                g.DrawLines(arrows, new Point[] { new(176,65), new(176,95), new(149,85) });
                g.DrawArc(arrows, 55, 60, 134, 134, 10, 135);
                g.DrawLines(arrows, new Point[] { new(66,193), new(66,163), new(93,173) });
            }
        }
        var handle = bitmap.GetHicon();
        try { using var borrowed = Icon.FromHandle(handle); return (Icon)borrowed.Clone(); }
        finally { DestroyIcon(handle); }
    }

    private static GraphicsPath Rounded(float x, float y, float width, float height, float radius)
    {
        var path = new GraphicsPath(); var d = radius * 2;
        path.AddArc(x, y, d, d, 180, 90); path.AddArc(x + width - d, y, d, d, 270, 90);
        path.AddArc(x + width - d, y + height - d, d, d, 0, 90); path.AddArc(x, y + height - d, d, d, 90, 90);
        path.CloseFigure(); return path;
    }

    private static void Flower(Graphics g, Color color)
    {
        var saved = g.Save();
        try
        {
            g.TranslateTransform(121, 127.5f); g.ScaleTransform(1.9f, 1.9f); g.TranslateTransform(-32, -32);
            using var pen = new Pen(color, 2.6f) { LineJoin = LineJoin.Round, StartCap = LineCap.Round, EndCap = LineCap.Round };
            float[][] curves = [ [26,26,26,16,32,9,38,16,38,26], [23,32,15,26,13,17,22,17,30,24],
                [41,32,49,26,51,17,42,17,34,24], [24,40,21,47,22,54,28,51,32,44], [40,40,43,47,42,54,36,51,32,44] ];
            foreach (var c in curves)
            {
                using var path = new GraphicsPath();
                path.AddBezier(32,34,c[0],c[1],c[2],c[3],c[4],c[5]);
                path.AddBezier(c[4],c[5],c[6],c[7],c[8],c[9],32,34);
                path.CloseFigure(); g.DrawPath(pen, path);
            }
        }
        finally { g.Restore(saved); }
    }
}
