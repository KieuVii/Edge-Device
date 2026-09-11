# Hướng dẫn triển khai lên Raspberry Pi

Tài liệu này hướng dẫn nạp code chạy SmartLock (nhận diện khuôn mặt + mở khóa) lên Raspberry Pi thông qua PuTTY/SCP.

---

## 1. Tổng quan kiến trúc

| Thành phần | Chạy ở đâu |
|---|---|
| `main.py` (nhận diện + mở khóa) | Raspberry Pi (điều khiển GPIO, SPI, camera, relay) |
| `register_face_multi.py` (đăng ký khuôn mặt) | Raspberry Pi |
| `supabase_client.py` (đồng bộ dữ liệu) | Chạy chung trên Pi, gọi API Supabase |
| Supabase (database, storage, RLS) | Cloud — đã host sẵn |
| Frontend Angular (dashboard) | Host riêng (Vercel/Netlify) hoặc local |

> Python code **không thể** chạy trên server từ xa vì phải trực tiếp điều khiển phần cứng (GPIO/SPI/camera/relay).

---

## 2. Các file cần nạp lên Pi

Chỉ cần **4 file** trong thư mục dự án:

| File | Mô tả |
|---|---|
| `main.py` | Chương trình chính: nhận diện khuôn mặt, ghi access_logs/alerts, điều khiển relay |
| `register_face_multi.py` | Đăng ký khuôn mặt cho người dùng |
| `supabase_client.py` | Thư viện đồng bộ Supabase (queue offline, upload ảnh, heartbeat) |
| `requirements.txt` | Danh sách thư viện Python cần cài |

Không cần nạp: `.env.example`, `.gitignore`, `supabase_rls_policies.sql` (đã chạy xong trên Supabase), `pending_ops.db` (tự tạo), thư mục `captures/` (tự tạo).

---

## 3. Truyền file lên Pi

### Cách A — PSCP (đi kèm bộ PuTTY)

Trên Windows, trong thư mục chứa `pscp.exe` / `plink.exe`:

```bat
:: Tạo thư mục trên Pi
plink -pw <PASSWORD> pi@<IP_PI> "mkdir -p ~/fina"

:: Copy 4 file
pscp -pw <PASSWORD> D:\Samsung-Project\Edge-Device\main.py ^
                     D:\Samsung-Project\Edge-Device\register_face_multi.py ^
                     D:\Samsung-Project\Edge-Device\supabase_client.py ^
                     D:\Samsung-Project\Edge-Device\requirements.txt ^
                     pi@<IP_PI>:/home/pi/fina/
```

Thay `<IP_PI>` bằng IP của Pi (kiểm tra bằng `ip a` trên Pi) và `<PASSWORD>` bằng mật khẩu user `pi`.

### Cách B — git clone (khuyến nghị nếu có repo GitHub)

```bash
git clone <URL_REPO_GITHUB> ~/fina
cd ~/fina
git pull   # lần sau chỉ cần kéo bản mới
```

---

## 4. Tạo file `.env` trên Pi

`.env` chứa thông tin Supabase và định danh thiết bị. **Sao chép y hệt nội dung file `.env` đang có trên máy tính của bạn**:

```bash
nano ~/fina/.env
```

Nội dung mẫu (điền đúng giá trị của bạn):

```ini
# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<publishable_key_hoac_service_role_key>

# Định danh thiết bị (khớp device_code trong bảng devices)
DEVICE_CODE=DOOR_01
DEVICE_NAME=Main Door Pi

# DRY_RUN=1: chỉ in payload ra console, KHÔNG gửi lên Supabase (dùng để test)
DRY_RUN=0
```

> ⚠️ `.env` bị `.gitignore` bỏ qua — không bao giờ commit file này lên GitHub.

---

## 5. Cài đặt phần cứng và dependencies

### 5.1. Bật SPI và Camera

```bash
sudo raspi-config
```

- **Interface Options → SPI → Enable**
- **Interface Options → Camera → Enable**
- Chọn **Finish** rồi **Reboot**

### 5.2. Cài dependencies

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libatlas-base-dev

# Tạo môi trường ảo
python3 -m venv ~/fina/venv
source ~/fina/venv/bin/activate

