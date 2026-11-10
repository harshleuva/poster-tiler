#!/usr/bin/env python3
"""
Poster Tiler - split a high-resolution image into printable pages (multi-page PDF).

Pixels are never resampled, filtered or re-compressed lossily: each tile is an
exact pixel crop of the source, embedded losslessly (Flate) in the PDF.
Overlap strips, dotted guides, and crop marks are drawn as vector graphics.

Install:  pip install pillow reportlab pyinstaller
Run:      python poster_tiler.py
"""
from __future__ import annotations

import math
import os
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from PIL import Image, ImageOps, ImageTk
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

Image.MAX_IMAGE_PIXELS = None  # allow very large posters/scans

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
PAPER_MM = {  # portrait (width, height) in mm
    "A5": (148.0, 210.0),
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}
UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4}


# ----------------------------------------------------------------------------
# 1. Layout maths (pure, no GUI / no imaging)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    poster_w: float
    poster_h: float
    paper_w: float
    paper_h: float
    margin: float = 5.0
    overlap: float = 10.0
    guides: bool = True
    crop_marks: bool = False
    labels: bool = True
    center: bool = False

    @property
    def printable_w(self) -> float:
        return self.paper_w - 2 * self.margin

    @property
    def printable_h(self) -> float:
        return self.paper_h - 2 * self.margin


@dataclass
class Tile:
    row: int
    col: int
    x: float
    y: float
    has_left: bool
    has_right: bool
    has_top: bool
    has_bottom: bool


@dataclass
class Grid:
    rows: int
    cols: int
    tiles: List[Tile] = field(default_factory=list)


def _count(total: float, printable: float, overlap: float) -> int:
    if total <= printable + 1e-6:
        return 1
    return 1 + math.ceil((total - printable) / (printable - overlap) - 1e-9)


def compute_grid(s: Settings) -> Grid:
    pw, ph = s.printable_w, s.printable_h
    if pw <= s.overlap or ph <= s.overlap:
        raise ValueError("Printable area must be larger than the overlap. "
                         "Reduce the margin/overlap or use larger paper.")
    
    cols = _count(s.poster_w, pw, s.overlap)
    rows = _count(s.poster_h, ph, s.overlap)
    step_x, step_y = pw - s.overlap, ph - s.overlap
    
    offset_x = ((cols * step_x + s.overlap) - s.poster_w) / 2 if s.center else 0
    offset_y = ((rows * step_y + s.overlap) - s.poster_h) / 2 if s.center else 0
    
    grid = Grid(rows, cols)
    for r in range(rows):
        for c in range(cols):
            grid.tiles.append(Tile(r, c, c * step_x - offset_x, r * step_y - offset_y,
                                   c > 0, c < cols - 1, r > 0, r < rows - 1))
    return grid


