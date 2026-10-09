# Hướng Dẫn Đóng Góp Vào Aircontrol (Contributing Guide)

Chào mừng bạn đến với cộng đồng phát triển **Aircontrol**!  
Aircontrol là dự án mã nguồn mở cung cấp giải pháp phản chiếu màn hình và điều khiển iPhone tốc độ cao 60 FPS độ trễ thấp trên Windows 10/11.

Chúng tôi rất hoan nghênh mọi sự đóng góp: từ sửa lỗi (bug fixes), tối ưu hóa hiệu năng, bổ sung tính năng mới cho đến cải thiện tài liệu.

---

## 🛠️ 1. Thiết Lập Môi Trường Phát Triển (Development Setup)

### Yêu Cầu Tiên Quyết:
- **Hệ điều hành:** Windows 10 hoặc Windows 11 (64-bit).
- **Python:** Python 3.11 hoặc mới hơn (khuyến nghị 3.11 hoặc 3.12).
- **Trình quản lý gói:** Khuyến nghị dùng [`uv`](https://github.com/astral-sh/uv) để quản lý virtual environment siêu nhanh, hoặc dùng `python -m venv`.
- **Driver Apple:** Đã cài đặt iTunes hoặc ứng dụng **Apple Devices** từ Microsoft Store (cung cấp driver Apple Mobile Device Support).

### Các Bước Cài Đặt:

1. **Clone repository về máy:**
   ```powershell
   git clone https://github.com/your-username/Aircontrol.git
   cd Aircontrol
   ```

2. **Tạo và kích hoạt môi trường ảo (Virtual Environment):**
   *Sử dụng `uv`:*
   ```powershell
   uv venv
   .venv\Scripts\activate
   uv pip install -e .
   uv pip install pytest pytest-asyncio pyinstaller
   ```

   *Hoặc sử dụng `python standard`:*
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   pip install pytest pytest-asyncio pyinstaller
   ```

3. **Kiểm tra cài đặt:**
   ```powershell
   pytest tests -q
   ```
   Tất cả các bài kiểm thử phải đạt trạng thái `passed`.

---

## 🚀 2. Chạy Ứng Dụng Trong Môi Trường Dev

- **Cách 1: Chạy nhanh qua script:**
  ```powershell
  .\run.bat
  ```

- **Cách 2: Chạy qua launcher:**
  ```powershell
  python run_aircontrol.py
  ```

- **Cách 3: Chạy dưới dạng module với các cờ tùy chọn:**
  ```powershell
  python -m aircontrol --wifi
  python -m aircontrol --usb
  python -m aircontrol --target-ip 192.168.1.150
  ```

---

## 🧪 3. Quy Chuẩn Kiểm Thử (Testing Guidelines)

Aircontrol áp dụng nguyên tắc kiểm thử nghiêm ngặt:
1. **Mọi tính năng mới hoặc bản sửa lỗi (bugfix) đều phải đi kèm unit test.**
2. **Không commit code làm gãy test suite hiện tại.**
3. Chạy toàn bộ test suite trước khi commit:
   ```powershell
   pytest tests -v
   ```

---

## 📦 4. Đóng Gói Binary Độc Lập (Standalone Build)

Dự án hỗ trợ đóng gói thành tệp thực thi độc lập `.exe` thông qua PyInstaller:
```powershell
.\build_release.bat
```
Kết quả biên dịch sẽ nằm tại:
- `dist\Aircontrol\Aircontrol.exe` (Thư mục chạy portable)
- `dist\Aircontrol-v0.1.0-win64.zip` (Tệp nén phát hành)

---

## 📋 5. Quy Trình Tạo Pull Request (PR Workflow)

1. **Tạo nhánh mới từ `master`:**
   ```powershell
   git checkout -b feature/ten-tinh-nang
   # hoặc: git checkout -b fix/ten-loi
   ```

2. **Quy chuẩn thông điệp commit (Conventional Commits):**
   - `feat(...)`: Thêm tính năng mới (ví dụ: `feat(audio): add WASAPI exclusive mode`)
   - `fix(...)`: Sửa lỗi (ví dụ: `fix(stream): resolve packet drop in reorder buffer`)
   - `docs(...)`: Cập nhật tài liệu
   - `test(...)`: Bổ sung hoặc sửa đổi bài kiểm thử
   - `refactor(...)`: Tái cấu trúc mã nguồn không thay đổi hành vi

3. **Đẩy nhánh lên GitHub và mở Pull Request:**
   - Cung cấp mô tả rõ ràng về vấn đề được giải quyết.
   - Đính kèm hình ảnh hoặc bằng chứng đo đạc nếu liên quan đến UI hoặc hiệu năng.

Cảm ơn bạn đã đồng hành và đóng góp vào Aircontrol!
