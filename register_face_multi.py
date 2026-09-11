import cv2
import numpy as np
import time
import spidev
import os
import sys
import unicodedata
from gpiozero import OutputDevice

import supabase_client as sb

if not sb.configured():
    print("\n>> Supabase chua duoc cau hinh (.env). Khong the dong bo face_profiles.")
    print(">> Hay dien SUPABASE_URL / SUPABASE_SERVICE_KEY / DEVICE_CODE trong .env roi chay lai.")
    exit(1)

# ==========================================
# 1. CAU HINH PHAN CUNG TFT
# ==========================================
try:
    DC_PIN = OutputDevice(24)   # Pin 18 (GPIO 24)
    RST_PIN = OutputDevice(25)  # Pin 22 (GPIO 25)
    RST_PIN.on()                # Keo chan RESET len muc HIGH (3.3V) de kich hoat man hinh
except Exception as exc:
    print("\n>> KHONG MO DUOC GPIO:", exc)
    print(">> Co the main.py hoac fina.service dang chay va giu GPIO.")
    print(">> Dung truoc roi chay lai: sudo systemctl stop fina  (hoac Ctrl+C terminal main.py)")
    exit(1)

spi = spidev.SpiDev()
try:
    spi.open(0, 0)
except OSError as exc:
    print("\n>> KHONG MO DUOC SPI (0,0):", exc)
    print(">> Thuong do main.py hoac fina.service dang chay va giu SPI bus.")
    print(">> Dung truoc roi chay lai: sudo systemctl stop fina  (hoac Ctrl+C terminal main.py)")
    exit(1)
spi.max_speed_hz = 24000000
spi.mode = 0

def send_cmd(cmd):
    DC_PIN.off()
    spi.writebytes([cmd])

def send_data(data):
    DC_PIN.on()
    if isinstance(data, int):
        spi.writebytes([data])
    elif isinstance(data, list):
        spi.writebytes(data)
    else:
        for i in range(0, len(data), 4096):
            spi.writebytes2(data[i:i+4096])

def init_tft():
    # Kich hoat phan cung man hinh
    RST_PIN.on()
    time.sleep(0.01)
    
    send_cmd(0x01); time.sleep(0.12) # SW Reset
    send_cmd(0x11); time.sleep(0.12) # Sleep Out
    
    send_cmd(0x3A); send_data(0x55)  # Chuan mau 16-bit RGB565
    send_cmd(0x36); send_data(0x70)  # Landscape 320x240
    send_cmd(0x20)                   # Inversion OFF (Mau thuc)
    
    # Nap chuoi thanh ghi dong bo quet xung tam nen
    send_cmd(0xB2); send_data([0x0C, 0x0C, 0x00, 0x33, 0x33])
    send_cmd(0xB7); send_data(0x35)
    send_cmd(0xBB); send_data(0x19)
    send_cmd(0xC0); send_data(0x2C)
    send_cmd(0xC2); send_data(0x01)
    send_cmd(0xC3); send_data(0x12)
    send_cmd(0xC4); send_data(0x20)
    send_cmd(0xC6); send_data(0x0F)
    
    send_cmd(0x29); time.sleep(0.05) # Display ON
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])

def render_tft(frame):
    # Khoa vung ghi lai truoc moi khung hinh
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])
    send_cmd(0x2C)

    frame_u16 = frame.astype(np.uint16)
    b = frame_u16[:, :, 0] >> 3
    g = frame_u16[:, :, 1] >> 2
    r = frame_u16[:, :, 2] >> 3
    rgb565 = (r << 11) | (g << 5) | b
    send_data(rgb565.byteswap().tobytes())

# ==========================================
# 2. KHOI TAO MO HINH AI & DATABASE
# ==========================================
cv2.setNumThreads(4)
detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.65)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')

db_file = "face_db.npy"
face_db = np.load(db_file, allow_pickle=True).item() if os.path.exists(db_file) else {}

