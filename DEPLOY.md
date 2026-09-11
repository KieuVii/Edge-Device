# Huong dan trien khai len Raspberry Pi

Tai lieu nay huong dan nap code chay SmartLock (nhan dien khuon mat + mo khoa) len Raspberry Pi thong qua PuTTY/SCP.

---

## 1. Tong quan kien truc

| Thanh phan | Chay o dau |
|---|---|
| `main.py` (nhan dien + mo khoa) | Raspberry Pi (dieu khien GPIO, SPI, camera, relay) |
| `register_face_multi.py` (dang ky khuon mat) | Raspberry Pi |
| `supabase_client.py` (dong bo du lieu) | Chay chung tren Pi, goi API Supabase |
| Supabase (database, storage, RLS) | Cloud -- da host san |
| Frontend Angular (dashboard) | Host rieng (Vercel/Netlify) hoac local |

> Python code **khong the** chay tren server tu xa vi phai truc tiep dieu khien phan cung (GPIO/SPI/camera/relay).

---

## 2. Cac file can nap len Pi

Chi can **4 file** trong thu muc du an:

| File | Mo ta |
|---|---|
| `main.py` | Chuong trinh chinh: nhan dien khuon mat, ghi access_logs/alerts, dieu khien relay |
| `register_face_multi.py` | Dang ky khuon mat cho nguoi dung |
| `supabase_client.py` | Thu vien dong bo Supabase (queue offline, upload anh, heartbeat) |
| `requirements.txt` | Danh sach thu vien Python can cai |

Khong can nap: `.env.example`, `.gitignore`, `supabase_rls_policies.sql` (da chay xong tren Supabase), `pending_ops.db` (tu tao), thu muc `captures/` (tu tao).

---

## 3. Truyen file len Pi

### Cach A -- PSCP (di kem bo PuTTY)

Tren Windows, trong thu muc chua `pscp.exe` / `plink.exe`:

```bat
:: Tao thu muc tren Pi
plink -pw <PASSWORD> pi@<IP_PI> "mkdir -p ~/fina"

:: Copy 4 file
pscp -pw <PASSWORD> D:\Samsung-Project\Edge-Device\main.py ^
                     D:\Samsung-Project\Edge-Device\register_face_multi.py ^
                     D:\Samsung-Project\Edge-Device\supabase_client.py ^
                     D:\Samsung-Project\Edge-Device\requirements.txt ^
                     pi@<IP_PI>:/home/pi/fina/
```

Thay `<IP_PI>` bang IP cua Pi (kiem tra bang `ip a` tren Pi) va `<PASSWORD>` bang mat khau user `pi`.

### Cach B -- git clone (khuyen nghi neu co repo GitHub)

```bash
git clone <URL_REPO_GITHUB> ~/fina
cd ~/fina
git pull   # lan sau chi can keo ban moi
```

---

## 4. Tao file `.env` tren Pi

`.env` chua thong tin Supabase va dinh danh thiet bi. **Sao chep y het noi dung file `.env` dang co tren may tinh cua ban**:

```bash
nano ~/fina/.env
```

Noi dung mau (dien dung gia tri cua ban):

```ini
# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<publishable_key_hoac_service_role_key>

# Dinh danh thiet bi (khop device_code trong bang devices)
DEVICE_CODE=DOOR_01
DEVICE_NAME=Main Door Pi

# DRY_RUN=1: chi in payload ra console, KHONG gui len Supabase (dung de test)
DRY_RUN=0
```

> WARN `.env` bi `.gitignore` bo qua -- khong bao gio commit file nay len GitHub.

---

## 5. Cai dat phan cung va dependencies

### 5.1. Bat SPI va Camera

```bash
sudo raspi-config
```

- **Interface Options -> SPI -> Enable**
- **Interface Options -> Camera -> Enable**
- Chon **Finish** roi **Reboot**

### 5.2. Cai dependencies

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libatlas-base-dev

# Tao moi truong ao
python3 -m venv ~/fina/venv
source ~/fina/venv/bin/activate

# Cai thu vien
pip install --upgrade pip
pip install -r ~/fina/requirements.txt
```

### 5.3. Neu cai `opencv-python` bi loi (Pi 32-bit)

Code **khong dung cua so GUI** (man hinh hien thi qua TFT/SPI), nen dung ban headless cho nhe:

```bash
pip uninstall -y opencv-python
pip install opencv-python-headless
```

### 5.4. Phan quyen GPIO/SPI (neu can)

```bash
sudo usermod -aG spi,gpio pi
```

---

## 6. Dang ky khuon mat

> **Truoc tien phai tao user + `face_profiles` tren web** (frontend/Supabase). Ghi nho chinh xac `face_name`.

```bash
source ~/fina/venv/bin/activate
cd ~/fina
python register_face_multi.py
```

- Nhap dung `face_name` khop voi Supabase.
- Nhin vao camera, nghieng nhe dau de thu du 10 mau.
- Sau khi xong, `face_profiles` tren Supabase tu cap nhat `status = registered`.

---

## 7. Chay chuong trinh chinh

```bash
source ~/fina/venv/bin/activate
cd ~/fina
python main.py
```

Kiem tra sau khi chay:

- Man hinh TFT hien thi trang thai.
- Tren Dashboard: thiet bi `DOOR_01` hien **online**.
- Moi lan nhan dien: co dong moi trong bang `access_logs` (granted/denied/no_face) va `alerts` neu co canh bao.
- Anh khuon mat la duoc upload len Storage bucket `access-captures`.

Thoat chuong trinh: `Ctrl+C` (Pi gui `status = offline`).

---

## 8. Tu dong chay khi khoi dong (tuy chon)

### 8.1. Tao service

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

### 8.2. Kich hoat

```bash
sudo systemctl daemon-reload
sudo systemctl enable fina
sudo systemctl start fina
sudo systemctl status fina
```

Xem log truc tiep:

```bash
journalctl -u fina -f
```

---

## 9. Xu ly loi thuong gap

| Hien tuong | Nguyen nhan / Cach xu ly |
|---|---|
| Loi SPI / `Permission denied` khi mo `spi` | Chua bat SPI hoac thieu quyen: `sudo raspi-config` bat SPI, `sudo usermod -aG spi,gpio pi`, reboot |
| `ModuleNotFoundError: opencv` | Chay `source ~/fina/venv/bin/activate` truoc, hoac cai lai opencv |
| Loi thieu `libGL` khi import cv2 | Cai `opencv-python-headless` |
| Camera khong mo (`VideoCapture(0)` fail) | Bat Camera trong raspi-config; USB camera kiem tra `/dev/video0` |
| Loi `42501 ... row-level security` | Thieu policy RLS -- chay lai `supabase_rls_policies.sql` (gom policy SELECT moi) tren Supabase |
| Queue `pending_ops.db` co ban ghi loi | Co su co mang/RLS; worker tu retry. Xoa duoc bang: `rm ~/fina/pending_ops.db` |
| Chu tieng Viet in loan tren terminal | Khong anh huong tren Pi (Linux dung UTF-8), chi xay ra tren Windows console |
| Muon test nhanh khong can phan cung | Sua `DRY_RUN=1` trong `.env` de chi in payload, khong gui Supabase |

---

## 10. Ghi chu bao mat

- File `.env` chua key truy cap Supabase -- khong commit len Git, khong chia se.
- Key dang dung la **publishable key** (quyen anon). Neu muon an toan toi da, thay bang **service_role key** trong `.env` (luu ky, chi dat tren Pi) -- khi do khong can cac policy RLS.
- Dat mat khau `pi` manh va han che mo SSH ra ngoai mang cong cong.