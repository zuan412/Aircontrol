# Aircontrol

Phần mềm truyền màn hình iPhone lên Windows độ trễ siêu thấp (<30ms, 60 FPS) và điều khiển từ xa (chuột, bàn phím, cử chỉ vuốt, phím cứng vật lý) trên giao diện desktop mô phỏng chiếc iPhone 16 Pro cao cấp.

---

## 1. Điểm Khác Biệt & Cải Tiến Kiến Trúc

So với các giải pháp trước đây:
- **WebCodecs Direct3D 11 Hardware Decoding**: Giải mã video HEVC trực tiếp bằng GPU Windows qua Chromium WebCodecs, triệt tiêu hoàn toàn nguy cơ deadlock/treo luồng của FFmpeg C-level khi iOS thay đổi tham số màn hình (SPS/PPS).
- **Giao Diện Độc Bản (Bespoke iPhone 16 Pro)**: Khung máy bo góc squircle chuẩn Apple, viền kim loại titanium, Dynamic Island sắc nét, các nút vật lý tương tác trực tiếp trên thân máy.
- **Tương Tác Toàn Diện**: Chạm ngón tay, vuốt trượt, cuộn trang bằng con lăn chuột (Mouse Wheel), bàn phím và phím cứng vật lý (Home, Power/Lock, Vol+, Vol-, Mute).
- **Lõi Tinh Gọn**: Khai thác trực tiếp hệ thống `CoreDevice` và `RemoteXPC` ổn định của `pymobiledevice3`, kiến trúc mô-đun hóa độc lập không phụ thuộc chéo.
- **Hỗ Trợ Cả USB & Wi-Fi**: Kết nối cắm cáp USB (độ trễ thấp nhất) hoặc qua mạng Wi-Fi LAN sau khi đã ghép nối.

---

## 2. Hướng Dẫn Khởi Chạy (Quick Start)

### Cách 1: Chạy bằng file `run.bat` (Tiện lợi nhất)
Nhấp đúp vào `run.bat` hoặc chạy trong PowerShell / CMD:
```powershell
.\run.bat
```

### Cách 2: Chạy trực tiếp bằng Python
```powershell
python -m aircontrol
```

### Cách 3: Các tham số nâng cao
- Kết nối qua Wi-Fi LAN:
  ```powershell
  python -m aircontrol --wifi
  ```
- Chỉ định UDID cụ thể nếu cắm nhiều thiết bị:
  ```powershell
  python -m aircontrol --udid 00008101-001A2B3C4D5E6F
  ```
- Chạy chế độ server nền (Headless Web Stream):
  ```powershell
  python -m aircontrol --no-gui --port 8080
  ```

---

## 3. Bảng Phím Tắt & Thao Tác Nhanh

| Chức Năng | Phím Tắt | Nút Trên Giao Diện | Thao Tác Tương Đương Trên iPhone |
| :--- | :--- | :--- | :--- |
| **Màn Hình Chính** | `Ctrl + H` | Click Home Bar ở đáy | Bấm phím Home / Vuốt thanh Home Bar |
| **Khóa / Mở Màn Hình** | `Ctrl + L` | Nút Nguồn cạnh phải | Bấm nút Power / Side Button |
| **Tăng Âm Lượng** | `Ctrl + Up` | Nút Vol+ cạnh trái | Bấm nút Tăng âm lượng |
| **Giảm Âm Lượng** | `Ctrl + Down` | Nút Vol- cạnh trái | Bấm nút Giảm âm lượng |
| **Chụp Ảnh Màn Hình** | `Ctrl + P` | Nút trên Toolbar | Lưu ảnh khung hình chất lượng cao |
| **Xoay Màn Hình** | `Ctrl + R` | Nút trên Toolbar | Xoay hướng hiển thị 90 độ |
| **Bật / Tắt HUD FPS** | `Ctrl + I` | Nút trên Toolbar | Hiển thị FPS, độ phân giải, codec |
| **Cuộn Trang Tự Nhiên** | *Lăn Chuột* | Trực tiếp trên màn hình | Mô phỏng ngón tay vuốt lướt trang |

---

## 4. Chạy Bộ Kiểm Thử Tự Động (Test Suite)

```powershell
python -m pytest tests -v
```
