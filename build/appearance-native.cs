using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

sealed class UpdateProgressWindow : Form {
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr handle, int attribute, ref int value, int size);

    private static readonly Color Background = Color.FromArgb(9, 22, 44);
    private static readonly Color Foreground = Color.FromArgb(242, 247, 255);
    private static readonly Color Muted = Color.FromArgb(173, 193, 220);
    private static readonly Color Accent = Color.FromArgb(101, 215, 244);

    private readonly Label heading, activity, percentage, hint;
    private readonly Meter meter;

    public UpdateProgressWindow(Icon icon, string versions, bool restart) {
        Text = "星译官 · 更新";
        Icon = icon;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ControlBox = false;
        MaximizeBox = false;
        MinimizeBox = false;
        BackColor = Background;
        ForeColor = Foreground;
        Font = new Font("Microsoft YaHei UI", 10);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(510, 218);

        var mark = new Panel { BackColor = Color.FromArgb(241, 183, 67), Bounds = new Rectangle(26, 28, 3, 26) };
        Controls.Add(mark);
        heading = AddLabel("星译官小包更新", 39, 22, 445, 37, Foreground, 18, FontStyle.Bold);
        if (!String.IsNullOrEmpty(versions)) AddLabel(versions, 40, 59, 444, 27, Muted, 10);

        activity = AddLabel("", 26, 98, 388, 37, Foreground, 11);
        activity.AccessibleName = "当前更新步骤";
        percentage = AddLabel("", 417, 98, 67, 37, Accent, 14, FontStyle.Bold);
        percentage.TextAlign = ContentAlignment.MiddleRight;
        percentage.AccessibleName = "整体更新进度";
        meter = new Meter { Bounds = new Rectangle(27, 143, 456, 8), AccessibleName = "整体更新进度" };
        Controls.Add(meter);
        hint = AddLabel(restart ? "更新完成后会自动重新打开星译官。" : "请等待更新完成。", 26, 165, 458, 29, Muted, 10);
    }

    private Label AddLabel(string text, int x, int y, int width, int height, Color color, float size, FontStyle style = FontStyle.Regular) {
        var label = new Label {
            Text = text, Bounds = new Rectangle(x, y, width, height),
            ForeColor = color, Font = new Font(Font.FontFamily, size, style),
            TextAlign = ContentAlignment.MiddleLeft, UseMnemonic = false
        };
        Controls.Add(label);
        return label;
    }

    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e);
        try {
            int dark = 1;
            DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int));
        } catch (EntryPointNotFoundException) { }
    }

    public void Report(string message, int? progress) {
        activity.Text = message;
        percentage.Text = progress.HasValue ? progress.Value + "%" : "";
        meter.Report(progress);
        if (progress == 100) {
            heading.Text = "更新完成";
            hint.Visible = false;
        }
    }

    private sealed class Meter : Control {
        private readonly Timer timer;
        private int? percentage;
        private int offset;

        public Meter() {
            DoubleBuffered = true;
            AccessibleRole = AccessibleRole.ProgressBar;
            timer = new Timer { Interval = 28 };
            timer.Tick += delegate { offset += Math.Max(1, Width / 80); Invalidate(); };
        }

        public void Report(int? progress) {
            if (percentage == progress && (progress.HasValue || timer.Enabled)) return;
            percentage = progress;
            AccessibleDescription = progress.HasValue ? progress.Value + "%" : "正在准备小包";
            timer.Enabled = !progress.HasValue;
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);
            using (var track = new SolidBrush(Color.FromArgb(44, 63, 94)))
            using (var fill = new SolidBrush(Accent)) {
                e.Graphics.FillRectangle(track, ClientRectangle);
                int width = percentage.HasValue ? Width * percentage.Value / 100 : Width / 4;
                int left = percentage.HasValue ? 0 : offset % (Width + width) - width;
                e.Graphics.FillRectangle(fill, left, 0, width, Height);
            }
        }

        protected override void Dispose(bool disposing) {
            if (disposing) timer.Dispose();
            base.Dispose(disposing);
        }
    }
}