POSE_COUNT = 3
SAMPLES_PER_POSE = 5
MIN_FACE_SIZE = 60
BLUR_MIN_VAR = 25.0
POSE_NAMES = ["NHIN THANG", "NGHIENG TRAI", "NGHIENG PHAI"]

def read_name(prompt):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    raw = sys.stdin.buffer.readline().rstrip(b"\r\n")
    for enc in ("utf-8", "cp1258", "latin-1"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace").strip()


def fold_name(name):
    name = name.replace("\u0111", "d").replace("\u0110", "D")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", name)
        if unicodedata.category(ch) != "Mn"
    )


def show_message(frame, lines, color=(255, 255, 255)):
    out = frame.copy()
    cv2.rectangle(out, (0, 0), (320, 240), (0, 0, 0), -1)
    y = 104 - (len(lines) - 1) * 15
    for line in lines:
        size = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
        x = max(0, (320 - size[0]) // 2)
        cv2.putText(out, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
        y += 28
    render_tft(out)
    return out


def render_capture(disp, user_name, pose_idx, pose_count, pose_name, pose_done,
                   samples_per_pose, total_done, total_target, msg, color):
    out = disp.copy()
    cv2.rectangle(out, (0, 0), (320, 58), (0, 0, 0), -1)
    cv2.putText(out, f"P{pose_idx}/{pose_count}: {pose_name}", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(out, f"{total_done}/{total_target}", (240, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(out, user_name.upper()[:20], (8, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.rectangle(out, (0, 200), (320, 240), (0, 0, 0), -1)
    cv2.putText(out, msg, (8, 221), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    bar_w = 180
    filled = int(bar_w * pose_done / samples_per_pose) if samples_per_pose else 0
    cv2.rectangle(out, (8, 228), (8 + bar_w, 236), (110, 110, 110), -1)
    cv2.rectangle(out, (8, 228), (8 + filled, 236), color, -1)
    return out


# Bat man hinh truoc, hien thi huong dan
init_tft()
print(">> TFT da khoi tao xong")
blank = np.zeros((240, 320, 3), dtype=np.uint8)
for _ in range(3):
    show_message(blank, ["DANG KY KHUON MAT", "NHAP TEN TREN TERMINAL"], (255, 255, 0))
    time.sleep(0.15)
print(">> Da gui man hinh huong dan - neu TFT van trang, xem loi in o tren terminal")

new_name = read_name("Nhap ten nguoi can dang ky (khop face_name tren Supabase): ")
if not new_name:
    print("Ten khong hop le!")
    exit(1)

profile = sb.find_face_profile(new_name)
if profile is None:
    show_message(blank, ["KHONG TIM THAY HO SO", f"'{fold_name(new_name)}'", "TREN SUPABASE"], (0, 0, 255))
    print(f"\n>> KHONG tim thay face_profiles '{new_name}' tren Supabase.")
    print(">> Hay tao user + face_profiles trong ung dung web truoc (face_name phai khop chinh xac), roi chay lai.")
    exit(1)

canonical_name = profile["face_name"]
sb.ensure_device()

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

features_by_pose = []
print(f">> Man hinh da bat! Hay nhin vao camera cho [{canonical_name}]...")
print(">> Moi pose thu 5 mau: nhin thang / nghieng trai / nghieng phai.")

try:
    for pose_idx in range(POSE_COUNT):
        pose_samples = []
        pose_name = POSE_NAMES[pose_idx]
        print(f">> POSE {pose_idx + 1}/{POSE_COUNT}: {pose_name}")
        if pose_idx > 0:
            show_message(blank, [f"POSE {pose_idx} XONG!", f"CHUYEN SANG POSE {pose_idx + 1}"], (0, 255, 255))
            time.sleep(1.2)
        while len(pose_samples) < SAMPLES_PER_POSE:
            ret, frame = cap.read()
            if not ret:
                continue

            frame = cv2.resize(frame, (320, 240))
            disp = frame.copy()

            detector.setInputSize((320, 240))
            _, faces = detector.detect(frame)

            if faces is not None and len(faces) > 0:
                areas = faces[:, 2] * faces[:, 3]
                face = faces[int(np.argmax(areas))]
                box = face[:4].astype(int)
                bx, by, bw, bh = box
                cv2.rectangle(disp, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)

                if bw >= MIN_FACE_SIZE and bh >= MIN_FACE_SIZE:
                    x0, y0 = max(0, bx), max(0, by)
                    x1, y1 = min(320, bx + bw), min(240, by + bh)
                    face_crop = frame[y0:y1, x0:x1]
                    if x1 - x0 < MIN_FACE_SIZE or y1 - y0 < MIN_FACE_SIZE:
                        msg = "CANH CHINH KHUON MAT"
                        color = (0, 0, 255)
                    else:
                        face_gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
                        sharpness = cv2.Laplacian(face_gray, cv2.CV_64F).var()
                        if sharpness >= BLUR_MIN_VAR:
                            aligned = recognizer.alignCrop(frame, face)
                            feat = recognizer.feature(aligned)
                            pose_samples.append(feat)
                            msg = f"{pose_name}: {len(pose_samples)}/{SAMPLES_PER_POSE}"
                            color = (0, 255, 255)
                            time.sleep(0.15)
                        else:
                            msg = "DO BI MO - GIU YEN"
                            color = (0, 0, 255)
                else:
                    msg = "DEN GAN HON"
                    color = (0, 0, 255)
            else:
                msg = "CANH CHINH KHUON MAT"
                color = (0, 0, 255)

            disp = render_capture(
                disp, fold_name(canonical_name), pose_idx + 1, POSE_COUNT,
                pose_name, len(pose_samples), SAMPLES_PER_POSE,
                pose_idx * SAMPLES_PER_POSE + len(pose_samples),
                POSE_COUNT * SAMPLES_PER_POSE, msg, color,
            )
            render_tft(disp)

        avg_feature = np.mean(pose_samples, axis=0)
        norm = np.linalg.norm(avg_feature)
        if norm > 0:
            avg_feature = avg_feature / norm
        features_by_pose.append(avg_feature)

    templates = features_by_pose

    internal_scores = []
    for i in range(len(templates)):
        for j in range(i + 1, len(templates)):
            internal_scores.append(
                recognizer.match(templates[i], templates[j], cv2.FaceRecognizerSF_FR_COSINE)
            )
    if internal_scores:
        print(f">> Chat luong template (cosine giua cac pose): min={min(internal_scores):.3f} max={max(internal_scores):.3f}")
        if min(internal_scores) < 0.50:
            print(">> WARN: Cac pose qua khac nhau (< 0.50) - nen dang ky lai voi anh sang tot hon.")

    # Hien thi thong bao hoan tat len man hinh
    cv2.rectangle(disp, (0, 0), (320, 240), (0, 0, 0), -1)
    cv2.putText(disp, "DANG KY HOAN TAT!", (25, 110),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
    cv2.putText(disp, f"USER: {fold_name(canonical_name).upper()}", (60, 150),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    render_tft(disp)

    for key in [k for k in face_db if k.lower() == canonical_name.lower() and k != canonical_name]:
        del face_db[key]

    face_db[canonical_name] = templates
    np.save(db_file, face_db)

    sample_total = POSE_COUNT * SAMPLES_PER_POSE
    sync_result = sb.mark_face_registered(canonical_name, sample_total)
    print(f"\n>> DA DANG KY XONG CHO [{canonical_name}] VOI {sample_total} MAU / {len(templates)} TEMPLATE!")
    print(f">> Danh sach hien co trong DB: {list(face_db.keys())}")
    if sync_result == "ok":
        print(f">> [Supabase] face_profiles '{canonical_name}' da cap nhat: registered.")
    elif sync_result == "queued":
        print(">> [Supabase] Mang khong on dinh - cap nhat face_profiles se gui lai khi co mang.")
    else:
        print(">> [Supabase] Khong the cap nhat face_profiles (chua cau hinh hoac loi).")
    time.sleep(2)

finally:
    cap.release()
    spi.close()
    DC_PIN.close()
    RST_PIN.close()