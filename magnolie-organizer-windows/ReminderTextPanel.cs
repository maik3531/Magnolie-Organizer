namespace MagnolieOrganizer.Windows;

// A reminder remains readable by wheel and keyboard without a permanent native
// scrollbar. The narrow thumb is shown only while the pointer is over the text.
internal sealed class ReminderTextPanel : Panel
{
    private readonly Label body = new() { AutoSize = false, UseMnemonic = false };
    private readonly Panel thumb = new() { Width = 3, Visible = false, Cursor = Cursors.Hand };
    private int offset, contentHeight, dragY, dragOffset;
    private bool dragging;

    internal ReminderTextPanel()
    {
        TabStop = true; AccessibleRole = AccessibleRole.StaticText;
        SetStyle(ControlStyles.Selectable | ControlStyles.OptimizedDoubleBuffer, true);
        Controls.Add(body); Controls.Add(thumb); thumb.BringToFront();
        thumb.BackColor = Color.FromArgb(171, 148, 104);
        foreach (var control in new Control[] { this, body, thumb })
        {
            control.MouseEnter += (_, _) => UpdateThumb();
            control.MouseLeave += (_, _) => UpdateThumb();
        }
        body.MouseDown += (_, _) => Focus();
        thumb.MouseDown += (_, e) =>
        {
            if (e.Button != MouseButtons.Left) return;
            Focus(); dragging = true; dragY = Cursor.Position.Y; dragOffset = offset; thumb.Capture = true;
        };
        thumb.MouseMove += (_, _) =>
        {
            if (dragging) ScrollTo(dragOffset + (Cursor.Position.Y - dragY) *
                Math.Max(1, contentHeight - ClientSize.Height) / Math.Max(1, ClientSize.Height - thumb.Height));
        };
        thumb.MouseUp += (_, _) => { dragging = false; thumb.Capture = false; UpdateThumb(); };
        thumb.MouseCaptureChanged += (_, _) => { if (!thumb.Capture) { dragging = false; UpdateThumb(); } };
    }

    [System.Diagnostics.CodeAnalysis.AllowNull]
    public override string Text
    {
        get => base.Text;
        set { base.Text = value; if (body is not null) { body.Text = value; AccessibleDescription = value; LayoutText(); } }
    }

    protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); if (body is not null) { body.Font = Font; LayoutText(); } }
    protected override void OnForeColorChanged(EventArgs e) { base.OnForeColorChanged(e); if (body is not null) body.ForeColor = ForeColor; }
    protected override void OnBackColorChanged(EventArgs e) { base.OnBackColorChanged(e); if (body is not null) body.BackColor = BackColor; }
    protected override void OnSizeChanged(EventArgs e) { base.OnSizeChanged(e); if (body is not null) LayoutText(); }
    protected override void OnMouseWheel(MouseEventArgs e)
    {
        var lines = SystemInformation.MouseWheelScrollLines;
        var distance = lines < 0 ? ClientSize.Height : Math.Max(1, lines) * Font.Height;
        ScrollTo(offset - e.Delta * distance / SystemInformation.MouseWheelScrollDelta);
        if (e is HandledMouseEventArgs handled) handled.Handled = true;
        base.OnMouseWheel(e);
    }
    protected override bool IsInputKey(Keys keyData) =>
        (keyData & Keys.KeyCode) is Keys.Up or Keys.Down or Keys.PageUp or Keys.PageDown or Keys.Home or Keys.End || base.IsInputKey(keyData);
    protected override void OnKeyDown(KeyEventArgs e)
    {
        var next = e.KeyCode switch
        {
            Keys.Up => offset - Font.Height, Keys.Down => offset + Font.Height,
            Keys.PageUp => offset - ClientSize.Height, Keys.PageDown => offset + ClientSize.Height,
            Keys.Home => 0, Keys.End => contentHeight, _ => offset
        };
        if (next != offset) { ScrollTo(next); e.Handled = true; }
        base.OnKeyDown(e);
    }

    private void LayoutText()
    {
        var width = Math.Max(1, ClientSize.Width - Math.Max(8, DeviceDpi * 8 / 96));
        contentHeight = TextRenderer.MeasureText(body.Text, Font, new Size(width, int.MaxValue),
            TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl | TextFormatFlags.NoPrefix).Height;
        body.Size = new Size(width, Math.Max(Font.Height, contentHeight));
        thumb.Width = Math.Max(2, DeviceDpi * 3 / 96);
        ScrollTo(offset);
    }

    private void ScrollTo(int value)
    {
        offset = Math.Clamp(value, 0, Math.Max(0, contentHeight - ClientSize.Height));
        body.Location = new Point(0, -offset); UpdateThumb();
    }

    private void UpdateThumb()
    {
        if (thumb is null) return;
        var overflow = contentHeight > ClientSize.Height && ClientSize.Height > 0;
        thumb.Visible = overflow && (dragging || IsHandleCreated && ClientRectangle.Contains(PointToClient(Cursor.Position)));
        if (!overflow) return;
        thumb.Height = Math.Min(ClientSize.Height, Math.Max(DeviceDpi * 16 / 96, ClientSize.Height * ClientSize.Height / contentHeight));
        thumb.Location = new Point(Math.Max(0, ClientSize.Width - thumb.Width),
            offset * (ClientSize.Height - thumb.Height) / Math.Max(1, contentHeight - ClientSize.Height));
    }
}
