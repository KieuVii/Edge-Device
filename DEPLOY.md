# Huong dan trien khai len Raspberry Pi

Tai lieu nay huong dan nap code chay SmartLock (nhan dien khuon mat + mo khoa) len Raspberry Pi Zero 2W va cau hinh chay nen tu dong khi cap nguon.

> Setup thuc te: user `pizero2w`, thu muc `~/edge-device/Edge-Device` (clone tu GitHub), venv trong `~/edge-device/Edge-Device/venv`. Cac vi du ben duoi dung dung cac path nay.

---

## 1. Tong quan kien truc

| Thanh phan | Chay o dau |
|---|---|
| `main.py` (nhan dien + mo khoa + nhan lenh dang ky tu xa) | Raspberry Pi (GPIO, SPI, camera, relay) |
| `register_face_multi.py` (dang ky khuon mat, CLI tuong tac) | Raspberry Pi |
| `tft_ui.py` + `registration.py` (man hinh TFT + flow dang ky dung chung) | Raspberry Pi |
| `supabase_client.py` (dong bo du lieu, queue offline) | Chay chung tren Pi, goi API Supabase |
| Supabase (database, storage, RLS) | Cloud -- da host san |
| Frontend Angular (dashboard) | Host rieng (Vercel/Netlify) hoac local |

> Python code **khong the** chay tren server tu xa vi phai truc tiep dieu khien phan cung (GPIO/SPI/camera/relay). Chi `supabase_client.py` la cross-platform (test duoc tren PC dev).

---

## 2. Cac file tren Pi

Clone ca repo (khuyen nghi) roi keo ve bang `git pull` moi lan cap nhat:

```bash
git clone https://github.com/KieuVii/Edge-Device.git ~/edge-device/Edge-Device
```

Cac file quan trong:

| File | Mo ta |
|---|---|
| `main.py` | Chuong trinh chinh: nhan dien khuon mat, ghi access_logs/alerts, relay, poll lenh dang ky tu web |
| `register_face_multi.py` | Dang ky khuon mat (CLI, ten qua argv hoac nhap tay) |
| `tft_ui.py` | Driver TFT ILI9341 dung chung (GPIO24/25 + SPI0.0) |
| `registration.py` | Flow thu 3 pose (15 mau) dung chung cho CLI va main.py |
| `supabase_client.py` | Thu vien dong bo Supabase (queue offline, upload anh, heartbeat) |
| `requirements.txt` | Danh sach thu vien Python |
| `fina.service` | Unit systemd de main.py tu chay khi cap nguon (xem muc 8) |

**Khong nam trong repo, phai dat canh script** (trong thu muc lam viec):
- Model ONNX: `face_detection_yunet_2023mar.onnx`, `face_recognition_sface_2021dec.onnx` (tai tu OpenCV Zoo)
- `.env` (tao tay, xem muc 4)
- `face_db.npy` (tu sinh boi luong dang ky)

Khong can nap: `.env.example`, `.gitignore`, `supabase_rls_policies.sql` (da chay xong tren Supabase), `pending_ops.db` (tu tao), thu muc `captures/` (tu tao).

---

## 3. Cau hinh Pi

```bash
sudo raspi-config
```

- **Interface Options -> SPI -> Enable**
- **Interface Options -> Camera -> Enable**
- Chon **Finish** roi **Reboot**

Cai dependencies (lam 1 lan):

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libatlas-base-dev

python3 -m venv ~/edge-device/Edge-Device/venv
source ~/edge-device/Edge-Device/venv/bin/activate
pip install --upgrade pip
pip install -r ~/edge-device/Edge-Device/requirements.txt
```

> Code **khong dung cua so GUI** (hien thi qua TFT/SPI), dung `opencv-python-headless` cho nhe. Neu `opencv-python` bi loi `libGL`, cai lai: `pip uninstall -y opencv-python && pip install opencv-python-headless`.

Phan quyen GPIO/SPI (user phai nam trong nhom `spi`,`gpio`):

```bash
sudo usermod -aG spi,gpio pizero2w
```

---

## 4. Tao file `.env` tren Pi

`.env` chua thong tin Supabase va dinh danh thiet bi. **Sao chep noi dung file `.env` dang co tren may tinh cua ban** (file nay bi `.gitignore` bo qua, khong bao gio commit len GitHub):

```bash
nano ~/edge-device/Edge-Device/.env
```

Noi dung mau:

```ini
# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<publishable_key_hoac_service_role_key>

# Dinh danh thiet bi (khop device_code trong bang devices)
DEVICE_CODE=DOOR_01
DEVICE_NAME=Main Door Pi
DEVICE_IP=10.198.146.113

