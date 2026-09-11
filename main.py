import cv2
import numpy as np
import time
import spidev
from threading import Thread
from gpiozero import OutputDevice

import supabase_client as sb

# 1. Phần cứng
DC_PIN = OutputDevice(24)       # Pin 18 (GPIO 24)
RST_PIN = OutputDevice(25)      # Pin 22 (GPIO 25)
RST_PIN.on()                    # Giữ chân RESET luôn ở 3.3V để màn hình chạy bình thường

# Relay kích mức CAO: Mặc định tắt (0V)
RELAY_PIN = OutputDevice(23, active_high=True, initial_value=False)

spi = spidev.SpiDev()
spi.open(0, 0)
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
    send_cmd(0x01); time.sleep(0.12)
    send_cmd(0x11); time.sleep(0.12)
    send_cmd(0x3A); send_data(0x55)
    send_cmd(0x36); send_data(0x70)
    send_cmd(0x20) # Inversion OFF
    
    send_cmd(0xB2); send_data([0x0C, 0x0C, 0x00, 0x33, 0x33])
    send_cmd(0xB7); send_data(0x35)
    send_cmd(0xBB); send_data(0x19)
    send_cmd(0xC0); send_data(0x2C)
    send_cmd(0xC2); send_data(0x01)
    send_cmd(0xC3); send_data(0x12)
    send_cmd(0xC4); send_data(0x20)
    send_cmd(0xC6); send_data(0x0F)
    
    send_cmd(0x29); time.sleep(0.05)
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])

# 2. Khởi tạo AI Model
cv2.setNumThreads(4)
try:
    face_db = np.load("face_db.npy", allow_pickle=True).item()
    print(">> Đã nạp danh sách khuôn mặt:", list(face_db.keys()))
except Exception:
    face_db = {}

detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.5)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')
COSINE_THRESHOLD = 0.32
DENIED_SIM_MIN = 0.15
GRANT_COOLDOWN = 5.0
ALERT_COOLDOWN = 3.0

# 3. Quản lý trạng thái
system_status = "STANDBY"
status_hold_time = 0
is_verifying = False
active_face_box = None
last_access_event_time = 0.0
last_grant_time = 0.0

# Hàm mở cửa cơ bản đúng như code cũ của bạn
def open_door_relay():
    sb.set_door_status("unlocked")
    RELAY_PIN.on()
    time.sleep(3.0)
    RELAY_PIN.off()
    sb.set_door_status("locked")

def verify_face_worker(frame_input):
    global system_status, status_hold_time, is_verifying, active_face_box
    global last_access_event_time, last_grant_time

    now = time.time()
    cooldown_ok = (now - last_access_event_time) >= ALERT_COOLDOWN or last_access_event_time == 0

    detector.setInputSize((320, 240))
    _, faces = detector.detect(frame_input)

    if faces is not None and len(faces) > 0:
        face = faces[0]
        active_face_box = face[:4].astype(int)

        aligned = recognizer.alignCrop(frame_input, face)
        feature = recognizer.feature(aligned)

        top_name = None
        top_score = -1.0
        matched_name = None

        for name, db_feature in face_db.items():
            score = recognizer.match(feature, db_feature, cv2.FaceRecognizerSF_FR_COSINE)
            if score > top_score:
                top_score = score
                top_name = name
        if top_name is not None and top_score >= COSINE_THRESHOLD:
            matched_name = top_name

        if matched_name is not None:
            system_status = f"WELCOME: {matched_name.upper()}"
            status_hold_time = now + 3.0
            last_grant_time = now
            last_access_event_time = now
            print(f">> [ACCESS GRANTED] XÁC THỰC THÀNH CÔNG CHO: {matched_name} (Score: {top_score:.2f})")
            Thread(target=open_door_relay, daemon=True).start()

            profile = sb.get_face_profile(matched_name)
            sb.record_access(
                result="granted", similarity=top_score, face_name=matched_name,
                face_profile=profile, threshold=COSINE_THRESHOLD,
                note="Access granted - door unlocked 3 seconds",
            )
        else:
            system_status = f"DENIED ({top_score:.2f})"
            status_hold_time = now + 2.0
            print(f">> [ACCESS DENIED] Không trùng khớp (Score: {top_score:.2f})")

            if len(face_db) == 0 or top_score < DENIED_SIM_MIN:
                result = "unknown"
                fname = None
                alert = {
                    "alert_type": "unknown_face",
                    "title": "Unknown Face Detected",
                    "severity": "high",
                    "status": "new",
                    "message": f"Phát hiện khuôn mặt lạ (similarity {top_score:.2f}).",
                }
            else:
                result = "denied"
                fname = top_name
                alert = {
                    "alert_type": "access_denied",
                    "title": "Access Denied",
                    "severity": "high",
                    "status": "new",
                    "message": f"Truy cập bị từ chối - similarity {top_score:.2f} dưới ngưỡng {COSINE_THRESHOLD}.",
                }

            if cooldown_ok:
                profile = sb.get_face_profile(fname) if fname else None
                cap = sb.save_capture(frame_input, label=result) if sb.enabled() else None
                sb.record_access(
                    result=result, similarity=top_score, face_name=fname,
                    face_profile=profile, threshold=COSINE_THRESHOLD,
                    note=f"Access {result} - similarity below threshold",
                    alert=alert, local_image=cap,
                )
                last_access_event_time = now
    else:
        active_face_box = None
        system_status = "NO FACE"
        status_hold_time = now + 1.0

        if cooldown_ok:
            alert = {
                "alert_type": "no_face",
                "title": "No Face Detected",
                "severity": "low",
                "status": "new",
                "message": "Chuyển động được phát hiện nhưng không thấy khuôn mặt.",
            }
            sb.record_access(
                result="no_face", face_name=None, threshold=COSINE_THRESHOLD, alert=alert,
            )
            last_access_event_time = now

    is_verifying = False

