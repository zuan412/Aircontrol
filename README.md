# Aircontrol

<div align="center">

**Bespoke Windows Screen Mirroring & Interactive Remote Control for iPhone**  
*Phản chiếu màn hình & điều khiển iPhone tốc độ cao 60 FPS trực tiếp trên máy tính Windows với độ trễ cực thấp (<30ms).*

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python)](https://www.python.org)
[![iOS Support](https://img.shields.io/badge/iOS-17%20%7C%2018%2B-000000?logo=apple)](https://www.apple.com/ios)
[![Frame Rate](https://img.shields.io/badge/Frame%20Rate-60%20FPS-22C55E)](https://github.com)
[![Audio](https://img.shields.io/badge/Audio-48kHz%20Stereo%20AAC--ELD-blue)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

[Tải Về Bản Portable](#-dành-cho-người-dùng-tải-về--khởi-chạy-ngay) • [Tính Năng](#-tính-năng-nổi-bật) • [Phím Tắt](#-bảng-phím-tắt--cử-chỉ) • [Phát Triển (Dev Setup)](#-dành-cho-nhà-phát-triển-developer-setup) • [Đóng Góp](#-đóng-góp-contributing)

</div>

---

## 🌟 Tính Năng Nổi Bật

- **⚡ 60 FPS Siêu Phản Ứng & Độ Nét Retina:**
  - Giải mã phần cứng HEVC/H.265 tối ưu lát cắt đa luồng (`FastHevcDecoder`), nạp trực tiếp các mặt phẳng màu YUV420p vào OpenGL Shader BT.709.
  - Tích hợp công nghệ **FEC (Forward Error Correction)** và **RTCP Spoofer**: luôn duy trì mức bitrate cực đại 50-100 Mbps, xóa bỏ hoàn toàn hiện tượng vỡ hạt/nhòe mờ khi vuốt chạm nhanh trên Wi-Fi.
- **🔊 Hệ Thống Âm Thanh Studio-Grade Đồng Bộ Hoàn Hảo (Lip-Sync):**
  - Giải mã luồng âm thanh gốc **AAC-ELD (48 kHz stereo)** qua thư viện C gốc Fraunhofer FDK-AAC (`libfdk-aac-2.dll`).
  - Bộ đệm phát âm thanh WASAPI độ trễ thấp 40ms kết hợp thuật toán làm mịn sóng âm (Soft Cross-Fade Compaction) và bù trễ nhịp phát: âm thanh trong trẻo, không rè, khớp từng mili-giây với hình ảnh.
- **🎨 Giao Diện Độc Bản macOS Simulator & Khung Vỏ iPhone 16 Pro:**
  - Khung viền kim loại Natural Titanium chuẩn tỉ lệ Apple, tích hợp nút Traffic Lights thanh lịch và Dynamic Island.
  - Tay nắm co giãn ôm khít tỉ lệ màn hình (Snug-fit), tự động xoay đứng/ngang linh hoạt khi xem video hoặc chơi game.
- **🖱️ Chuột, Cảm Ứng Đa Điểm & Cuộn Quán Tính Tự Nhiên:**
  - Nhấp chuột trái để chạm, nhấn giữ và kéo vuốt tự nhiên.
  - **Cuộn quán tính 5 bước (Kinetic Momentum):** Con lăn chuột trôi êm ái tự nhiên như ngón tay lướt trên màn hình OLED.
  - **Cử chỉ Pinch-to-Zoom:** Giữ phím `Alt` và kéo chuột để thu phóng hai ngón.
  - Nhấp chuột phải để về màn hình chính (**Home Gesture**); nhấp đúp chuột phải để mở bộ chuyển đổi ứng dụng (**App Switcher**).
- **📋 Đồng Bộ Clipboard Hai Chiều & Nhập Liệu Tiếng Việt Thông Minh:**
  - Khai thác trực tiếp dịch vụ nội bộ Apple `com.apple.coredevice.pasteboardservice`.
  - Nhấn `Ctrl + V` để dán tức thì văn bản từ PC sang iPhone.
  - Hỗ trợ gõ tiếng Việt Unicode có dấu (Unikey / EVKey) mượt mà 100%, không bị nuốt chữ hay nhảy scancode.
- **🔌 Kết Nối Kép Linh Hoạt (USB & Wi-Fi LAN):**
  - Tự động nhận diện thiết bị cắm cáp USB (độ trễ <15ms).
  - Tự động phát hiện và kết nối iPhone qua mạng không dây Wi-Fi LAN (hỗ trợ nhập IP trực tiếp trên giao diện chờ).

---

## ⌨️ Bảng Phím Tắt & Cử Chỉ

| Thao Tác | Phím Tắt / Thao Tác Chuột | Tác Vụ Tương Đương Trên iPhone |
| :--- | :--- | :--- |
| **Màn hình chính (Home)** | `Home` / `Esc` / `Ctrl + H` / `Chuột Phải` | Trở về màn hình chính |
| **Đổi ứng dụng (App Switcher)** | `Alt + Tab` / `Ctrl + Tab` / `Nhấp đúp Chuột Phải` | Mở trình chuyển đa nhiệm |
| **Khóa / Mở màn hình** | `Ctrl + L` | Khóa hoặc đánh thức thiết bị |
| **Tắt màn hình iPhone (Tiết kiệm pin)** | `Ctrl + D` | Đưa màn hình iPhone về độ sáng 0% |
| **Xoay màn hình (Rotate)** | `Ctrl + R` | Chuyển đổi giữa chế độ Đứng và Ngang |
| **Ghim cửa sổ trên cùng** | `Ctrl + T` | Luôn hiển thị Aircontrol trên các app khác |
| **Chụp ảnh màn hình (Screenshot)** | `F12` / `Ctrl + P` / `Ctrl + S` | Lưu ảnh và copy vào Clipboard PC |
| **Dán văn bản (Paste)** | `Ctrl + V` | Dán văn bản từ Windows sang iPhone |
| **Thu phóng hai ngón (Pinch)** | Giữ phím `Alt` + Kéo chuột | Zoom in / Zoom out |
| **Cuộn trang quán tính** | Con lăn chuột (Mouse Wheel) | Cuộn trang mượt mà tự nhiên |

---

## 🚀 Dành Cho Người Dùng: Tải Về & Khởi Chạy Ngay

Ứng dụng được đóng gói dạng **Portable (chạy ngay, không cần cài đặt Python)**:

1. Vào mục [**Releases**](../../releases) của repository này.
2. Tải tệp tin nén mới nhất: **`Aircontrol-v0.1.0-win64.zip`**.
3. Giải nén tệp zip vừa tải về.
4. Nhấp đúp vào **`Aircontrol.exe`** để khởi chạy.

> **Yêu Cầu Hệ Thống:**
> - Hệ điều hành: Windows 10 hoặc Windows 11 (64-bit).
> - Đã cài đặt **iTunes** (hoặc ứng dụng **Apple Devices** từ Microsoft Store) để máy tính có sẵn driver nhận diện thiết bị Apple.
> - Bật **Developer Mode (Chế độ nhà phát triển)** trên iPhone: *Cài đặt > Quyền riêng tư & Bảo mật > Chế độ nhà phát triển*.

---

## 💻 Dành Cho Nhà Phát Triển (Developer Setup)

Nếu bạn muốn chỉnh sửa mã nguồn hoặc đóng góp tính năng mới:

### 1. Cài Đặt Môi Trường:
Yêu cầu Python 3.11+:

```powershell
# Clone mã nguồn
git clone https://github.com/zuan412/Aircontrol.git
cd Aircontrol

# Tạo môi trường ảo (khuyến nghị dùng uv hoặc venv)
uv venv
.venv\Scripts\activate

# Cài đặt dependencies
uv pip install -e .
uv pip install pytest pytest-asyncio pyinstaller
```

### 2. Khởi Chạy Môi Trường Dev:
```powershell
# Chạy nhanh qua script
.\run.bat

# Hoặc qua launcher
python run_aircontrol.py

# Hoặc kết nối qua địa chỉ IP cụ thể
python -m aircontrol --target-ip 192.168.1.150
```

### 3. Chạy Toàn Bộ Test Suite:
```powershell
pytest tests -v
```

### 4. Đóng Gói Standalone Executable (.exe):
```powershell
.\build_release.bat
```

---

## 🤝 Đóng Góp (Contributing)

Mọi đóng góp từ cộng đồng đều được chào đón! Hãy đọc kỹ [**CONTRIBUTING.md**](CONTRIBUTING.md) để nắm rõ:
- Quy chuẩn mã nguồn & kiến trúc.
- Quy trình kiểm thử bắt buộc trước khi tạo Pull Request.
- Quy chuẩn thông điệp commit (Conventional Commits).

---

## 📄 Bản Quyền & Giấy Phép (License)

Dự án được phân phối dưới giấy phép **MIT License**. Xem chi tiết tại [LICENSE](LICENSE).
