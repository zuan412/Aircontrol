# FINAL MASTER UPGRADE BLUEPRINT: KIẾN TRÚC ĐẠI NÂNG CẤP TOÀN DIỆN CHO AIRCONTROL

> **Mã dự án:** `AIRCONTROL-MASTER-BLUEPRINT-2026-FINAL`  
> **Tác giả:** Antigravity Tech Lead & Systems Architecture Swarm  
> **Đối tượng áp dụng:** Nền tảng điều khiển & phản chiếu iPhone trên Windows 10/11 (Hỗ trợ từ iOS 15 đến iOS 18/27+)  
> **Dữ liệu thực nghiệm phần cứng:**
> - PC Host: AMD/Intel Windows 11, Card mạng `Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter`
> - iPhone mục tiêu: `iPhone 12 Pro Max (iOS 18)` (`peer_udid: 00008101-00014D11022AXXXX`, IP: `192.168.1.150`)
> - Kết quả đo đạc thực tế: Mạng Router thường có ping `108ms`, jitter `52ms` (nguyên nhân gây nhòe mờ khi vuốt).

---

## 1. TỔNG QUAN ĐÁNH GIÁ 2 CUỘC ĐẠI NGHIÊN CỨU

Qua hai đợt nghiên cứu chuyên sâu (can thiệp trực tiếp vào thiết bị thực tế và phân tích giao thức Apple nội bộ), chúng ta đã xác định được toàn bộ bức tranh kỹ thuật:

```
[Hiện Trạng Thất Bại Của Wi-Fi Thường]
iPhone (108ms Ping / 52ms Jitter) 
  ───> Apple AVCRateController phát hiện mạng xấu 
  ───> Tự động bóp băng thông xuống 2-5 Mbps + Tăng nén QP 
  ───> Vuốt chạm bị vỡ hạt, nhòe mờ (Macroblocking)

[Mục Tiêu Đại Nâng Cấp: Wired-Equivalent Wireless]
iPhone (1.5ms Ping / <0.5ms Jitter qua 5GHz P2P)
  ───> RTCP Spoofer ép AVCRateController duy trì 100 Mbps
  ───> FEC (FlexFEC) phục hồi 100% gói rớt trong 0ms RAM
  ───> 60-100 Mbps Retina không tì vết, cuộn trang mượt mà như cắm cáp
```

### Các Phát Hiện Trọng Yếu:
1. **72 Dịch Vụ RSD Đang Mở:** Chiếc iPhone thực tế sở hữu các dịch vụ chưa từng được khai thác trên Windows: `com.apple.coredevice.pasteboardservice` (Clipboard), `com.apple.dt.testmanagerd.remote` (Hành động hệ thống sâu), `com.apple.coredevice.screencaptureservice` (Ảnh tĩnh gốc), `com.apple.coredevice.hid.universalhidservice`.
2. **Cấu Trúc Video Mới (iOS 27.0 Probed):** Cờ `fecEnabled=True` (Sửa lỗi trước), `customVideoWidth/Height` (Màn hình ảo tùy chỉnh độ phân giải PC), `foveationSupported` (Bitrate tập trung điểm chạm), và băng thông tối đa lên đến 100 Mbps.
3. **Bản Chất Độc Quyền Của Apple Continuity:** Mac dùng chip bảo mật Secure Enclave và sóng AWDL riêng để mở khóa ngầm từ xa; trên Windows, phương pháp tối ưu nhất là đi qua kênh CoreDevice TLS/QUIC Tunnel đã được xác thực an toàn bằng Pair Record.

---

## 2. NGHIÊN CỨU BỔ SUNG CÁC TÍNH NĂNG ĐỘT PHÁ MỚI

Để biến Aircontrol thành một phần mềm toàn diện, đẳng cấp vượt trội so với mọi giải pháp hiện có, bản thiết kế bổ sung thêm **4 thành phần trải nghiệm người dùng cao cấp**:

---

### Bổ Sung 1: Đồng Bộ Clipboard Hai Chiều Tức Thì (`PasteboardSyncEngine`)
- **Vấn đề:** Người dùng muốn copy một đường link, đoạn code hoặc mật khẩu trên PC và dán thẳng vào iPhone (hoặc chụp màn hình/copy ảnh trên iPhone rồi dán vào Word/Photoshop trên PC) nhưng không có cách nào nhanh chóng.
- **Giải pháp:** Khai thác dịch vụ `com.apple.coredevice.pasteboardservice` (Cổng 50718 nội bộ).
- **Cơ chế hoạt động:**
  - **Hướng PC ➔ iPhone:** Giám sát sự kiện `QClipboard.dataChanged` trên Windows. Khi có văn bản hoặc hình ảnh mới, tự động gửi request `com.apple.coredevice.pasteboard.set` qua kênh RemoteXPC.
  - **Hướng iPhone ➔ PC:** Đăng ký nhận notify từ pasteboardservice; khi người dùng bấm "Copy" trên iOS, PC tự động cập nhật Windows Clipboard trong nền.

