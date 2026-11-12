from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from engine import (Cancelled, PRESETS, QUALITIES, RESOLUTIONS, SPEEDS, MOTION_MODES, MOBILE_RESOLUTIONS, MOBILE_FRAME_RATES,
                    Settings, analyze_source, export_advice, export_video, mobile_settings, output_dimensions, preview_pair, probe)
from quality_method import prepare_quality_fps

BG = "#101116"
PANEL = "#191b23"
TEXT = "#f3f4f8"
MUTED = "#a2a6b8"
ACCENT = "#7ef5cf"
METHOD = "Quality + FPS (preserve video)"
ENHANCE = "Enhance + export"
MOBILE = "Mobile compatible (recommended)"


class DetailView(tk.Toplevel):
    def __init__(self, owner, pair):
        super().__init__(owner)
        self.title("100% detail • Drag to pan, move the divider to compare")
        self.geometry("1000x720")
        self.configure(bg=PANEL)
        self.pair = pair
        self.split = tk.DoubleVar(value=50)
        tk.Label(self, text="SOURCE  ←  comparison divider  →  ENHANCED     |     1 image pixel = 1 display pixel",
                 bg=PANEL, fg=TEXT).pack(pady=10)
        tk.Scale(self, variable=self.split, from_=0, to=100, orient="horizontal", bg=PANEL, fg=TEXT,
                 highlightthickness=0, command=self.draw).pack(fill="x", padx=20)
        area = tk.Frame(self, bg=PANEL)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        horizontal = ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        vertical = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        area.grid_rowconfigure(0, weight=1)
        area.grid_columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<ButtonPress-1>", lambda event: self.canvas.scan_mark(event.x, event.y))
        self.canvas.bind("<B1-Motion>", lambda event: self.canvas.scan_dragto(event.x, event.y, gain=1))
        self.draw()

    def draw(self, value=None):
        if not hasattr(self, "canvas"):
            return
        left, right = self.pair
        image = left.copy()
        divider = round(image.width * self.split.get() / 100)
        image.paste(right.crop((divider, 0, image.width, image.height)), (divider, 0))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.create_line(divider, 0, divider, image.height, fill=ACCENT, width=2)
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))


class QualityStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Qual 2.3 • 4K and Source FPS Export")
        self.geometry("1220x840")
        self.minsize(1050, 760)
        self.configure(bg=BG)
        self.source = None
        self.info = None
        self.output = None
        self.busy = False
        self.exporting = False
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.photos = []
        self.preview_pair = None
        self.analysis = None
        self.preview_directory = tempfile.TemporaryDirectory(prefix="qual-preview-", ignore_cleanup_errors=True)
        self.preview_serial = 0
        self.workflow = tk.StringVar(value=MOBILE)
        self.mobile_fps = tk.StringVar(value="Keep source (normal speed)")
        self.mobile_resolution = tk.StringVar(value="Keep original size")
        self.preview_note = tk.StringVar(value="Choose a video to inspect it.")
        self.advice = tk.StringVar(value="Choose a video, then analyze it for source-based recommendations.")
        self.deband = tk.BooleanVar(value=False)
        self.sharpening = tk.StringVar(value="Adaptive")
        self.speed = tk.StringVar(value="Slow / better compression")
        self.motion = tk.StringVar(value=MOTION_MODES[0])
        self.crop_x = tk.DoubleVar(value=0.5)
        self.crop_y = tk.DoubleVar(value=0.5)
        self.export_started = None
        self.last_detail = None
        self.report_path = None
        self.status = tk.StringVar(value="Choose a video to get started.")
        self.file_label = tk.StringVar(value="No video selected")
        self.metadata = tk.StringVar(value="MP4, MOV, MKV, WebM and more")
        self.preset = tk.StringVar(value="Balanced")
        self.resolution = tk.StringVar(value="1080 × 1920")
        self.framing = tk.StringVar(value="Fit with black bars")
        self.fps = tk.StringVar(value="Keep source")
        self.quality = tk.StringVar(value="High quality")
        self.position = tk.DoubleVar(value=0)
        self.adjustments = {key: tk.DoubleVar(value=value) for key, value in PRESETS["Balanced"].items()}
        self.controls = []
        self.edit_controls = []
        self.scroll_panels = []
        self._theme()
        self._build()
        for variable in [*self.adjustments.values(), self.resolution, self.framing, self.fps, self.quality,
                         self.sharpening, self.deband, self.motion, self.crop_x, self.crop_y, self.mobile_fps, self.mobile_resolution]:
            variable.trace_add("write", self._settings_changed)
        self.workflow.trace_add("write", self._workflow_changed)
        self._workflow_changed()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground="#242733", background="#303341", foreground=TEXT,
                        arrowcolor=ACCENT, padding=4, borderwidth=0)
        style.map("TCombobox", fieldbackground=[("readonly", "#242733")], foreground=[("readonly", TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor="#292c38", background=ACCENT, borderwidth=0)
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background="#292c38", foreground=MUTED, padding=(10, 8))
        style.map("TNotebook.Tab", background=[("selected", "#34394a")], foreground=[("selected", ACCENT)])
        self.option_add("*TCombobox*Listbox.background", "#242733")
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*Font", "{Segoe UI} 10")

    def label(self, parent, text=None, color=TEXT, size=10, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kwargs)

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=ACCENT if primary else "#2b2e3b",
                         fg="#10231e" if primary else TEXT, activebackground="#a4ffe3" if primary else "#3b4051",
                         activeforeground="#10231e" if primary else TEXT, relief="flat", bd=0,
                         padx=18, pady=10, cursor="hand2", font=("Segoe UI", 10, "bold"),
                         disabledforeground="#747987")

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(18, 14))
        self.label(header, "qual", color=ACCENT, size=28, bold=True).pack(side="left")
        self.label(header, "  /  QUALITY STUDIO  2.3", size=11, bold=True).pack(side="left", padx=10)
        self.label(header, "LOCAL PROCESSING  •  YOUR FILES STAY HERE", color=MUTED, size=9).pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=28)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=PANEL, padx=20, pady=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = tk.Frame(body, bg=PANEL, padx=12, pady=12, width=365)
        right.grid(row=0, column=1, sticky="ns")

        source_row = tk.Frame(left, bg=PANEL)
        source_row.pack(fill="x")
        self.label(source_row, "01  YOUR VIDEO", color=MUTED, size=9, bold=True).pack(side="left")
        self.choose_btn = self.button(source_row, "Choose video", self.choose_video)
        self.choose_btn.pack(side="right")
        self.label(left, textvariable=self.file_label, size=12, bold=True, anchor="w", wraplength=540).pack(fill="x", pady=(8, 2))
        self.label(left, textvariable=self.metadata, color=MUTED, anchor="w", wraplength=530, justify="left").pack(fill="x")
        preview_header = tk.Frame(left, bg=PANEL)
        preview_header.pack(fill="x", pady=(20, 8))
        self.label(preview_header, "SOURCE", color=MUTED, size=9, bold=True).pack(side="left", expand=True)
        self.after_label = self.label(preview_header, "UNCHANGED VIDEO", color=ACCENT, size=9, bold=True)
        self.after_label.pack(side="left", expand=True)
        self.canvas = tk.Canvas(left, bg="#0d0e12", highlightthickness=0, height=190)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw())
        self._draw()
        timeline = tk.Frame(left, bg=PANEL)
        timeline.pack(fill="x", pady=(10, 0))
        self.label(timeline, "Preview frame", color=MUTED, size=9).pack(side="left")
        self.timeline = tk.Scale(timeline, from_=0, to=1, resolution=0.1, variable=self.position,
                                 orient="horizontal", bg=PANEL, fg=MUTED, highlightthickness=0,
                                 troughcolor="#303442", activebackground=ACCENT, length=230,
                                 showvalue=False, bd=0)
        self.timeline.pack(side="left", fill="x", expand=True, padx=10)
        self.controls.append(self.timeline)
        self.timeline.bind("<ButtonRelease-1>", lambda event: self.preview_note.set("Frame changed. Refresh to see this moment."))
        self.preview_btn = self.button(left, "Refresh before / after", self.refresh_preview)
        self.preview_btn.pack(fill="x", pady=(8, 6))
        preview_actions = tk.Frame(left, bg=PANEL)
        preview_actions.pack(fill="x")
        self.detail_btn = self.button(preview_actions, "100% detail", self.show_detail)
        self.detail_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.clip_btn = self.button(preview_actions, "Make 3s sample", self.make_sample)
        self.clip_btn.pack(side="left", fill="x", expand=True)
        self.label(left, textvariable=self.preview_note, color=MUTED, size=9, wraplength=530, justify="left").pack(anchor="w", pady=(7, 0))

        self.notebook = ttk.Notebook(right, width=350, height=440)
        self.notebook.pack(fill="both", expand=True)
        method_tab = self.tab("Method")
        look = self.tab("Look")
        output_tab = self.tab("Export")
        advice_tab = self.tab("Advice")
        self.combo(method_tab, "Choose your workflow", self.workflow, [MOBILE, ENHANCE, METHOD])
        self.label(method_tab, "Mobile compatible", color=ACCENT, size=15, bold=True).pack(anchor="w", pady=(18, 8))
        self.label(method_tab, "Exports a standard MP4 with your original resolution, one AAC stereo track, and no special audio tail. Keep your source FPS, including 120 fps, at normal speed, or choose a constant 30/60 fps export.",
                   wraplength=305, justify="left").pack(anchor="w")
        self.mobile_resolution_box = self.combo(method_tab, "Mobile resolution", self.mobile_resolution, list(MOBILE_RESOLUTIONS))
        self.mobile_fps_box = self.combo(method_tab, "Mobile frame rate", self.mobile_fps,
                                          list(MOBILE_FRAME_RATES))
        self.label(method_tab, "Keep source preserves frame timestamps and playback speed; it also retains variable frame timing when present. It does not create frames or turn camera slow-motion footage into real-time footage. Automatic limits output to 30/60 fps. HDR is converted to SDR. 4K/120 fps needs suitable playback hardware, and TikTok may deliver a different version. If phone playback lags, compare with a 60 fps export.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w", pady=(10, 4))
        self.label(method_tab, "Quality + FPS • experimental", color=MUTED, size=12, bold=True).pack(anchor="w", pady=(18, 8))
        self.label(method_tab, "Prepare an existing edit without re-encoding its video. The local SL/SR method adds an audio tail and a stereo duplicate, while retaining the source's encoded picture and frame timing, including 120 fps.",
                   wraplength=305, justify="left").pack(anchor="w")
        credit = self.label(method_tab, "Powered by CompressBase ↗", color=ACCENT, bold=True, cursor="hand2")
        credit.pack(anchor="w", pady=(12, 5))
        credit.bind("<Button-1>", lambda event: webbrowser.open("https://compressbase.com/method-api"))
        self.label(method_tab, "Runs offline with the bundled public helper. Audio is converted to AAC stereo first. Its special audio layout, tail, and preserved high frame rate may be incompatible with some playback paths. If phone playback lags, export Mobile compatible from your original video instead.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w", pady=(0, 12))
        self.label(method_tab, "Every prepared file gets video-packet, frame-timing, and decode checks, plus a JSON report beside the MP4. TikTok playback quality and FPS are not guaranteed.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w")
        self.label(method_tab, "Want to change the picture?", bold=True).pack(anchor="w", pady=(20, 5))
        self.label(method_tab, "Select Enhance + export to use the Look and Export tabs. You can then import that enhanced MP4 and run Quality + FPS on it.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w")
        self.report_btn = self.button(method_tab, "Open verification report", self.open_report)
        self.report_btn.pack(fill="x", pady=(15, 5))
        self.report_btn.config(state="disabled")

        before_edit_controls = len(self.controls)
        preset_box = self.combo(look, "Picture preset", self.preset, list(PRESETS))
        preset_box.bind("<<ComboboxSelected>>", self.apply_preset)
        self.combo(look, "Sharpening algorithm", self.sharpening, ["Adaptive", "Classic"])
        self.label(look, "Fine-tune the look", size=11, bold=True).pack(anchor="w", pady=(12, 5))
        for key, title, low, high, step in [
            ("sharpen", "Sharpen", 0, 1.0, 0.05),
            ("denoise", "Noise reduction", 0, 5, 0.1),
            ("contrast", "Contrast", 0.8, 1.3, 0.01),
            ("saturation", "Color", 0, 1.5, 0.01),
            ("brightness", "Brightness", -0.1, 0.1, 0.005),
            ("gamma", "Shadow / gamma", 0.8, 1.3, 0.01),
        ]:
            row = tk.Frame(look, bg=PANEL)
            row.pack(fill="x", pady=1)
            self.label(row, title, color=MUTED, size=9, width=15, anchor="w").pack(side="left")
            self.label(row, textvariable=self.adjustments[key], color=TEXT, size=9, width=5, anchor="e").pack(side="right")
            scale = tk.Scale(row, from_=low, to=high, resolution=step, variable=self.adjustments[key],
                             orient="horizontal", bg=PANEL, fg=TEXT, highlightthickness=0,
                             troughcolor="#303442", activebackground=ACCENT, length=125, showvalue=False,
                             bd=0, sliderlength=16, width=8, font=("Segoe UI", 8),
                             command=lambda value: self.preset.set("Custom"))
            scale.pack(side="right", fill="x", expand=True)
            self.controls.append(scale)
        deband = tk.Checkbutton(look, text="Smooth gradient banding (gentle)", variable=self.deband, bg=PANEL, fg=TEXT,
                               selectcolor="#303442", activebackground=PANEL, activeforeground=TEXT, bd=0, highlightthickness=0)
        deband.pack(anchor="w", pady=(14, 4))
        self.controls.append(deband)
        self.label(look, "Start gently. Noise reduction and gradient smoothing can soften textures. HDR is automatically tone-mapped to SDR; interlaced footage is deinterlaced.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w", pady=12)

        self.combo(output_tab, "Canvas", self.resolution, ["1080 × 1920", "720 × 1280", "2160 × 3840 (4K)", "Original size"])
        self.combo(output_tab, "Framing", self.framing, ["Fit with black bars", "Center crop"])
        for variable, title in ((self.crop_x, "Crop left / right"), (self.crop_y, "Crop up / down")):
            row = tk.Frame(output_tab, bg=PANEL)
            row.pack(fill="x", pady=3)
            self.label(row, title, color=MUTED, size=9, width=17, anchor="w").pack(side="left")
            scale = tk.Scale(row, variable=variable, from_=0, to=1, resolution=0.01, orient="horizontal", bg=PANEL,
                             fg=TEXT, showvalue=False, highlightthickness=0, troughcolor="#303442", length=145, bd=0, width=8)
            scale.pack(side="left", fill="x", expand=True)
            self.controls.append(scale)
        options = tk.Frame(output_tab, bg=PANEL)
        options.pack(fill="x")
        first = tk.Frame(options, bg=PANEL)
        first.pack(side="left", fill="x", expand=True, padx=(0, 8))
        second = tk.Frame(options, bg=PANEL)
        second.pack(side="left", fill="x", expand=True)
        self.combo(first, "Frame rate", self.fps, ["Keep source", "30 fps", "60 fps"], width=12)
        self.combo(second, "Compression", self.quality, list(QUALITIES), width=14)
        self.combo(output_tab, "Encoding speed", self.speed, list(SPEEDS))
        self.combo(output_tab, "Motion", self.motion, list(MOTION_MODES))
        self.label(output_tab, "Interpolation creates in-between frames and can warp edges. Use the sample clip to check motion. A 4K export cannot add missing source detail.",
                   color=MUTED, size=9, wraplength=305, justify="left").pack(anchor="w", pady=10)
        self.label(output_tab, "MP4  /  H.264  /  AAC  /  SDR BT.709", color=ACCENT, size=9, bold=True).pack(anchor="w", pady=(5, 0))
        self.edit_controls = self.controls[before_edit_controls:]

        self.analyze_btn = self.button(advice_tab, "Analyze 3 source frames", self.analyze)
        self.analyze_btn.pack(fill="x", pady=(6, 8))
        self.recommend_btn = self.button(advice_tab, "Use recommendations in Enhance mode", self.use_recommendations)
        self.recommend_btn.pack(fill="x", pady=(0, 12))
        self.label(advice_tab, textvariable=self.advice, color=MUTED, size=10, wraplength=305, justify="left").pack(anchor="w")
        self.bind("<MouseWheel>", self._wheel)

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=28, pady=(14, 18))
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(fill="x", pady=(0, 10))
        actions = tk.Frame(footer, bg=BG)
        actions.pack(fill="x")
        self.label(actions, textvariable=self.status, color=MUTED, anchor="w", wraplength=550).pack(side="left", fill="x", expand=True)
        self.cancel_btn = self.button(actions, "Cancel", self.cancel_export)
        self.cancel_btn.pack(side="right", padx=(8, 0))
        self.cancel_btn.config(state="disabled")
        self.export_btn = self.button(actions, "Export mobile MP4 →", self.export, primary=True)
        self.export_btn.pack(side="right", padx=(8, 0))
        self.folder_btn = self.button(actions, "Open output folder", self.open_output)
        self.folder_btn.pack(side="right", padx=(8, 0))
        self.folder_btn.config(state="disabled")
        self.label(footer, "Local processing • Original files are preserved • Quality + FPS retains encoded video; Enhance mode changes it • TikTok controls final playback quality.",
                   color=MUTED, size=8, wraplength=1050).pack(anchor="w", pady=(12, 0))
        self._update_controls()

    def tab(self, title):
        page = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(page, text=title)
        canvas = tk.Canvas(page, bg=PANEL, highlightthickness=0, width=325, height=430)
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=PANEL, padx=5, pady=5)
        handle = canvas.create_window(0, 0, anchor="nw", window=inner)
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(handle, width=event.width))
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        self.scroll_panels.append((page, canvas))
        return inner

    def _wheel(self, event):
        for page, canvas in self.scroll_panels:
            if str(event.widget).startswith(str(page)):
                canvas.yview_scroll(-int(event.delta / 120), "units")
                break

    def combo(self, parent, title, variable, values, width=28):
        self.label(parent, title, color=MUTED, size=9).pack(anchor="w", pady=(8, 3))
        box = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        box.pack(fill="x")
        self.controls.append(box)
        return box

    def settings(self):
        return Settings(resolution=self.resolution.get(), framing=self.framing.get(), fps=self.fps.get(),
                        quality=self.quality.get(), sharpening=self.sharpening.get(), deband=self.deband.get(),
                        speed=self.speed.get(), motion=self.motion.get(), crop_x=self.crop_x.get(), crop_y=self.crop_y.get(),
                        **{key: value.get() for key, value in self.adjustments.items()})

    def preview_settings(self):
        if self.workflow.get() == MOBILE and self.info:
            return mobile_settings(self.info, self.mobile_fps.get(), self.mobile_resolution.get())
        return self.settings() if self.workflow.get() == ENHANCE else Settings(
            resolution="Original size", sharpen=0, denoise=0, contrast=1, saturation=1, brightness=0, gamma=1)

    def _settings_changed(self, *args):
        if self.source and self.workflow.get() != METHOD:
            self.preview_note.set("Settings changed. Refresh the comparison or make a sample clip.")
            self._update_advice()

    def _workflow_changed(self, *args):
        self.after_label.config(text={ENHANCE: "ENHANCED", METHOD: "UNCHANGED VIDEO", MOBILE: "MOBILE EXPORT"}[self.workflow.get()])
        self.export_btn.config(text={ENHANCE: "Export enhanced MP4 →", METHOD: "Prepare Quality + FPS →", MOBILE: "Export mobile MP4 →"}[self.workflow.get()])
        self.preview_pair = None
        self._draw()
        self.preview_note.set("Workflow changed. Refresh to see its preview.")
        self._update_controls()
        self._update_advice()

    def _update_advice(self):
        notes = list(self.analysis.notes) if self.analysis else []
        if self.info and self.workflow.get() == ENHANCE:
            notes += export_advice(self.info, self.settings())
        if self.info and self.workflow.get() == METHOD:
            notes += [f"Quality + FPS keeps the source's {self.info.width} × {self.info.height} video and {self.info.fps:g} fps. Look and Export adjustments apply only in Enhance mode.",
                      "An audio tail can make the container about 0.35 seconds longer. A stereo duplicate is included for players that do not support the special audio layout."]
        if self.info and self.workflow.get() == MOBILE:
            settings = mobile_settings(self.info, self.mobile_fps.get(), self.mobile_resolution.get())
            width, height = output_dimensions(settings, self.info)
            cadence = f"source {self.info.fps:g} fps with original frame timing" if settings.fps == "Keep source" else f"constant {settings.fps}"
            notes += [f"Mobile export: {width} × {height}, {cadence}, H.264, and one AAC stereo track when audio exists.",
                      "Frame conversion samples the original timeline, preserving normal playback duration. It does not stretch the picture to match a different FPS label.",
                      "Use the original edit when possible. A previously prepared file can also be converted; its clean stereo track is preferred and its extra audio tail is trimmed to the video end.",
                      "Test this file directly on the phone, then upload it for a comparison. Local checks cannot verify TikTok's mobile playback."]
        self.advice.set("\n\n".join(dict.fromkeys(notes)) or "Analyze the source for recommendations.")

    def apply_preset(self, event=None):
        for key, value in PRESETS[self.preset.get()].items():
            self.adjustments[key].set(value)

    def _update_controls(self):
        state = "disabled" if self.busy else "normal"
        self.choose_btn.config(state=state)
        self.preview_btn.config(state="normal" if self.source and not self.busy else "disabled")
        self.export_btn.config(state="normal" if self.source and not self.busy else "disabled")
        self.detail_btn.config(state="normal" if self.source and not self.busy else "disabled")
        self.clip_btn.config(state="normal" if self.source and not self.busy and self.workflow.get() != METHOD else "disabled")
        self.analyze_btn.config(state="normal" if self.source and not self.busy else "disabled")
        self.recommend_btn.config(state="normal" if self.analysis and not self.busy else "disabled")
        for control in self.controls:
            disabled = self.busy or (control in self.edit_controls and self.workflow.get() != ENHANCE) or (control in (self.mobile_fps_box, self.mobile_resolution_box) and self.workflow.get() != MOBILE)
            control.configure(state="disabled" if disabled else "readonly" if isinstance(control, ttk.Combobox) else "normal")

    def _work(self, task):
        self.busy = True
        self._update_controls()

        def run():
            try:
                task()
            except Cancelled:
                self.events.put(("cancelled", None))
            except Exception as error:
                self.events.put(("error", str(error)))
            finally:
                self.events.put(("idle", None))
        threading.Thread(target=run, daemon=True).start()

    def choose_video(self):
        selected = filedialog.askopenfilename(title="Choose your original video", filetypes=[
            ("Videos", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.mts"), ("All files", "*.*")])
        if not selected:
            return
        path = Path(selected)
        self.status.set("Reading video and building a preview…")
        settings = self.preview_settings()
        workflow, mobile_fps, mobile_resolution = self.workflow.get(), self.mobile_fps.get(), self.mobile_resolution.get()

        def load():
            info = probe(path)
            self.events.put(("loaded", (path, info)))
            moment = min(info.duration / 3, 2)
            chosen = mobile_settings(info, mobile_fps, mobile_resolution) if workflow == MOBILE else settings
            self.events.put(("preview", preview_pair(path, chosen, moment, info)))
        self._work(load)

    def refresh_preview(self):
        if self.busy or not self.source:
            return
        path, settings, moment, info = self.source, self.preview_settings(), self.position.get(), self.info
        self.status.set("Rendering the selected frame with your settings…")

        def render():
            pair = preview_pair(path, settings, moment, info)
            self.events.put(("preview", pair))
        self._work(render)

    def show_detail(self):
        if self.busy or not self.source:
            return
        path, settings, moment, info = self.source, self.preview_settings(), self.position.get(), self.info
        self.status.set("Rendering full-resolution frames for 100% detail comparison…")

        def render():
            self.events.put(("detail", preview_pair(path, settings, moment, info, full_size=True)))
        self._work(render)

    def analyze(self):
        if self.busy or not self.source:
            return
        path, info = self.source, self.info
        self.status.set("Sampling three frames to recommend conservative settings…")
        self._work(lambda: self.events.put(("analysis", analyze_source(path, info))))

    def use_recommendations(self):
        if self.busy or not self.analysis:
            return
        settings = self.analysis.recommended
        self.workflow.set(ENHANCE)
        self.preset.set("Recommended")
        for key, variable in self.adjustments.items():
            variable.set(getattr(settings, key))
        for key in ("resolution", "framing", "fps", "quality", "sharpening", "deband", "speed", "motion", "crop_x", "crop_y"):
            getattr(self, key).set(getattr(settings, key))
        self._update_advice()
        self.refresh_preview()

    def make_sample(self):
        if self.busy or not self.source or self.workflow.get() == METHOD:
            return
        self.preview_serial += 1
        destination = Path(self.preview_directory.name) / f"sample-{self.preview_serial}.mp4"
        source, info, settings = self.source, self.info, self.preview_settings()
        start = max(0, min(self.position.get(), self.info.duration - 0.1))
        self._start_export("Rendering a short sample with your export settings…")

        def render():
            export_video(source, destination, info, settings, self.cancel_event,
                         lambda value: self.events.put(("progress", value)), start=start, duration=3)
            self.events.put(("sample", destination))
        self._work(render)

    def _start_export(self, message):
        self.cancel_event.clear()
        self.exporting = True
        self.export_started = time.monotonic()
        self.progress["value"] = 0
        self.cancel_btn.config(state="normal")
        self.status.set(message)

    def _draw(self):
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if not self.preview_pair:
            self.canvas.create_text(width / 2, height / 2 - 15, text="A clearer next upload.", fill=TEXT,
                                    font=("Segoe UI", 18, "bold"))
            self.canvas.create_text(width / 2, height / 2 + 20, text="Choose a video to compare your quality method.",
                                    fill=MUTED, font=("Segoe UI", 10))
            return
        self.photos = []
        self.canvas.create_line(width / 2, 12, width / 2, height - 12, fill="#303442")
        for index, original in enumerate(self.preview_pair):
            frame = original.copy()
            frame.thumbnail((max(1, width // 2 - 24), max(1, height - 24)), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(frame)
            self.photos.append(photo)
            self.canvas.create_image(width * (0.25 + index * 0.5), height / 2, image=photo)

    def export(self):
        if self.busy or not self.source:
            return
        method = self.workflow.get() == METHOD
        mobile = self.workflow.get() == MOBILE
        suffix = "_quality_fps.mp4" if method else "_mobile.mp4" if mobile else "_qual.mp4"
        path = filedialog.asksaveasfilename(title="Save prepared video" if method else "Save mobile video" if mobile else "Save enhanced video", initialdir=str(self.source.parent),
                    initialfile=self.source.stem + suffix, defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")])
        if not path:
            return
        destination = Path(path)
        if destination.resolve() == self.source.resolve():
            messagebox.showerror("Preserve your original", "Choose a different filename for your export.")
            return
        source, info, settings = self.source, self.info, self.preview_settings()
        self._start_export("Preparing Quality + FPS…" if method else "Exporting… You can keep using your computer.")

        def render():
            if method:
                prepare_quality_fps(source, destination, info, self.cancel_event,
                                    lambda value: self.events.put(("progress", value)),
                                    lambda value: self.events.put(("status", value)))
            else:
                export_video(source, destination, info, settings, self.cancel_event,
                             lambda value: self.events.put(("progress", value)))
            self.events.put(("complete", destination))
        self._work(render)

    def cancel_export(self):
        self.cancel_event.set()
        self.status.set("Cancelling and removing the unfinished export…")
        self.cancel_btn.config(state="disabled")

    def open_output(self):
        if self.output:
            self.open_local(self.output.parent)

    def open_report(self):
        if self.report_path and self.report_path.is_file():
            self.open_local(self.report_path)

    def open_local(self, path):
        try:
            os.startfile(str(path))
        except OSError as error:
            self.status.set(f"Saved file: {path}")
            messagebox.showinfo("Open the saved file", f"The file is saved at:\n{path}\n\nWindows could not open it automatically: {error}")

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "loaded":
                    self.source, self.info = value
                    self.analysis = None
                    self.report_path = None
                    self.report_btn.config(state="disabled")
                    self.preview_pair = None
                    self.progress["value"] = 0
                    self._draw()
                    self.file_label.set(self.source.name)
                    info = self.info
                    self.metadata.set(f"{info.width} × {info.height}  •  {info.fps:g} fps  •  {info.duration:.1f}s  •  {self.source.stat().st_size / 1_000_000:.1f} MB  •  {info.codec.upper()}  •  {'HDR' if info.hdr else 'SDR'}")
                    self.timeline.config(to=max(0, info.duration - 0.1))
                    self.position.set(min(info.duration / 3, 2))
                    self._update_advice()
                elif kind == "preview":
                    self.preview_pair = value
                    self._draw()
                    self.status.set("Preview ready. Fine-tune your settings or export the full video.")
                    self.preview_note.set("Matched framing • HDR shown as SDR for comparison • Still preview excludes motion interpolation.")
                elif kind == "detail":
                    self.last_detail = DetailView(self, value)
                    if self.state() == "withdrawn":
                        self.last_detail.withdraw()
                    self.status.set("100% detail view ready. Drag to pan and move the comparison divider.")
                elif kind == "analysis":
                    self.analysis = value
                    self._update_advice()
                    self.status.set("Analysis ready. See Advice; recommendations are optional.")
                elif kind == "status":
                    self.status.set(value)
                elif kind == "sample":
                    self.output = value
                    self.folder_btn.config(state="normal")
                    self.status.set(f"Sample saved: {value.name}. Opening in your default video player…")
                    self.open_local(value)
                elif kind == "progress":
                    self.progress["value"] = value * 100
                    if self.workflow.get() != METHOD:
                        elapsed = time.monotonic() - self.export_started if self.export_started else 0
                        estimate = f" • about {elapsed * (1-value) / value:.0f}s left" if 0.02 < value < 1 else ""
                        self.status.set(f"Exporting… {value:.0%}{estimate}")
                elif kind == "complete":
                    self.output = value
                    self.folder_btn.config(state="normal")
                    size = value.stat().st_size / 1_000_000
                    if self.workflow.get() == METHOD:
                        self.report_path = value.with_suffix(".quality-fps.json")
                        self.report_btn.config(state="normal")
                    self.status.set(f"Saved: {value.name} • {size:.1f} MB" + (" • Video verified" if self.workflow.get() == METHOD else ""))
                elif kind == "cancelled":
                    self.progress["value"] = 0
                    self.status.set("Export cancelled. Your original video is safe.")
                elif kind == "error":
                    self.preview_note.set("This operation failed. Refresh the preview after correcting the issue.")
                    self.status.set("Could not finish. See the error details and try again.")
                    messagebox.showerror("Quality Studio", value)
                elif kind == "idle":
                    self.busy = False
                    self.exporting = False
                    self.cancel_btn.config(state="disabled")
                    self._update_controls()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _close(self):
        if self.busy:
            messagebox.showinfo("Work in progress", "Cancel your export and wait for it to stop, or wait for the preview to finish, before closing.")
            return
        self.destroy()
        self.preview_directory.cleanup()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from self_check import run
        run(Path(sys.argv[2]))
    else:
        QualityStudio().mainloop()