# 4. Luồng chính
def main():
    global system_status, is_verifying, active_face_box
    init_tft()

    sb.start_worker()
    sb.ensure_device()
    sb.load_face_profiles()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    prev_gray = None
    last_trigger_time = 0
    last_heartbeat = 0
    prev_time = time.time()

    print(">> HỆ THỐNG ACCESS CONTROL ĐÃ HOẠT ĐỘNG HOÀN TOÀN TRÊN TFT!")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue

            current_time = time.time()
            frame = cv2.resize(frame, (320, 240))

            # Phát hiện chuyển động
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is None:
                prev_gray = gray
                continue

            frame_delta = cv2.absdiff(prev_gray, gray)
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            motion_score = np.sum(thresh)
            prev_gray = gray

            # Reset trạng thái
            if current_time >= status_hold_time and not is_verifying:
                system_status = "STANDBY"
                active_face_box = None

            # Kích hoạt AI nhận diện
            grant_ready = (current_time - last_grant_time) > GRANT_COOLDOWN or last_grant_time == 0
            if (motion_score > 35000 and (current_time - last_trigger_time > 1.5) and not is_verifying
                    and current_time >= status_hold_time and grant_ready):
                is_verifying = True
                last_trigger_time = current_time
                system_status = "SCANNING..."
                Thread(target=verify_face_worker, args=(frame.copy(),), daemon=True).start()

            # Tính toán FPS
            fps = 1.0 / (current_time - prev_time) if (current_time - prev_time) > 0 else 0
            prev_time = current_time

            # Heartbeat trạng thái thiết bị
            if current_time - last_heartbeat >= 15:
                sb.heartbeat_tick()
                last_heartbeat = current_time

            # Chọn màu giao diện
            if "WELCOME" in system_status:
                color = (0, 255, 0)      # Xanh lá
            elif "DENIED" in system_status or "NO FACE" in system_status:
                color = (0, 0, 255)      # Đỏ
            elif "SCANNING" in system_status:
                color = (0, 255, 255)    # Vàng
            else:
                color = (255, 255, 255)  # Trắng

            # Vẽ khung nhận diện động quanh mặt
            if active_face_box is not None:
                bx, by, bw, bh = active_face_box
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 2)

            # Thanh trạng thái
            cv2.rectangle(frame, (0, 0), (320, 28), (0, 0, 0), -1)
            cv2.putText(frame, system_status, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            cv2.putText(frame, f"{fps:.1f} FPS", (250, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

            # Đẩy frame lên TFT
            frame_u16 = frame.astype(np.uint16)
            b = frame_u16[:, :, 0] >> 3
            g = frame_u16[:, :, 1] >> 2
            r = frame_u16[:, :, 2] >> 3
            rgb565 = (r << 11) | (g << 5) | b

            send_cmd(0x2C)
            send_data(rgb565.byteswap().tobytes())

    except KeyboardInterrupt:
        print("\n>> Dừng hệ thống.")
    finally:
        cap.release()
        spi.close()
        DC_PIN.close()
        RST_PIN.close()
        RELAY_PIN.close()
        sb.set_device_offline()
        sb.stop_worker(timeout=6)

if __name__ == "__main__":
    main()