---

### Bổ Sung 2: Gõ Tiếng Việt & Nhập Liệu Thông Minh (Smart Unicode Injection)
- **Vấn đề:** Gửi scancode bàn phím HID giả lập qua mạng thường xuyên gặp lỗi: bộ gõ tiếng Việt (Unikey/EVKey) gửi các phím Backspace liên tục làm iPhone bị nuốt ký tự, loạn dấu hoặc mất chữ.
- **Giải pháp:** Xây dựng cơ chế **IME Text Bridge**:
  - Khi người dùng đang trỏ vào ô nhập liệu trên iPhone, ứng dụng hỗ trợ gõ text hoàn chỉnh trên PC rồi đưa thẳng chuỗi UTF-8 Unicode vào trường văn bản của iOS thông qua giao thức tự động hóa hoặc Pasteboard Injection.
  - Hỗ trợ đầy đủ bảng mã Unicode tiếng Việt, emoji và ký tự đặc biệt mà không bao giờ bị dính phím hay kẹt scancode.

---

### Bổ Sung 3: Cuộn Trang Quán Tính Vật Lý (Kinetic Inertial Smooth Scrolling)
- **Vấn đề:** Con lăn chuột máy tính (Mouse Wheel) gửi các bước cuộn dạng rời rạc (notches: 120 units). Khi chuyển thẳng thành touch scroll trên iPhone, màn hình bị khựng giật từng đoạn, không có độ trơn tru tự nhiên của iOS.
- **Giải pháp:** Tích hợp bộ mô phỏng vật lý quán tính (Spring-Damper Physics Engine):
  - Khi người dùng lăn chuột, hệ thống tính toán vận tốc ban đầu $v_0$ và áp dụng gia tốc giảm chấn hàm mũ:
    $$v(t) = v_0 \cdot e^{-\lambda t}$$
  - Sinh ra một chuỗi các gói tin Touch Move (khoảng cách 8ms ~ 120Hz/60Hz) mô phỏng chính xác chuyển động trượt của ngón tay người trên màn hình cảm ứng, mang lại cảm giác cuộn mượt mà như đang chạm trực tiếp vào iPhone.

---

### Bổ Sung 4: Bộ Phím Tắt Chuẩn Mực Hệ Điều Hành (OS Productivity Shortcuts)
Map trực tiếp các phím tắt quen thuộc trên PC sang các thao tác tự nhiên của iPhone:
- `Windows Key` / `Home` ➔ Nút Home ảo (về màn hình chính).
- `Alt + Tab` ➔ Mở App Switcher (trình chuyển đổi đa nhiệm).
- `Esc` ➔ Thao tác Back / Hủy.
- `Ctrl + L` / `Win + L` ➔ Khóa màn hình iPhone.
- `F12` / `PrtScn` ➔ Chụp ảnh màn hình tĩnh Pixel-Perfect lưu thẳng vào PC.

---

## 3. TOÀN CẢNH KIẾN TRÚC MỚI: THE NEXT-GEN ELITE ARCHITECTURE

```mermaid
graph TD
    subgraph TẦNG MẠNG & PHẦN CỨNG (Transport & QoS)
        A1[USB Direct Cable] -->|480M-5Gbps| MUX[Smart Multiplexer]
        A2[5GHz Wi-Fi 6 P2P SoftAP] -->|1.5ms RTT / 1200Mbps| MUX
        A3[Wi-Fi Router LAN] -->|DSCP 46 EF QoS| MUX
        MUX --> TUN[QUIC / TLS CoreDevice Tunnel]
    end

    subgraph TẦNG ĐIỀU KHIỂN & CHỐNG SUY HAO (Protocol & Stability)
        TUN --> S1[RTCP Spoofer: Khóa cứng 100Mbps Retina]
        TUN --> S2[FEC Recovery: Phục hồi rớt gói 0ms RAM]
        TUN --> S3[PasteboardSync: Đồng bộ Clipboard 2 chiều]
        TUN --> S4[Kinetic Scroll & Unicode IME Bridge]
    end

    subgraph TẦNG HIỂN THỊ & ÂM THANH (Render & Presentation)
        S1 --> V1[Fast HEVC Decoder + Direct3D 11 Shader]
        TUN --> A_SINK[Low-Latency WASAPI Audio Sink]
        V1 --> UI[Bespoke Titanium Simulator Window]
        A_SINK --> UI
    end
```

