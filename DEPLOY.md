# Huong dan trien khai len Raspberry Pi

Tai lieu nay huong dan nap code chay SmartLock (nhan dien khuon mat + mo khoa) len Raspberry Pi Zero 2W va cau hinh chay nen tu dong khi cap nguon.

> Setup thuc te: user `pizero2w`, thu muc `~/edge-device/Edge-Device` (clone tu GitHub), venv trong `~/edge-device/Edge-Device/venv`. Cac vi du ben duoi dung dung cac path nay.

---

## 1. Tong quan kien truc

**Mo hinh moi (web-seeded hierarchy):** Building -> Floor -> Room -> Door -> Device. Moi Pi = 1 dong `devices` do WEB tao san (seed `DOOR_101`..`DOOR_302`, kem `room_id` + `door_id`). Pi **chi doc** `id` + `room_id` tu bang `devices` theo `device_code` -- KHONG tu tao/sua dong device.

**Lenh dieu khien qua bang `device_commands` (command-driven, khong phai recognition lien tuc):**

- Idle: TFT hien "WELCOME TO SMART LOCK", camera dong.
- Moi `POLL_INTERVAL = 3s`: Pi poll 1 lenh `pending` cua chinh no (`device_id = id cua Pi`) -> chay trong **worker thread** -> update `status` + `result_message`.
- Web gui lenh = INSERT vao `device_commands` (theo `device_id` uuid, khong con hardcode DOOR_01).

| Thanh phan | Chay o dau |
|---|---|
| `main.py` (nhan lenh, nhan dien, mo khoa, heartbeat) | Raspberry Pi (GPIO, SPI, camera, relay) |
| `register_face_multi.py` (dang ky khuon mat, CLI tuong tac) | Raspberry Pi |
| `tft_ui.py` + `registration.py` (TFT + flow dang ky 3 pose dung chung) | Raspberry Pi |
| `supabase_client.py` (dong bo, queue offline, heartbeat) | Chay chung tren Pi, goi API Supabase |
| `fina_rescue.py` + `fina-rescue.timer` (cuu service dang bi stop) | Raspberry Pi (chay root, moi 10s) |
| `diag_face_db.py`, `calibrate_threshold.py` (cong cu kiem tra) | Raspberry Pi |
| Supabase (database, storage, RLS) | Cloud -- da host san |
| Frontend Angular (dashboard, device picker) | Host rieng (Vercel/Netlify) hoac local |

> Python code **khong the** chay tren server tu xa vi phai truc tiep dieu khien phan cung (GPIO/SPI/camera/relay). Chi `supabase_client.py` la cross-platform (test duoc tren PC dev).

---

## 2. Cac file tren Pi

Clone ca repo (khuyen nghi) roi keo ve bang `git pull` moi lan cap nhat:

```bash
git clone https://github.com/KieuVii/Edge-Device.git ~/edge-device/Edge-Device
```

| File | Mo ta |
|---|---|
| `main.py` | Chuong trinh chinh: poll lenh, nhan dien (checkin/checkout), dang ky tu xa, relay, heartbeat, watchdog systemd |
| `register_face_multi.py` | Dang ky khuon mat CLI (ten qua argv hoac nhap tay; **phai co face_profiles tren web truoc**) |
| `tft_ui.py` | Driver TFT ILI9341 dung chung (GPIO24/25 + SPI0.0) |
| `registration.py` | Flow thu 3 pose x 5 mau (15 mau) dung chung cho CLI va main.py |
| `supabase_client.py` | Thu vien dong bo Supabase (queue offline, heartbeat, device lookup, record access) |
| `fina.service` | Unit systemd: main.py tu chay khi cap nguon (`Type=notify` + `WatchdogSec=30`) |
| `fina_rescue.py` + `fina-rescue.service` + `fina-rescue.timer` | Tu dong bat lai fina khi co lenh pending tu web (cuu service bi stop, khong can SSH) |
| `diag_face_db.py` | Kiem tra face_db.npy: `list` / `remove <idx>` (backup .bak) / diag day du + live match |
| `calibrate_threshold.py` | `collect known\|unknown N` + `score` -> do lech phan phoi cosine, de xuat threshold |
| `requirements.txt` | Danh sach thu vien Python |

**Khong nam trong repo, phai dat canh script** (trong thu muc lam viec, systemd dung `WorkingDirectory` tro vao do):
- Model ONNX: `face_detection_yunet_2023mar.onnx`, `face_recognition_sface_2021dec.onnx` (tai tu OpenCV Zoo)
- `.env` (tao tay, xem muc 4)
- `face_db.npy` (tu sinh boi luong dang ky; key = `face_profiles.face_name` chinh xac, moi key = list 3 templates)

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
SUPABASE_SERVICE_KEY=<service_role_key>