# ----------------------------------------------------------------------------
# 2. Imaging + PDF export
# ----------------------------------------------------------------------------
def load_image(path: str) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path))
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _dotted(c: rl_canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    c.setLineWidth(0.7)
    c.setStrokeColorRGB(1, 1, 1)
    c.setDash([2.2, 2.2], 2.2)
    c.line(x1, y1, x2, y2)
    c.setStrokeColorRGB(0, 0, 0)
    c.setDash([2.2, 2.2], 0)
    c.line(x1, y1, x2, y2)
    c.setDash([])


def _crop_marks(c: rl_canvas.Canvas, s: Settings) -> None:
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(0, 0, 0)
    c.setDash([])
    m = s.margin
    pw, ph = s.paper_w, s.paper_h
    length = min(5.0, m * 0.8)
    c.line(m, ph, m, ph - length); c.line(0, ph - m, length, ph - m)
    c.line(pw - m, ph, pw - m, ph - length); c.line(pw, ph - m, pw - length, ph - m)
    c.line(m, 0, m, length); c.line(0, m, length, m)
    c.line(pw - m, 0, pw - m, length); c.line(pw, m, pw - length, m)


def export_pdf(img: Image.Image, s: Settings, out_path: str, progress: Optional[Callable[[int, int], None]] = None) -> Grid:
    grid = compute_grid(s)
    px_per_mm_x, px_per_mm_y = img.width / s.poster_w, img.height / s.poster_h
    pw_mm, ph_mm, m, ov = s.paper_w, s.paper_h, s.margin, s.overlap

    c = rl_canvas.Canvas(out_path, pagesize=(pw_mm * mm, ph_mm * mm))
    c.setTitle("Poster tiles")
    c.setCreator("Poster Tiler")
    total = len(grid.tiles)

    for n, t in enumerate(grid.tiles, 1):
        crop_x0, crop_y0 = max(0.0, t.x), max(0.0, t.y)
        x1, y1 = min(t.x + s.printable_w, s.poster_w), min(t.y + s.printable_h, s.poster_h)
        
        bx0, bx1 = round(crop_x0 * px_per_mm_x), min(round(x1 * px_per_mm_x), img.width)
        by0, by1 = round(crop_y0 * px_per_mm_y), min(round(y1 * px_per_mm_y), img.height)
        
        if bx1 > bx0 and by1 > by0:
            crop = img.crop((bx0, by0, bx1, by1))
            left = m + (crop_x0 - t.x)            
            top = ph_mm - m - (crop_y0 - t.y)     
            w, h = (bx1 - bx0) / px_per_mm_x, (by1 - by0) / px_per_mm_y
            
            c.drawImage(ImageReader(crop), left * mm, (top - h) * mm, w * mm, h * mm)
            right, bottom = left + w, top - h

            if s.guides and ov > 0:
                if t.has_left: _dotted(c, (left + ov) * mm, bottom * mm, (left + ov) * mm, top * mm)
                if t.has_right: _dotted(c, (right - ov) * mm, bottom * mm, (right - ov) * mm, top * mm)
                if t.has_top: _dotted(c, left * mm, (top - ov) * mm, right * mm, (top - ov) * mm)
                if t.has_bottom: _dotted(c, left * mm, (bottom + ov) * mm, right * mm, (bottom + ov) * mm)

        if s.crop_marks and m > 0: _crop_marks(c, s)

        if m >= 3 and s.labels:  
            c.setFont("Helvetica", 6)
            c.setFillColorRGB(0.25, 0.25, 0.25)
            c.drawCentredString(pw_mm / 2 * mm, (m / 2 - 1) * mm,
                                f"Row {t.row + 1}/{grid.rows}  Col {t.col + 1}/{grid.cols}  "
                                f"Page {n}/{total}  -  dotted line = {ov:g} mm overlap")
        c.showPage()
        if progress: progress(n, total)
    c.save()
    return grid


# ----------------------------------------------------------------------------
# 3. Splash Screen Logic
# ----------------------------------------------------------------------------
def show_splash_and_start(root: tk.Tk) -> None:
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.config(bg="white")
    
    w, h = 400, 300
    x = (splash.winfo_screenwidth() - w) // 2
    y = (splash.winfo_screenheight() - h) // 2
    splash.geometry(f"{w}x{h}+{x}+{y}")
    
    tk.Label(splash, text="POSTER TILER", font=("Helvetica", 32, "bold"), 
             bg="white", fg="#e22").pack(expand=True)
    
    def fade_out(alpha=1.0):
        alpha -= 0.05
        if alpha > 0:
            splash.attributes('-alpha', alpha)
            splash.after(30, lambda: fade_out(alpha))
        else:
            splash.destroy()
            root.deiconify()  # Show main app
    
    # Wait 1000ms (1 second), then start fade
    splash.after(1000, fade_out)


# ----------------------------------------------------------------------------
# 4. GUI
# ----------------------------------------------------------------------------
class App(ttk.Frame):
    PREVIEW = (380, 320)

    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=10)
        root.title("Poster Tiler - print big images on standard paper")
        self.pack(fill="both", expand=True)
        
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.img: Optional[Image.Image] = None
        self.thumb: Optional[Image.Image] = None
        self._photo = None

        self.path = tk.StringVar()
        self.unit = tk.StringVar(value="cm")
        self.w = tk.StringVar(value="100")
        self.h = tk.StringVar(value="70")
        self.lock = tk.BooleanVar(value=True)
        self.paper = tk.StringVar(value="A4")
        self.orient = tk.StringVar(value="Auto")
        self.margin = tk.StringVar(value="5")
        self.overlap = tk.StringVar(value="10")
        self.guides = tk.BooleanVar(value=True)
        self.crop_marks = tk.BooleanVar(value=False)
        self.labels = tk.BooleanVar(value=True)
        self.center = tk.BooleanVar(value=False)
        self.info = tk.StringVar(value="Open an image to begin.")
        self.page_count_str = tk.StringVar(value="Total Pages: --")

        self._build()
        for v in (self.w, self.h, self.unit, self.paper, self.orient,
                  self.margin, self.overlap, self.guides, self.crop_marks, 
                  self.labels, self.center):
            v.trace_add("write", lambda *_: self._on_change())
        self.w.trace_add("write", lambda *_: self._sync("w"))
        self.h.trace_add("write", lambda *_: self._sync("h"))
        self._syncing = False

    def _build(self) -> None:
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="n", padx=(0, 12))

        ttk.Label(left, text="1. Image", font=("", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(left, textvariable=self.path, width=30, state="readonly").grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(left, text="Browse...", command=self.open_image).grid(row=1, column=2, padx=(4, 0))

        ttk.Label(left, text="2. Poster size", font=("", 10, "bold")).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Label(left, text="Width").grid(row=3, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.w, width=10).grid(row=3, column=1, sticky="w", pady=2)
        ttk.Combobox(left, textvariable=self.unit, values=list(UNITS), width=4, state="readonly").grid(row=3, column=2, sticky="w")
        ttk.Label(left, text="Height").grid(row=4, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.h, width=10).grid(row=4, column=1, sticky="w", pady=2)
        ttk.Checkbutton(left, text="Keep image aspect ratio", variable=self.lock).grid(row=5, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(left, text="3. Paper", font=("", 10, "bold")).grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Combobox(left, textvariable=self.paper, values=list(PAPER_MM), width=8, state="readonly").grid(row=7, column=0, sticky="w", pady=2)
        ttk.Combobox(left, textvariable=self.orient, values=["Auto", "Portrait", "Landscape"], width=10, state="readonly").grid(row=7, column=1, columnspan=2, sticky="w")
        ttk.Label(left, text="Blank margin (mm)").grid(row=8, column=0, sticky="w")
        ttk.Spinbox(left, from_=0, to=30, increment=1, textvariable=self.margin, width=6).grid(row=8, column=1, sticky="w", pady=2)

        ttk.Label(left, text="4. Features & Alignment", font=("", 10, "bold")).grid(row=9, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Label(left, text="Overlap (mm)").grid(row=10, column=0, sticky="w")
        ttk.Spinbox(left, from_=0, to=50, increment=1, textvariable=self.overlap, width=6).grid(row=10, column=1, sticky="w", pady=2)
        ttk.Checkbutton(left, text="Dotted gluing guides", variable=self.guides).grid(row=11, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(left, text="Corner crop marks", variable=self.crop_marks).grid(row=12, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(left, text="Print page labels", variable=self.labels).grid(row=13, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(left, text="Center on paper", variable=self.center).grid(row=14, column=0, columnspan=3, sticky="w")

        # Page count and info layout
        ttk.Label(left, textvariable=self.page_count_str, font=("", 10, "bold")).grid(row=15, column=0, columnspan=3, sticky="w", pady=(15, 0))
        ttk.Label(left, textvariable=self.info, wraplength=260, foreground="#0a4").grid(row=16, column=0, columnspan=3, sticky="w", pady=5)
        
        # Export Button and Info Button in same row
        btn_frame = ttk.Frame(left)
        btn_frame.grid(row=17, column=0, columnspan=3, sticky="ew", pady=(5,0))
        btn_frame.columnconfigure(0, weight=1)
        
        self.btn = ttk.Button(btn_frame, text="Export PDF...", command=self.export)
        self.btn.grid(row=0, column=0, sticky="ew")
        
        # 'i' Information button
        self.info_btn = ttk.Button(btn_frame, text=" ℹ ", width=3, command=self.show_about)
        self.info_btn.grid(row=0, column=1, padx=(5,0))

        self.bar = ttk.Progressbar(left, mode="determinate")
        self.bar.grid(row=18, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.canvas = tk.Canvas(self, width=self.PREVIEW[0], height=self.PREVIEW[1],
                                bg="#e8e8e8", highlightthickness=1, highlightbackground="#999")
        self.canvas.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda e: self._on_change())

    def show_about(self) -> None:
        """Displays the custom 'About' window matching the Shadow Vault design."""
        about = tk.Toplevel(self)
        about.title("About")
        about.geometry("400x300")
        about.configure(bg="#111111")
        about.resizable(False, False)
        
        # Center the window
        x = self.winfo_rootx() + (self.winfo_width() // 2) - 200
        y = self.winfo_rooty() + (self.winfo_height() // 2) - 150
        about.geometry(f"+{x}+{y}")

        # Text styling to match the provided image
        tk.Label(about, text="POSTER TILER", font=("Courier", 18, "bold"), 
                 bg="#111111", fg="#00FF41").pack(pady=(30, 5))
        
        tk.Label(about, text="Print High-Resolution Images on Standard Paper", 
                 font=("Courier", 9), bg="#111111", fg="#CCCCCC").pack(pady=(0, 20))
        
        tk.Label(about, text="Created by:", font=("Courier", 11), 
                 bg="#111111", fg="#CCCCCC").pack(pady=(10, 5))
        
        tk.Label(about, text="HARSH LEUVA", font=("Courier", 14, "bold"), 
                 bg="#111111", fg="#00FF41").pack(pady=(0, 20))
        
        tk.Label(about, text="Website:", font=("Courier", 10), 
                 bg="#111111", fg="#CCCCCC").pack(pady=(0, 5))
        
        link = tk.Label(about, text="harshleuva.github.io", font=("Courier", 10, "underline"), 
                        bg="#111111", fg="#00BFFF", cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda e: webbrowser.open_new("https://harshleuva.github.io"))

    @staticmethod
    def _num(var: tk.StringVar) -> Optional[float]:
        try:
            v = float(var.get().replace(",", "."))
            return v if v >= 0 else None
        except ValueError:
            return None

    def _sync(self, src: str) -> None:
        if self._syncing or not self.lock.get() or not self.img: return
        val = self._num(self.w if src == "w" else self.h)
        if not val: return
        ratio = self.img.height / self.img.width
        self._syncing = True
        try:
            if src == "w": self.h.set(f"{val * ratio:.2f}".rstrip("0").rstrip("."))
            else: self.w.set(f"{val / ratio:.2f}".rstrip("0").rstrip("."))
        finally: self._syncing = False

    def _settings(self) -> Optional[Settings]:
        f = UNITS[self.unit.get()]
        w, h, mg, ov = self._num(self.w), self._num(self.h), self._num(self.margin), self._num(self.overlap)
        if not (w and h) or mg is None or ov is None: return None
        pw, ph = PAPER_MM[self.paper.get()]
        base = dict(poster_w=w * f, poster_h=h * f, margin=mg, overlap=ov, 
                    guides=self.guides.get(), crop_marks=self.crop_marks.get(),
                    labels=self.labels.get(), center=self.center.get())
        options = {"Portrait": [(pw, ph)], "Landscape": [(ph, pw)], "Auto": [(pw, ph), (ph, pw)]}[self.orient.get()]
        best, best_n = None, None
        for a, b in options:
            s = Settings(paper_w=a, paper_h=b, **base)
            try: n = len(compute_grid(s).tiles)
            except ValueError: continue
            if best is None or n < best_n: best, best_n = s, n
        return best

    def _on_change(self) -> None:
        if self.img: self._refresh()

    def _refresh(self) -> None:
        s = self._settings()
        self.canvas.delete("all")
        if not s:
            self.info.set("Check the numbers entered (overlap must be smaller than the printable area).")
            self.page_count_str.set("Total Pages: --")
            return
        g = compute_grid(s)
        orient = "Portrait" if s.paper_h >= s.paper_w else "Landscape"
        
        self.page_count_str.set(f"Pages Required: {len(g.tiles)}")
        self.info.set(f"{g.cols} cols x {g.rows} rows ({self.paper.get()} {orient})\n"
                      f"Density: ~{self.img.width / s.poster_w * 25.4:.0f} DPI")
        
        pw = self.canvas.winfo_width()
        ph = self.canvas.winfo_height()
        if pw <= 1 or ph <= 1: pw, ph = self.PREVIEW

        k = min((pw - 10) / s.poster_w, (ph - 10) / s.poster_h)
        W, H = s.poster_w * k, s.poster_h * k
        ox, oy = (pw - W) / 2, (ph - H) / 2
        th = self.thumb.resize((max(1, int(W)), max(1, int(H))), Image.BILINEAR)
        self._photo = ImageTk.PhotoImage(th)
        self.canvas.create_image(ox, oy, image=self._photo, anchor="nw")
        
        for t in g.tiles:
            crop_x0, crop_y0 = max(0.0, t.x), max(0.0, t.y)
            x0, y0 = ox + crop_x0 * k, oy + crop_y0 * k
            x1 = ox + min(t.x + s.printable_w, s.poster_w) * k
            y1 = oy + min(t.y + s.printable_h, s.poster_h) * k
            
            if x1 > x0 and y1 > y0:
                self.canvas.create_rectangle(x0, y0, x1, y1, outline="#e22", dash=(3, 3))
                self.canvas.create_text(x0 + 4, y0 + 2, anchor="nw", fill="#e22",
                                        text=f"{t.row + 1},{t.col + 1}", font=("", 8, "bold"))

    def open_image(self) -> None:
        p = filedialog.askopenfilename(title="Choose a high-resolution image",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
                                                  ("All files", "*.*")])
        if not p: return
        try:
            self.config(cursor="watch"); self.update_idletasks()
            self.img = load_image(p)
        except Exception as e:
            messagebox.showerror("Cannot open image", str(e))
            return
        finally:
            self.config(cursor="")
        self.path.set(p)
        self.thumb = self.img.copy()
        self.thumb.thumbnail((800, 800))
        self._syncing = True
        self.h.set(f"{float(self.w.get() or 100) * self.img.height / self.img.width:.2f}".rstrip("0").rstrip("."))
        self._syncing = False
        self._refresh()

    def export(self) -> None:
        if not self.img:
            messagebox.showwarning("No image", "Please open an image first.")
            return
        s = self._settings()
        if not s:
            messagebox.showerror("Invalid settings", "Please check the size, margin and overlap values.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                           initialfile=os.path.splitext(os.path.basename(self.path.get()))[0] + "_poster.pdf")
        if not out: return

        def prog(n: int, total: int) -> None:
            self.bar["value"] = 100 * n / total
            self.update_idletasks()

        try:
            self.btn.state(["disabled"]); self.config(cursor="watch")
            g = export_pdf(self.img, s, out, prog)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return
        finally:
            self.btn.state(["!disabled"]); self.config(cursor=""); self.bar["value"] = 0
        messagebox.showinfo("Done", f"Saved {len(g.tiles)} pages ({g.cols} x {g.rows}) to:\n{out}")


def main() -> None:
    root = tk.Tk()
    root.geometry("850x620")
    root.withdraw()  # Hide main window initially

    App(root)

    # Show splash screen (handles fade out and unhiding root)
    show_splash_and_start(root)
    
    root.mainloop()

if __name__ == "__main__":
    main()