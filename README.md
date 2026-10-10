# Aircontrol

<div align="center">

**Bespoke Windows Screen Mirroring & Interactive Remote Control for iPhone**  
*Ultra-low latency (<30ms) 60 FPS screen mirroring and responsive remote control for iPhone directly on Windows.*

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python)](https://www.python.org)
[![iOS Support](https://img.shields.io/badge/iOS-17%20%7C%2018%2B-000000?logo=apple)](https://www.apple.com/ios)
[![Frame Rate](https://img.shields.io/badge/Frame%20Rate-60%20FPS-22C55E)](https://github.com)
[![Audio](https://img.shields.io/badge/Audio-48kHz%20Stereo%20AAC--ELD-blue)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

[Download Portable](#-download--quick-start) • [Key Features](#-key-features) • [Shortcuts & Gestures](#-shortcuts--gestures) • [Developer Setup](#-developer-setup) • [Contributing](#-contributing)

</div>

---

## 🌟 Key Features

- **⚡ 60 FPS Ultra-Responsive & Retina Crisp:**
  - Multi-threaded slice-optimized hardware HEVC/H.265 decoding (`FastHevcDecoder`), streaming YUV420p color planes directly into BT.709 OpenGL shaders.
  - Integrated **Forward Error Correction (FEC)** and **RTCP Spoofer**: sustains maximum bitrate (50–100 Mbps), completely eliminating macroblocking and smearing during fast swipes over Wi-Fi.
- **🔊 Studio-Grade Lip-Sync Audio Engine:**
  - Native **AAC-ELD (48 kHz stereo)** decoding via native Fraunhofer FDK-AAC C library (`libfdk-aac-2.dll`).
  - Ultra-low latency (40ms) WASAPI audio buffer combined with Soft Cross-Fade Compaction and playback drift compensation: crystal-clear, crackle-free audio synchronized to the millisecond with video frames.
- **🎨 Bespoke macOS Simulator UI & iPhone 16 Pro Enclosure:**
  - Authentic Apple-proportioned Natural Titanium chassis featuring sleek traffic lights and dynamic island rendering.
  - Snug-fit viewport scaling with automatic, fluid portrait/landscape orientation switching for gaming and video playback.
- **🖱️ Precision Mouse, Multi-Touch & Natural Kinetic Scrolling:**
  - Left-click for touch, press-and-hold for drag/swipe.
  - **5-Stage Kinetic Momentum Scrolling:** Smooth mouse wheel deceleration mimicking OLED touch friction.
  - **Pinch-to-Zoom Gesture:** Hold `Alt` and drag mouse for two-finger zoom.
  - Right-click for **Home Gesture**; double right-click to trigger **App Switcher**.
- **📋 Bidirectional Clipboard Sync & Smart Text Input:**
  - Direct integration with Apple internal service `com.apple.coredevice.pasteboardservice`.
  - Instant text paste from PC to iPhone with `Ctrl + V`.
  - Seamless international keyboard and Unicode character input without keycode drops or scancode desynchronization.
- **🔌 Dual-Mode Connectivity (USB & Wi-Fi LAN):**
  - Automatic plug-and-play USB cable detection (<15ms latency).
  - Wireless zero-configuration Wi-Fi LAN discovery (supports manual direct IP connection on standby screen).

---

## ⌨️ Shortcuts & Gestures

| Action | Shortcut / Mouse Action | iPhone Equivalent |
| :--- | :--- | :--- |
| **Home Screen** | `Home` / `Esc` / `Ctrl + H` / `Right Click` | Return to Home screen |
| **App Switcher** | `Alt + Tab` / `Ctrl + Tab` / `Double Right Click` | Open App Switcher |
| **Lock / Unlock** | `Ctrl + L` | Lock or wake device |
| **Turn off iPhone Screen (Battery saver)** | `Ctrl + D` | Dim iPhone screen to 0% |
| **Rotate Screen** | `Ctrl + R` | Toggle between Portrait and Landscape |
| **Always on Top** | `Ctrl + T` | Keep window floating on top |
| **Screenshot** | `F12` / `Ctrl + P` / `Ctrl + S` | Save screenshot & copy to PC Clipboard |
| **Paste Text** | `Ctrl + V` | Paste text from Windows to iPhone |
| **Pinch to Zoom** | Hold `Alt` + Drag Mouse | Zoom in / Zoom out |
| **Kinetic Scroll** | Mouse Wheel | Natural smooth momentum scrolling |

---

## 🚀 Download & Quick Start

Aircontrol is packaged as a **Portable application (standalone, Python installation not required)**:

1. Navigate to the [**Releases**](../../releases) tab in this repository.
2. Download the latest release package: **`Aircontrol-v0.1.0-win64.zip`**.
3. Extract the downloaded zip archive.
4. Double-click **`Aircontrol.exe`** to launch.

> **System Requirements:**
> - Operating System: Windows 10 or Windows 11 (64-bit).
> - **iTunes** (or **Apple Devices** app from Microsoft Store) installed for Apple Mobile Device USB/network drivers.
> - **Developer Mode** enabled on iPhone: *Settings > Privacy & Security > Developer Mode*.

---

## 💻 Developer Setup

To modify source code or contribute new features:

### 1. Environment Setup:
Requires Python 3.11+:

```powershell
# Clone the repository
git clone https://github.com/zuan412/Aircontrol.git
cd Aircontrol

# Create virtual environment (uv or venv recommended)
uv venv
.venv\Scripts\activate

# Install dependencies in editable mode
uv pip install -e .
uv pip install pytest pytest-asyncio pyinstaller
```

### 2. Launch in Development Mode:
```powershell
# Quick launch via batch script
.\run.bat

# Or via Python launcher
python run_aircontrol.py

# Or connect to a specific target IP
python -m aircontrol --target-ip 192.168.1.150
```

### 3. Run Test Suite:
```powershell
pytest tests -v
```

### 4. Build Standalone Executable (.exe):
```powershell
.\build_release.bat
```

---

## 🤝 Contributing

Contributions are welcome! Please refer to [**CONTRIBUTING.md**](CONTRIBUTING.md) for details on:
- Architecture principles and code quality standards.
- Mandatory test suite verification before submitting Pull Requests.
- Conventional Commits specification.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