# DRY_RUN=1: chi in payload ra console, KHONG gui len Supabase (dung de test)
DRY_RUN=0
```

Dat model ONNX trong cung thu muc (systemd dung `WorkingDirectory` tro vao do):

```bash
cp face_detection_yunet_2023mar.onnx face_recognition_sface_2021dec.onnx ~/edge-device/Edge-Device/
```

---

## 5. Dang ky khuon mat

> **Cach khuyen nghi (tu web):** tao user + `face_profiles` tren web, roi bam nut **Register Face** trong trang Face Registration. Web gui lenh `start_register_face` vao `device_commands`, Pi (main.py dang chay) tu dong mo man hinh scan 3 pose va bao ket qua. Khong can SSH.

> **Cach thay the (CLI tren Pi):** truoc tien phai tao user + `face_profiles` tren web (dung chinh xac `face_name`), roi:

```bash
sudo systemctl stop fina   # main.py dang giu camera/GPIO, phai dung truoc
cd ~/edge-device/Edge-Device
source venv/bin/activate
python register_face_multi.py "Vo Minh Hieu"   # hoac khong ten -> se hoi nhap tay
sudo systemctl start fina  # chay lai dich vu
```

- Nhin vao camera, giu ye dau theo 3 pose (thang/trai/phai, moi pose 5 mau, timeout 60s).
- Sau khi xong, `face_profiles` tren Supabase tu cap nhat `status = registered`, Pi tu nhan dien duoc ngay.

---

## 6. Chay nhanh de kiem tra (debug)

```bash
cd ~/edge-device/Edge-Device && source venv/bin/activate
python main.py
```

Kiem tra sau khi chay:

- Man hinh TFT hien thi trang thai + camera view.
- Tren Dashboard: thiet bi `DOOR_01` hien **online**.
- Moi lan nhan dien: co dong moi trong bang `access_logs` (granted/denied/no_face) va `alerts` neu co canh bao.
- Anh khuon mat la duoc upload len Storage bucket `access-captures`.

Thoat: `Ctrl+C` (Pi gui `status = offline`).

> **Binh thuong KHONG can chay tay** -- da co `fina.service` tu dong chay khi cap nguon (muc 8). Chay tay chi khi debug, va nho dung `sudo systemctl stop fina` truoc.

---

## 7. Tu dong chay khi cap nguon (service)

### 7.1. Cai dat

File `fina.service` da co san trong repo:

```bash
cd ~/edge-device/Edge-Device && git pull
sudo cp fina.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fina    # enable = tu chay khi cap nguon; --now = chay ngay
sudo systemctl status fina
```

### 7.2. Xem log

```bash
journalctl -u fina -f
```

### 7.3. Quan ly

```bash
sudo systemctl stop fina     # dung (truoc khi chay register_face_multi.py thuc cong hoac diag)
sudo systemctl start fina    # chay lai
sudo systemctl restart fina  # sau khi git pull, khoi dong lai de nap code moi
sudo systemctl disable fina  # bo tu dong chay khi cap nguon (it khi can)
```

> `Restart=always` trong unit: neu main.py crash thi systemd tu chay lai sau 5 giay. `SIGTERM` duoc main.py xu ly sach (set device offline + flush queue) truoc khi thoat.

---

## 8. Xu ly loi thuong gap

| Hien tuong | Nguyen nhan / Cach xu ly |
|---|---|
| Loi SPI / `Permission denied` khi mo `spi` | Chua bat SPI hoac thieu quyen: `sudo raspi-config` bat SPI, `sudo usermod -aG spi,gpio pizero2w`, reboot |
| `ModuleNotFoundError: opencv` | Chay trong venv: `source ~/edge-device/Edge-Device/venv/bin/activate` truoc |
| Loi thieu `libGL` khi import cv2 | Cai `opencv-python-headless` |
| Camera khong mo (`VideoCapture(0)` fail) | Bat Camera trong raspi-config; USB camera kiem tra `/dev/video0` |
| Loi `KHONG MO DUOC GPIO/SPI` khi chay register_face_multi.py | `fina.service` dang chay va giu GPIO/SPI: `sudo systemctl stop fina` roi chay lai |
| Loi `42501 ... row-level security` | Thieu policy RLS -- chay lai `supabase_rls_policies.sql` (da idempotent, chay lai khong loi) tren Supabase SQL Editor |
| Queue `pending_ops.db` co ban ghi loi | Co su co mang/RLS; worker tu retry. Xoa duoc bang: `rm ~/edge-device/Edge-Device/pending_ops.db` |
| Lenh "Register Face" tren web khong duoc xu ly | Pi offline hoac main.py khong chay: `systemctl status fina`, xem `journalctl -u fina` |
| Chu tieng Viet in loan tren terminal | Khong anh huong tren Pi (Linux dung UTF-8), chi xay ra tren Windows console |
| Muon test nhanh khong can phan cung | Sua `DRY_RUN=1` trong `.env` de chi in payload, khong gui Supabase |

---

## 9. Ghi chu bao mat

- File `.env` chua key truy cap Supabase -- khong commit len Git, khong chia se.
- Key dang dung la **publishable key** (quyen anon). Neu muon an toan toi da, thay bang **service_role key** trong `.env` (luu ky, chi dat tren Pi) -- khi do khong can cac policy RLS.
- Dat mat khau user Pi manh va han che mo SSH ra ngoai mang cong cong.