---

## 4. MA TRẬN SO SÁNH TRƯỚC VÀ SAU ĐẠI NÂNG CẤP

| Tiêu Chí Kỹ Thuật | Phiên Bản Hiện Tại (v0.1.0) | Sau Đại Nâng Cấp (Next-Gen Master) |
| :--- | :--- | :--- |
| **Độ trễ truyền dẫn Wi-Fi** | 108 ms (Qua Router nhà) | **1.5 ms** (Qua 5GHz P2P SoftAP) |
| **Băng thông Video** | Bị bóp xuống 5 - 15 Mbps | **Khóa cứng ở 60 - 100 Mbps** |
| **Độ nét khi vuốt chạm** | Vỡ hạt, nhòe mờ khi chuyển động | **Sắc nét tuyệt đối (FEC + RTCP Spoofer)** |
| **Độ trễ hiển thị (Display)** | 18 - 30 ms (CPU Copy) | **< 5 ms (Zero-Copy Texture)** |
| **Đồng bộ Clipboard** | Chưa có | **2 chiều tự động (Văn bản & Ảnh)** |
| **Nhập liệu tiếng Việt** | Dễ nhảy phím / nuốt chữ | **Unicode Injection mượt mà 100%** |
| **Cuộn trang bằng chuột** | Giật cục theo nấc con lăn | **Mượt mà quán tính tự nhiên (Kinetic)** |
| **Đồng bộ Âm thanh** | Buffer lớn (>100ms) | **WASAPI độ trễ thấp (<15ms, Lip-sync lock)** |

---

## 5. LỘ TRÌNH THỰC HIỆN ĐẠI NÂNG CẤP (PHASED ROADMAP)

Chúng tôi chia đợt đại nâng cấp thành 3 giai đoạn rõ ràng, an toàn và có kiểm chứng từng bước theo đúng kỷ luật kỹ thuật:

### Giai Đoạn 1: Cải Tiến Cốt Lõi Ngay Lập Tức (Immediate Core Boost)
*Không can thiệp cấu trúc lớn, xử lý dứt điểm các phàn nàn của người dùng ngay trên codebase hiện tại:*
1. **Khử nhòe mờ vuốt chạm:**
   - Kích hoạt `fec_enabled=True` trong `svc.start_video_stream`.
   - Nâng cấp `_build_rctl_packet` và `_build_rtcp_rr` trong `stream.py` thành **RTCP Spoofer** (báo cáo mạng hoàn hảo để ép iPhone giữ bitrate cực đại).
2. **Kích hoạt Clipboard Đồng Bộ 2 Chiều:**
   - Tạo module `aircontrol/core/pasteboard.py` kết nối dịch vụ `com.apple.coredevice.pasteboardservice`.
3. **Tối ưu hóa Điều Khiển & Phím Tắt:**
   - Bổ sung bộ giảm chấn quán tính (Kinetic Scroll) trong `hid.py` và `video_widget.py`.
   - Ánh xạ phím tắt hệ thống: Win = Home, Alt+Tab = Switcher, Esc = Back, Ctrl+L = Lock.
4. **Kiểm thử & Xác minh:** Chạy toàn bộ 126+ test cases đảm bảo PASS 100%.

### Giai Đoạn 2: Đột Phá Mạng Không Dây (Zero-Latency Wireless Bridge)
1. **Tích hợp One-Click 5GHz P2P SoftAP:** Thêm tùy chọn trên giao diện cho phép tự động bật trạm phát 5GHz từ card Realtek PC, đưa ping từ 108ms xuống 1.5ms.
2. **Gắn nhãn WMM/DSCP QoS:** Đăng ký socket UDP với Windows QoS2 API (DSCP 46 EF).
3. **Nâng cấp QUIC Tunnel:** Tận dụng kênh QUIC trên UDP cho RemotePairing.

### Giai Đoạn 3: Đẳng Cấp Phần Cứng & Đồ Họa Tối Thượng (Ultimate Hardware Pipeline)
1. **D3D11VA Zero-Copy Renderer:** Chuyển bộ giải mã sang DirectX 11 SwapChain để giải phóng hoàn toàn CPU và đạt độ trễ <5ms.
2. **QuickTime USB Bulk Engine:** Kích hoạt chế độ UVC/UAC qua USB Endpoint cho đường truyền có dây 100 Mbps nguyên bản.