# Cài thư viện
pip install --upgrade pip
pip install -r ~/fina/requirements.txt
```

### 5.3. Nếu cài `opencv-python` bị lỗi (Pi 32-bit)

Code **không dùng cửa sổ GUI** (màn hình hiển thị qua TFT/SPI), nên dùng bản headless cho nhẹ:

```bash
pip uninstall -y opencv-python
pip install opencv-python-headless
```

### 5.4. Phân quyền GPIO/SPI (nếu cần)

```bash
sudo usermod -aG spi,gpio pi
```

---

## 6. Đăng ký khuôn mặt

> **Trước tiên phải tạo user + `face_profiles` trên web** (frontend/Supabase). Ghi nhớ chính xác `face_name`.

```bash
source ~/fina/venv/bin/activate
cd ~/fina
python register_face_multi.py
```

- Nhập đúng `face_name` khớp với Supabase.
- Nhìn vào camera, nghiêng nhẹ đầu để thu đủ 10 mẫu.
- Sau khi xong, `face_profiles` trên Supabase tự cập nhật `status = registered`.

---

## 7. Chạy chương trình chính

```bash
source ~/fina/venv/bin/activate
cd ~/fina
python main.py
```

Kiểm tra sau khi chạy:

- Màn hình TFT hiển thị trạng thái.
- Trên Dashboard: thiết bị `DOOR_01` hiện **online**.
- Mỗi lần nhận diện: có dòng mới trong bảng `access_logs` (granted/denied/no_face) và `alerts` nếu có cảnh báo.
- Ảnh khuôn mặt lạ được upload lên Storage bucket `access-captures`.

Thoát chương trình: `Ctrl+C` (Pi gửi `status = offline`).

---

## 8. Tự động chạy khi khởi động (tuỳ chọn)

### 8.1. Tạo service

```bash
sudo nano /etc/systemd/system/fina.service
```

```ini
[Unit]
Description=SmartLock Face Access
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/home/pi/fina/venv/bin/python /home/pi/fina/main.py
WorkingDirectory=/home/pi/fina
Restart=always
RestartSec=5
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 8.2. Kích hoạt

```bash
sudo systemctl daemon-reload
sudo systemctl enable fina
sudo systemctl start fina
sudo systemctl status fina
```

Xem log trực tiếp:

```bash
journalctl -u fina -f
```

---

## 9. Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân / Cách xử lý |
|---|---|
| Lỗi SPI / `Permission denied` khi mở `spi` | Chưa bật SPI hoặc thiếu quyền: `sudo raspi-config` bật SPI, `sudo usermod -aG spi,gpio pi`, reboot |
| `ModuleNotFoundError: opencv` | Chạy `source ~/fina/venv/bin/activate` trước, hoặc cài lại opencv |
| Lỗi thiếu `libGL` khi import cv2 | Cài `opencv-python-headless` |
| Camera không mở (`VideoCapture(0)` fail) | Bật Camera trong raspi-config; USB camera kiểm tra `/dev/video0` |
| Lỗi `42501 ... row-level security` | Thiếu policy RLS — chạy lại `supabase_rls_policies.sql` (gồm policy SELECT mới) trên Supabase |
| Queue `pending_ops.db` có bản ghi lỗi | Có sự cố mạng/RLS; worker tự retry. Xoá được bằng: `rm ~/fina/pending_ops.db` |
| Chữ tiếng Việt in loạn trên terminal | Không ảnh hưởng trên Pi (Linux dùng UTF-8), chỉ xảy ra trên Windows console |
| Muốn test nhanh không cần phần cứng | Sửa `DRY_RUN=1` trong `.env` để chỉ in payload, không gửi Supabase |

---

## 10. Ghi chú bảo mật

- File `.env` chứa key truy cập Supabase — không commit lên Git, không chia sẻ.
- Key đang dùng là **publishable key** (quyền anon). Nếu muốn an toàn tối đa, thay bằng **service_role key** trong `.env` (lưu kỹ, chỉ đặt trên Pi) — khi đó không cần các policy RLS.
- Đặt mật khẩu `pi` mạnh và hạn chế mở SSH ra ngoài mạng công cộng.