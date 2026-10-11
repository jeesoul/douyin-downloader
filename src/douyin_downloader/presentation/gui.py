import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .. import __version__
from ..domain.models import DownloadCancelled, DownloadOptions
from ..infrastructure.runtime import redact

LOGGER = logging.getLogger(__name__)


def open_path(path: Path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class DownloaderApp:
    """Tk 只在主线程更新；后台任务通过事件队列报告状态。"""

    def __init__(self, root, options: DownloadOptions, log_path: Path, runner=None):
        import tkinter as tk
        from tkinter import font, ttk

        if runner is None:
            from ..application.service import run_download

            runner = run_download
        self.root = root
        self.runner = runner
        self.log_path = log_path
        self.options = options
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.active = False
        self.closing = False
        self.exit_code = 1
        self.worker = None
        self.saved_folder = None
        root.title(f"Douyin Material Downloader {__version__}")
        root.configure(bg="#ffffff")
        root.geometry("640x570")
        root.resizable(False, False)
        root.update_idletasks()
        root.geometry(
            f"+{max(0, (root.winfo_screenwidth() - 640) // 2)}+{max(0, (root.winfo_screenheight() - 570) // 2)}"
        )
        families = font.families(root)
        family = next(
            (
                name
                for name in (
                    "Microsoft YaHei UI",
                    "Microsoft YaHei",
                    "PingFang SC",
                    "Noto Sans CJK SC",
                    "Arial",
                )
                if name in families
            ),
            "TkDefaultFont",
        )
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", foreground="#242424", font=(family, 10))
        style.configure("TButton", font=(family, 10), padding=(10, 6))
        style.configure("TProgressbar", background="#fe2c55")
        style.configure("Title.TLabel", font=(family, 17, "bold"))
        style.configure("Status.TLabel", font=(family, 11, "bold"))
        tk.Frame(root, height=5, bg="#fe2c55").pack(fill="x")
        body = ttk.Frame(root, padding=(24, 18))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Douyin Material Downloader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Share link", padding=(0, 16, 0, 5)).pack(anchor="w")
        self.link = tk.Text(
            body,
            height=4,
            wrap="word",
            font=(family, 10),
            padx=8,
            pady=6,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
        )
        self.link.pack(fill="x")
        if options.link:
            self.link.insert("1.0", options.link)
        else:
            try:
                from ..adapters.douyin.links import extract_url

                clipboard = root.clipboard_get()
                if extract_url(clipboard):
                    self.link.insert("1.0", clipboard)
            except (tk.TclError, ImportError):
                pass
        choices = ttk.Frame(body)
        choices.pack(fill="x", pady=(12, 10))
        ttk.Label(choices, text="Quality").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.quality = tk.StringVar(value=options.quality or "Auto (Best)")
        self.quality_box = ttk.Combobox(
            choices,
            textvariable=self.quality,
            state="readonly",
            width=13,
            values=["Auto (Best)", "1080", "720", "540", "hdr"],
        )
        self.quality_box.grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Label(choices, text="Photo export").grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.photo_mode = tk.StringVar(
            value="Originals + MP4" if options.photo_mode == "both" else "Originals"
        )
        self.photo_box = ttk.Combobox(
            choices,
            textvariable=self.photo_mode,
            state="readonly",
            width=19,
            values=["Originals + MP4", "Originals"],
        )
        self.photo_box.grid(row=0, column=3, sticky="w")
        ttk.Separator(body).pack(fill="x", pady=(6, 12))
        self.status = ttk.Label(body, text="Ready", style="Status.TLabel", wraplength=585)
        self.status.pack(fill="x")
        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 8))
        self.stats = ttk.Label(body, text=" ")
        self.stats.pack(fill="x")
        details = ttk.Frame(body)
        details.pack(fill="both", expand=True, pady=(8, 12))
        self.detail = tk.Text(
            details,
            height=5,
            wrap="word",
            font=(family, 9),
            relief="flat",
            state="disabled",
            foreground="#565656",
            background="#f6f7f8",
            padx=8,
            pady=6,
        )
        self.detail.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(details, command=self.detail.yview)
        scrollbar.pack(side="right", fill="y")
        self.detail.configure(yscrollcommand=scrollbar.set)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.download_button = ttk.Button(buttons, text="Download", command=self.start)
        self.download_button.pack(side="left")
        self.folder_button = ttk.Button(
            buttons, text="Open Folder", command=self.open_folder, state="disabled"
        )
        self.folder_button.pack(side="left", padx=8)
        self.log_button = ttk.Button(
            buttons, text="Open Log", command=lambda: open_path(self.log_path)
        )
        self.log_button.pack(side="left")
        self.close_button = ttk.Button(buttons, text="Close", command=self.cancel_or_close)
        self.close_button.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        self.link.focus_set()
        if options.link:
            root.after(100, self.start)

    def set_detail(self, message):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", message)
        self.detail.configure(state="disabled")

    def start(self):
        if self.active:
            return
        link = self.link.get("1.0", "end-1c").strip()
        if not link:
            self.status.configure(text="No link provided", foreground="#d93025")
            return
        quality = self.quality.get()
        options = DownloadOptions(
            link=link,
            output_dir=self.options.output_dir,
            quality=None if quality == "Auto (Best)" else quality,
            photo_mode="both" if self.photo_mode.get() == "Originals + MP4" else "originals",
            slide_seconds=self.options.slide_seconds,
            show_browser=self.options.show_browser,
        )
        self.active = True
        self.cancel.clear()
        self.exit_code = 1
        self.link.configure(state="disabled")
        self.quality_box.configure(state="disabled")
        self.photo_box.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.close_button.configure(text="Cancel", state="normal")
        self.status.configure(text="Processing...", foreground="#242424")
        self.stats.configure(text=" ")
        self.set_detail("")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)

        def work():
            try:
                result = self.runner(
                    options,
                    self.cancel,
                    lambda message: self.events.put(("status", message)),
                    lambda *values: self.events.put(("transfer", values)),
                    lambda *values: self.events.put(("export", values)),
                )
                self.events.put(("done", result))
            except DownloadCancelled:
                self.events.put(("cancelled", None))
            except Exception as exc:
                message = redact(str(exc))
                LOGGER.error("%s: %s", type(exc).__name__, message)
                self.events.put(("error", message))

        self.worker = threading.Thread(target=work, name="douyin-download")
        self.worker.start()

    def finish(self, kind, value):
        self.active = False
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=100 if kind == "done" else 0)
        self.download_button.configure(
            state="normal", text="Download" if kind == "done" else "Retry"
        )
        self.close_button.configure(state="normal", text="Close")
        self.link.configure(state="normal")
        self.quality_box.configure(state="readonly")
        self.photo_box.configure(state="readonly")
        if self.closing:
            self.root.destroy()
            return
        if kind == "done":
            self.exit_code = 0
            self.status.configure(
                text="Completed with warnings" if value.warnings else "Done!",
                foreground="#996000" if value.warnings else "#1e8e3e",
            )
            self.set_detail(
                "\n".join(["Saved:", *(str(path) for path in value.files), *value.warnings])
            )
            self.saved_folder = value.files[0].parent if value.files else self.options.output_dir
            self.folder_button.configure(state="normal")
            self.stats.configure(text=f"{len(value.files)} file(s) saved")
        elif kind == "error":
            self.status.configure(text="Download failed", foreground="#d93025")
            self.set_detail(value)
            self.stats.configure(text=" ")
        else:
            self.status.configure(text="Cancelled", foreground="#565656")
            self.set_detail("")
            self.stats.configure(text=" ")

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in {"done", "error", "cancelled"}:
                self.finish(kind, value)
                if self.closing:
                    return
            elif not self.cancel.is_set():
                if kind == "status":
                    self.status.configure(text=value)
                    self.stats.configure(text=" ")
                    self.progress.stop()
                    self.progress.configure(mode="indeterminate", value=0)
                    self.progress.start(12)
                elif kind == "transfer":
                    written, total, elapsed = value
                    speed = written / max(elapsed, 0.001)
                    if total:
                        self.progress.stop()
                        self.progress.configure(
                            mode="determinate", maximum=100, value=min(100, written * 100 / total)
                        )
                        eta = max(0, total - written) / speed if speed else 0
                        text = f"{written / 1048576:.1f} / {total / 1048576:.1f} MB    {speed / 1048576:.2f} MB/s    ETA {int(eta)}s"
                    else:
                        text = f"{written / 1048576:.1f} MB    {speed / 1048576:.2f} MB/s"
                    self.stats.configure(text=text)
                elif kind == "export":
                    current, total = value
                    self.progress.stop()
                    self.progress.configure(
                        mode="determinate",
                        maximum=100,
                        value=min(100, current * 100 / max(total, 0.001)),
                    )
                    self.stats.configure(
                        text=f"Video export: {min(100, current * 100 / max(total, 0.001)):.0f}%"
                    )
        self.root.after(100, self.poll)

    def request_cancel(self):
        self.cancel.set()
        self.close_button.configure(state="disabled")
        self.status.configure(text="Cancelling...")
        self.set_detail("Waiting for the current request to finish.")

    def cancel_or_close(self):
        if self.active:
            self.request_cancel()
        else:
            self.root.destroy()

    def close(self):
        if self.active:
            self.closing = True
            self.request_cancel()
        else:
            self.root.destroy()

    def open_folder(self):
        if self.saved_folder:
            open_path(self.saved_folder)


def launch_gui(options: DownloadOptions, log_path: Path) -> int:
    import tkinter as tk

    root = tk.Tk()
    app = DownloaderApp(root, options, log_path)
    root.mainloop()
    if app.worker:
        app.worker.join()
    return app.exit_code
