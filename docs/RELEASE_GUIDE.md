# Cẩm Nang Phát Hành Bản Thử Nghiệm Aircontrol Lên GitHub (Không Lộ Mã Nguồn)

Tài liệu này hướng dẫn chi tiết quy trình đóng gói và phát hành ứng dụng **Aircontrol** lên GitHub dưới dạng file nhị phân độc lập (Standalone Portable Binary) mà **hoàn toàn không làm lộ mã nguồn gốc (`.py`)**.

---

## 1. Bản Đóng Gói Đã Được Tạo Tự Động

Ứng dụng đã được cấu hình đóng gói qua PyInstaller với cấu trúc thư mục tối ưu:
- **Thư mục chạy trực tiếp:** `dist\Aircontrol\`
  - File chạy chính: `Aircontrol.exe` (đã nhúng icon, không hiển thị cửa sổ dòng lệnh CMD đen).
  - Thư viện C/FFmpeg native: `_internal\av.libs\*.dll`
  - Bộ giải mã âm thanh AAC-ELD: `_internal\libfdk-aac-2.dll`
  - Dữ liệu vỏ máy mô phỏng Apple: `_internal\skins\`
  - Mã nguồn Python đã được biên dịch thành bytecode tối ưu hóa (`.pyc` đóng trong gói PYZ), **không chứa bất kỳ file `.py` nào**.
- **Gói nén phát hành:** `dist\Aircontrol-v0.1.0-win64.zip` (~154 MB)
  - Người dùng cuối chỉ cần tải về, giải nén và nhấp đúp `Aircontrol.exe` là chạy ngay.
  - Không yêu cầu cài đặt Python, `uv` hay bất kỳ thư viện ngoài nào.

> [!TIP]
> **Đóng gói lại chỉ với 1 cú nhấp:** Khi có bản cập nhật mới, chỉ cần nhấp đúp vào file [`build_release.bat`](file:///d:/Coding/Aircontrol/build_release.bat), toàn bộ tiến trình dọn dẹp, biên dịch và tạo file zip sẽ tự động diễn ra.

---

## 2. Chiến Lược Phát Hành Lên GitHub Không Lộ Source Code

Khi đăng sản phẩm lên GitHub, có 2 kịch bản an toàn tuyệt đối:

### Kịch Bản A: Phân Phối Qua "Landing Repository" Công Khai (Khuyến Nghị Cao Nhất)
Đây là cách làm chuẩn của các phần mềm thương mại / nguồn đóng (như Discord, Notion, Telegram Desktop Windows build):
1. **Tạo Repository mới trên GitHub**, đặt tên ví dụ: `aircontrol-desktop` hoặc `aircontrol-preview` ở chế độ **Public**.
2. **Nội dung trong repository này CHỈ chứa:**
   - File [`DISTRIBUTION_README.md`](file:///d:/Coding/Aircontrol/DISTRIBUTION_README.md) (đổi tên thành `README.md`) làm trang giới thiệu sản phẩm.
   - File `LICENSE` (Giấy phép sử dụng phần mềm đóng gói).
   - Thư mục ảnh chụp màn hình / GIF demo (nếu có).
   - **Tuyệt đối KHÔNG commit thư mục code `aircontrol/`, `tests/`, `pyproject.toml` vào repo này.**
3. Vào tab **Releases** của repo `aircontrol-preview`:
   - Bấm **Create a new release** -> Đặt tag: `v0.1.0-beta`.
   - Tiêu đề: `Aircontrol v0.1.0 (Public Beta Preview)`.
   - Kéo thả file `dist\Aircontrol-v0.1.0-win64.zip` vào ô **Attach binaries by dropping them here or selecting them**.
   - Bấm **Publish release**.
4. **Kết quả:** Cộng đồng chỉ tải được file `Aircontrol-v0.1.0-win64.zip`. Nút "Source code (zip)" do GitHub tự sinh sẽ chỉ chứa file `README.md` của repo giới thiệu, mã nguồn gốc được bảo vệ 100%.

---

### Kịch Bản B: Giữ Repository Hiện Tại Ở Chế Độ Private
Nếu bạn muốn lưu mã nguồn trên GitHub nhưng không muốn ai xem được:
1. Đặt repository `Aircontrol` trên GitHub ở chế độ **Private**.
2. Chỉ có tài khoản của bạn xem và sửa được mã nguồn.
3. Khi muốn gửi cho bạn bè hoặc người dùng thử nghiệm:
   - Gửi trực tiếp file `dist\Aircontrol-v0.1.0-win64.zip` qua Google Drive, Dropbox, Mega hoặc Telegram.
   - Hoặc tải file zip lên mục Release của repo Private và tạo direct download link.

---

## 3. Các Bước Đăng Bản Thử Nghiệm Lên GitHub (Từng Bước)

1. Mở trình duyệt, truy cập `https://github.com/new`.
2. Đặt tên repository: `aircontrol-desktop` (hoặc tên tùy chọn), chọn chế độ **Public**.
3. Khởi tạo với một file `README.md` (hoặc copy nội dung từ [`DISTRIBUTION_README.md`](file:///d:/Coding/Aircontrol/DISTRIBUTION_README.md)).
4. Vào mục **Releases** ở thanh bên phải của repository.
5. Nhấp **Draft a new release**:
   - **Tag version:** `v0.1.0-beta`
   - **Release title:** `Aircontrol v0.1.0 Beta - 60 FPS iPhone Mirroring for Windows`
   - **Description:** Dán nội dung ghi chú phát hành (Release Notes) từ mục 4 bên dưới.
   - **Attach binaries:** Kéo thả tệp `d:\Coding\Aircontrol\dist\Aircontrol-v0.1.0-win64.zip`.
6. Nhấp **Publish release**.
7. Chia sẻ link Release cho người dùng trải nghiệm!

---

## 4. Mẫu Ghi Chú Phát Hành (Release Notes Template)

```markdown
# 🚀 Aircontrol v0.1.0 Beta Preview

Trải nghiệm phản chiếu màn hình và điều khiển iPhone từ máy tính Windows với độ trễ cực thấp, tốc độ khung hình 60 FPS mượt mà và thiết kế Apple Simulator Titanium độc bản.

### ✨ Điểm Nổi Bật
- **Hiệu năng cao:** Luồng HEVC phần cứng, bộ lọc thích ứng tương phản CAS (Contrast Adaptive Sharpening), độ trễ <30ms qua cáp USB và <50ms qua Wi-Fi 5GHz.
- **Điều khiển tương tác đa chạm:** Hỗ trợ đầy đủ chuột, cuộn hai ngón mượt mà, cử chỉ Home/App Switcher, phóng to/thu nhỏ (Alt + Kéo chuột).
- **Âm thanh chất lượng cao:** Truyền phát trực tiếp âm thanh AAC-ELD độ trễ thấp từ iPhone sang loa máy tính.
- **Giao diện Apple Simulator:** Viền màn hình titan tự nhiên mỏng chuẩn xác, hỗ trợ xoay ngang/dọc, chế độ Always on Top, chụp ảnh màn hình chép trực tiếp vào Clipboard.
- **Tiện ích bàn phím:** Tự động đồng bộ Clipboard từ máy tính sang iPhone qua phím tắt Ctrl+V.

### 📦 Tải Về & Khởi Chạy
1. Tải tệp `Aircontrol-v0.1.0-win64.zip` bên dưới.
2. Giải nén vào một thư mục bất kỳ trên máy tính.
3. Nhấp đúp vào `Aircontrol.exe` để bắt đầu.

### ⚠️ Yêu Cầu Trước Khi Kết Nối
- Đã cài đặt **iTunes** hoặc **Apple Devices App** trên Windows (để có Apple Mobile Device Driver).
- Mở khóa màn hình iPhone và chọn **"Tin cậy máy tính này" (Trust This Computer)** nếu được hỏi.
- Bật **Chế độ Nhà phát triển (Developer Mode)** trên iPhone: *Cài đặt > Quyền riêng tư & Bảo mật > Chế độ Nhà phát triển* (khởi động lại máy khi được yêu cầu).
```