# Dinh danh thiet bi: phai khop device_code do WEB seed trong bang devices
# (DOOR_101..DOOR_302). Dong device do web tao kem room_id/door_id; Pi chi
# doc id + room_id tu bang devices (KHONG tu tao/sua dong device).
DEVICE_CODE=DOOR_101
DEVICE_NAME=Raspberry Pi Door Device

# Tuy chon (hien tai Pi khong gui ip_address len; co the bo)
# DEVICE_IP=10.198.146.113

# DRY_RUN=1: chi in payload ra console, KHONG gui len Supabase (dung de test tren PC)
DRY_RUN=0
```

> **Quan trong:** Pi dung **service_role key** -> RLS bi bypass phia device (web moi bi RLS chan). Key nay chi dat tren Pi, khong commit, khong chia se. Neu `DEVICE_CODE` sai / dong device chua duoc seed, Pi log canh bao `KHONG tim thay device_code=...`, sync tat (lenh nam pending, khong crash) -- recognition va mo khoa van hoat dong, chi khong gui log.

Dat model ONNX trong cung thu muc:

```bash
cp face_detection_yunet_2023mar.onnx face_recognition_sface_2021dec.onnx ~/edge-device/Edge-Device/
```

---

## 5. Dang ky khuon mat

> **Cach khuyen nghi (tu web):** tao user + `face_profiles` tren web (chon Phong, status pending), roi bam **Register Face** -> chon Phong -> Thiet bi. Web set status `pending`, INSERT lenh `start_register_face` voi payload `{face_name}` vao `device_commands`. Pi (main.py dang chay) tu dong mo man hinh scan 3 pose, ghi `face_db.npy`, update `face_profiles.status = registered` (web tu set `registered_by_device_id` sau khi lenh `done`). Khong can SSH.

> **Cach thay the (CLI tren Pi):** truoc tien phai tao user + `face_profiles` tren web (dung chinh xac `face_name`), roi:

```bash
sudo systemctl stop fina   # main.py dang giu camera/GPIO, phai dung truoc
cd ~/edge-device/Edge-Device
source venv/bin/activate
python register_face_multi.py "Vo Minh Hieu"   # hoac khong ten -> se hoi nhap tay
sudo systemctl start fina  # chay lai dich vu
```

- Nhin vao camera, giu ye dau theo 3 pose (NHIN THANG / NGHIENG TRAI / NGHIENG PHAI, moi pose 5 mau, timeout 60s).
- Loc anh mo (Laplacian variance >= 25) va mat nho (< 60px); moi pose luu **template trung binh L2-normalized** (3 templates/nguoi).
- Neu cosine giua cac pose < 0.50: canh bao nen dang ky lai voi anh sang tot.
- Sau khi xong: `face_profiles` tren Supabase tu cap nhat `status = registered`, Pi tu nhan dien duoc ngay.

---

## 6. Hop dong lenh tu web (`device_commands`)

| Lenh | Payload | Pi xu ly | Ket qua |
|---|---|---|---|
| `start_checkin` | `{}` | Mo camera, verify toi `VERIFY_TIMEOUT = 45s`; match >= 0.40 -> `granted` + mo relay 3s; nguoc lai `unknown` (khong profile / score < 0.15) hoac `denied` | Ghi `access_logs` (result, similarity, threshold 0.40, `access_type` = checkin/checkout, `room_id` = **phong cua device**, `user_id`/`face_profile_id` tu profile) + update lenh |
| `start_checkout` | `{}` | Nhu tren voi `access_type = checkout` | Nhu tren |
| `start_register_face` | `{face_name}` | Scan 3 pose (60s/pose), ghi `face_db.npy`, `mark_face_registered` (status registered + registered_by_device_id), reload face_db + profiles | `done`/`failed` + `result_message` |
| `manual_unlock` | `{}` | Mo relay 3s (`door_status` unlocked -> locked) | `done` |
| `lock_door` | `{}` | Relay tat + `door_status = locked` | `done` |
| `restart_camera` | `{}` | Mo camera + doc 3 frame kiem tra | `done` (frames OK) / `failed` + `devices.status = error` |
| `sync_face_db` | `{}` | Prune template khong con tren `face_profiles` + reload | `done` |
| `restart_service` | `{}` | Huy cac lenh restart pending khac (`cancel_other_restarts`), mark done, roi **re-exec chinh no** (execv cung PID -- systemd khong thay process thoat, khong phu thuoc `Restart=`), fallback `sys.exit(0)` | `done` |

- **Vong doi status:** `pending` -> `running` -> `done` | `failed` | `cancelled`; Pi ghi `result_message` + `executed_at`.
- **Khoi dong lai:** `recover_stale_commands()` danh dau moi lenh `running` con sot la `failed` ("Bi gian doan khi Pi khoi dong lai").
- **RLS (chi chan web):** member chi INSERT duoc `start_checkin`/`start_checkout` khi la member cua phong co device (`room_permissions.permission_status = allowed`) va `requested_by = chinh ho`; admin lam duoc moi lenh. Pi dung service key nen khong bi chan.
- **Camera loi** trong checkin/checkout/register -> `devices.status = error` (web hien thi).

---

## 7. Co che van hanh (can biet de debug)

- **Poll lenh:** moi 3s, `fetch_pending_command()`: `device_id = Pi`, `status = pending`, order `requested_at`, limit 1. Lenh chay trong **worker thread** (`_command_busy` chan lenh chong nhau) de main loop khong block; `restart_service` duoc xu ly ngay ca khi lenh khac dang ket (thoat hiem).
- **Heartbeat:** moi 15s `devices.status = online` + `last_seen` (web tu coi offline khi last_seen qua 60s). `set_device_error()` -> `error`; khi thoat -> `offline`.
- **Watchdog systemd:** `Type=notify` + `WatchdogSec=30`. main.py gui `READY=1` sau khi init xong va `WATCHDOG=1` moi 10s tu **daemon thread rieng** (raw AF_UNIX sd_notify socket, khong dung binary `systemd-notify`) -- lenh dai (45s/180s) khong bao gio bi kill; process tre > 30s (blackhole mang, camera treo) thi systemd tu kill + restart. Khi chay tay bang `python main.py` (khong co systemd) ping la no-op, vo hai.
- **Queue offline (`pending_ops.db`):** moi ghi (access_logs/alerts/devices/face_profiles/command status) vao sqlite + worker thread gui lai; loi mang -> retry; loi vinh vien (401/403/404/400/RLS 42501) -> log roi bo. Client co `postgrest_client_timeout=8`/`storage_client_timeout=8` (khong bao gio treo vo han khi mat mang).
- **fina-rescue:** moi 10s (root): neu `fina` KHONG active va co lenh pending cua device -> `restart_service` thi danh `done` ("Service da duoc khoi dong lai tu xa (fina-rescue)") + `systemctl start fina`; lenh khac -> chi start fina (Pi tu xu ly). -> Bam "Restart" tren UI cuu duoc service dang bi **stop**.
- **Dong bo xoa user:** moi 60s `sync_face_db()` xoa template trong `face_db.npy` khong con `face_name` trong `face_profiles` (deleting user tren web -> Pi ngung nhan dien trong ~60s).

---

## 8. Chay nhanh de kiem tra (debug)

```bash
cd ~/edge-device/Edge-Device && source venv/bin/activate
python main.py
```

Kiem tra sau khi chay:

- Log khoi dong: `Device 'DOOR_101' (id=..., room_id=...)`, `HE THONG SMART LOCK DA SAN SANG - doi lenh tu web (Register/Checkin/Checkout/Restart)`.
- Man hinh TFT hien "WELCOME TO SMART LOCK" (idle, camera dong).
- Tren web: thiet bi hien **online**; bam Checkin/Checkout/Register/Restart theo Phong -> Thiet bi.
- Moi lan nhan dien: dong moi trong `access_logs` (granted/denied/unknown, kem `access_type`, `room_id` = phong device).
- Anh khuon mat (neu co `local_image`) duoc upload len Storage bucket `access-captures` (bucket **private** -- web khong hien thi anh, chi luu URL).

Thoat: `Ctrl+C` (Pi gui `status = offline`).

> **Binh thuong KHONG can chay tay** -- da co `fina.service` tu dong chay khi cap nguon (muc 9). Chay tay chi khi debug, va nho dung `sudo systemctl stop fina` truoc.

---

## 9. Tu dong chay khi cap nguon (service)

### 9.1. Cai dat

Cac file `fina.service`, `fina-rescue.service`, `fina-rescue.timer` da co san trong repo:

```bash
cd ~/edge-device/Edge-Device && git pull
sudo cp fina.service fina-rescue.service fina-rescue.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fina                  # enable = tu chay khi cap nguon; --now = chay ngay
sudo systemctl enable --now fina-rescue.timer     # moi 10s: bat lai fina khi co lenh pending tu web
sudo systemctl status fina
```

### 9.2. Xem log

```bash
journalctl -u fina -f
journalctl -u fina-rescue -f      # log cua bo cuu ho (chi xuat hien khi co lenh pending + fina tat)
systemctl list-timers fina-rescue # kiem tra timer dang hoat dong
```

### 9.3. Quan ly

```bash
sudo systemctl stop fina     # dung (truoc khi chay register_face_multi.py thuc cong hoac diag)
sudo systemctl start fina    # chay lai
sudo systemctl restart fina  # sau khi git pull, khoi dong lai de nap code moi
sudo systemctl disable fina  # bo tu dong chay khi cap nguon (it khi can)
```

> **Watchdog:** `Type=notify` + `WatchdogSec=30` trong unit: main.py gui `READY=1` sau khoi dong va `WATCHDOG=1` moi 10s qua sd_notify raw socket; neu process tre >30s (blackhole mang, camera treo...) systemd tu kill + restart. `Restart=always`: neu main.py crash thi systemd tu chay lai sau 5 giay. `SIGTERM` duoc main.py xu ly sach (set device offline + flush queue) truoc khi thoat.
>
> **fina-rescue:** `fina-rescue.timer` (moi 10s, chay root) kiem tra `fina` con song khong; neu tat ma co lenh pending tu web thi tu dong `systemctl start fina` -- bam "Restart" tren UI cuu duoc service dang bi **stop** (khong can SSH). Lenh `restart_service` duoc danh `done` boi rescue de tranh restart 2 lan.
>
> **Restart tu web khi service dang chay:** Pi nhan `restart_service` -> `cancel_other_restarts` (huy cac lenh restart pending khac -- tranh loop do click nhieu lan) -> `execv` cung PID (systemd khong thay process thoat, khong can `Restart=`) -> boot lai -> online.

---

## 10. Xu ly loi thuong gap

| Hien tuong | Nguyen nhan / Cach xu ly |
|---|---|
| Service **start/stop lap lai lien tuc** (journal day `Scheduled restart job`) | main.py crash o khoi dong (vi du loi Python) + `Restart=always` -> loop moi 5s. Xem loi that su: `journalctl -u fina -n 50 --no-pager`. Code moi nhat (`git pull`) da fix loi `_command_busy`; neu van crash, sua loi roi `sudo systemctl restart fina` |
| Log `KHONG tim thay device_code='DOOR_01'` | Sai `DEVICE_CODE` trong `.env` hoac dong device chua duoc web seed. Sua .env (vd `DOOR_101`) / seed devices tren web; sync tat, lenh nam pending, khong crash |
| Service bi `stop` (khong crash) roi khong len lai | Binh thuong da co `fina-rescue.timer` tu bat khi co lenh pending; neu muon bat ngay: `sudo systemctl start fina` |
| Loi SPI / `Permission denied` khi mo `spi` | Chua bat SPI hoac thieu quyen: `sudo raspi-config` bat SPI, `sudo usermod -aG spi,gpio pizero2w`, reboot |
| `ModuleNotFoundError: opencv` | Chay trong venv: `source ~/edge-device/Edge-Device/venv/bin/activate` truoc |
| Loi thieu `libGL` khi import cv2 | Cai `opencv-python-headless` |
| Camera khong mo (`VideoCapture(0)` fail) | Bat Camera trong raspi-config; USB camera kiem tra `/dev/video0`; Pi set `devices.status = error`. Lenh `restart_camera` de test lai tu web |
| Loi `KHONG MO DUOC GPIO/SPI` khi chay register_face_multi.py | `fina.service` dang chay va giu GPIO/SPI: `sudo systemctl stop fina` roi chay lai |
| Loi `42501 ... row-level security` tren WEB khi gui lenh checkin/checkout | User khong phai member phong cua device (`room_permissions`) -- admin them member vao phong; admin thi khong bi chan |
| Queue `pending_ops.db` co ban ghi loi | Co su co mang/RLS; worker tu retry, loi vinh vien tu bo. Xoa duoc bang: `rm ~/edge-device/Edge-Device/pending_ops.db` |
| Lenh "Register Face" tren web khong duoc xu ly | Pi offline hoac main.py khong chay: `systemctl status fina`, `journalctl -u fina`; kiem tra `face_name` payload khop `face_profiles.face_name` |
| Lenh checkin/checkout khong duoc xu ly | Member khong co `room_permissions.allowed` cho phong cua device -> RLS chan INSERT (xem dong tren) |
| Chu tieng Viet in loan tren terminal | Khong anh huong tren Pi (Linux dung UTF-8), chi xay ra tren Windows console (set `PYTHONIOENCODING=utf-8`) |
| Muon test nhanh khong can phan cung | Sua `DRY_RUN=1` trong `.env` de chi in payload, khong gui Supabase (goi ham cua `supabase_client.py`, khong chay main.py tren PC) |

---

## 11. Ghi chu bao mat

- File `.env` chua **service_role key** -- khong commit len Git, khong chia se, chi dat tren Pi.
- Pi dung service key nen **RLS bi bypass phia device**; toan bo gioi han quyen do web (RLS) quan ly: member chi gui duoc checkin/checkout cho phong minh, admin lam moi lenh.
- Dat mat khau user Pi manh va han che mo SSH ra ngoai mang cong cong.