

# Poster Tiler

A high-performance Python desktop application built with Tkinter, Pillow, and ReportLab that splits massive, high-resolution images into printable multi-page PDFs (like A4, A3, etc.) without losing any pixel quality or using lossy compression.

![Poster Tiler Banner](https://img.shields.io/badge/Python-GUI-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

* **Zero Resampling & Lossless Quality:** Pixels are never filtered or compressed lossily. Each tile is an exact pixel crop embedded losslessly (Flate) into the PDF.
* **Smart Grid Preview:** Live interactive preview canvas that updates in real-time as you modify settings.
* **Overlaps & Gluing Guides:** Configurable overlap strips with alternating black/white dashed vector guidelines for easy alignment.
* **Crop Marks:** Optional solid L-shaped corner trim marks for precise post-printing cuts.
* **Alignment Controls:** Built-in centering option to distribute blank margins evenly across pages.
* **Page Count Indicator:** Real-time display of total pages required based on paper size and poster dimensions.
* **Standalone Executable Support:** Built with a clean UI and packaged cleanly without a background console window.

---

## Installation & Running

### Prerequisites
Make sure you have Python installed, then install the required dependencies:
<img width="1254" height="1254" alt="Red Rounded-Square Snake Icon" src="https://github.com/user-attachments/assets/7fbd4452-51dd-4f2b-807c-0628199ba93f" />
```bash
pip install pillow reportlab
