import os
import signal
import sys
import time
from threading import Thread

import cv2
import numpy as np
from gpiozero import OutputDevice

import supabase_client as sb
import tft_ui
import registration

# Khi systemd gui SIGTERM (systemctl stop / reboot): thoat sach de finally chay
# (set device offline + flush queue) thay vi bi kill cung.
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))

# Relay kich muc CAO: Mac dinh tat (0V)
RELAY_PIN = OutputDevice(23, active_high=True, initial_value=False)

# 2. Khoi tao AI Model
cv2.setNumThreads(4)
try:
    face_db = np.load("face_db.npy", allow_pickle=True).item()
    print(">> Da nap danh sach khuon mat:", list(face_db.keys()))
except Exception:
    face_db = {}

detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.65)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')
COSINE_THRESHOLD = 0.40
DENIED_SIM_MIN = 0.15
MIN_FACE_SIZE = 60
GRANT_COOLDOWN = 5.0
ALERT_COOLDOWN = 3.0

# 3. Quan ly trang thai
system_status = "STANDBY"
status_hold_time = 0
is_verifying = False
active_face_box = None
last_access_event_time = 0.0
last_grant_time = 0.0

# Ham mo cua co ban dung nhu code cu cua ban
def open_door_relay():
    sb.set_door_status("unlocked")
    RELAY_PIN.on()
    time.sleep(3.0)
    RELAY_PIN.off()
    sb.set_door_status("locked")

def get_templates(name):
    feats = face_db[name]
    if isinstance(feats, np.ndarray):
        return [feats]
    return list(feats)

def sync_face_db():
    global face_db
    profiles = sb.load_face_profiles()
    if profiles is None:
        return
    stale = [k for k in face_db if k not in profiles]
    if stale:
        for k in stale:
            del face_db[k]
        np.save("face_db.npy", face_db)
        print(">> [Sync] Da xoa template khong con tren Supabase:", stale)


def handle_register_command(cap):
    global face_db
    cmd = sb.fetch_pending_register_command()
    if cmd is None:
        return False
    cmd_id = cmd["id"]
    face_name = (cmd.get("payload") or {}).get("face_name")
    if not face_name:
        sb.set_command_status(cmd_id, "failed", message="Thieu face_name trong payload")
        return True

    sb.set_command_status(cmd_id, "running")
    print(f">> [Lenh] Nhan lenh dang ky khuon mat: {face_name}")
    ok, msg = registration.run_registration(face_name, cap=cap)
    sb.set_command_status(cmd_id, "done" if ok else "failed", message=msg)
    print(f">> [Lenh] Ket qua dang ky: {'OK' if ok else 'THAT BAI'} - {msg}")

    face_db = np.load("face_db.npy", allow_pickle=True).item() if os.path.exists("face_db.npy") else {}
    sb.load_face_profiles()
    sync_face_db()
    return True

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
        bx, by, bw, bh = active_face_box

        top_name = None
        top_score = -1.0
        matched_name = None

        if bw >= MIN_FACE_SIZE and bh >= MIN_FACE_SIZE:
            aligned = recognizer.alignCrop(frame_input, face)
            feature = recognizer.feature(aligned)

            for name in face_db:
                for db_feature in get_templates(name):
                    score = recognizer.match(feature, db_feature, cv2.FaceRecognizerSF_FR_COSINE)
                    if score > top_score:
                        top_score = score
                        top_name = name
        else:
            print(f">> [SKIP] Mat qua nho ({bw}x{bh}px < {MIN_FACE_SIZE}) - xem la khuon mat la")

        if top_name is not None and top_score >= COSINE_THRESHOLD:
            matched_name = top_name

        if matched_name is not None:
            system_status = f"WELCOME: {matched_name.upper()}"
            status_hold_time = now + 3.0
            last_grant_time = now
            last_access_event_time = now
            print(f">> [ACCESS GRANTED] XAC THUC THANH CONG CHO: {matched_name} (Score: {top_score:.2f})")
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
            print(f">> [ACCESS DENIED] {top_name or 'NO_MATCH'} (Score: {top_score:.2f})")

            if len(face_db) == 0 or top_score < DENIED_SIM_MIN:
                result = "unknown"
                fname = None
                alert = {
                    "alert_type": "unknown_face",
                    "title": "Unknown Face Detected",
                    "severity": "high",
                    "status": "new",
                    "message": f"Phat hien khuon mat la (similarity {top_score:.2f}).",
                }
            else:
                result = "denied"
                fname = top_name
                alert = {
                    "alert_type": "access_denied",
                    "title": "Access Denied",
                    "severity": "high",
                    "status": "new",
                    "message": f"Truy cap bi tu choi - similarity {top_score:.2f} duoi nguong {COSINE_THRESHOLD}.",
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
                "message": "Chuyen dong duoc phat hien nhung khong thay khuon mat.",
            }
            sb.record_access(
                result="no_face", face_name=None, threshold=COSINE_THRESHOLD, alert=alert,
            )
            last_access_event_time = now

    is_verifying = False

# 4. Luong chinh
def main():
    global system_status, is_verifying, active_face_box
    tft_ui.init_tft()

    sb.start_worker()
    sb.ensure_device()
    sb.load_face_profiles()
    sync_face_db()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    prev_gray = None
    last_trigger_time = 0
    last_heartbeat = 0
    last_profile_sync = 0
    last_cmd_check = 0
    prev_time = time.time()

    print(">> HE THONG ACCESS CONTROL DA HOAT DONG HOAN TOAN TREN TFT!")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue

            current_time = time.time()
            frame = cv2.resize(frame, (320, 240))

            # Phat hien chuyen dong
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is None:
                prev_gray = gray
                continue

            frame_delta = cv2.absdiff(prev_gray, gray)
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            motion_score = np.sum(thresh)
            prev_gray = gray

            # Reset trang thai
            if current_time >= status_hold_time and not is_verifying:
                system_status = "STANDBY"
                active_face_box = None

            # Kich hoat AI nhan dien
            grant_ready = (current_time - last_grant_time) > GRANT_COOLDOWN or last_grant_time == 0
            if (motion_score > 35000 and (current_time - last_trigger_time > 1.5) and not is_verifying
                    and current_time >= status_hold_time and grant_ready):
                is_verifying = True
                last_trigger_time = current_time
                system_status = "SCANNING..."
                Thread(target=verify_face_worker, args=(frame.copy(),), daemon=True).start()

            # Tinh toan FPS
            fps = 1.0 / (current_time - prev_time) if (current_time - prev_time) > 0 else 0
            prev_time = current_time

            # Heartbeat trang thai thiet bi
            if current_time - last_heartbeat >= 15:
                sb.heartbeat_tick()
                last_heartbeat = current_time

            # Dong bo xoa face_profiles tu web app (neu co)
            if current_time - last_profile_sync >= 60:
                sync_face_db()
                last_profile_sync = current_time

            # Nhan lenh dang ky khuon mat tu web app (device_commands)
            if current_time - last_cmd_check >= 5:
                if handle_register_command(cap):
                    last_trigger_time = current_time
                last_cmd_check = current_time

            # Chon mau giao dien
            if "WELCOME" in system_status:
                color = (0, 255, 0)      # Xanh la
            elif "DENIED" in system_status or "NO FACE" in system_status:
                color = (0, 0, 255)      # Do
            elif "SCANNING" in system_status:
                color = (0, 255, 255)    # Vang
            else:
                color = (255, 255, 255)  # Trang

            # Ve khung nhan dien dong quanh mat
            if active_face_box is not None:
                bx, by, bw, bh = active_face_box
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 2)

            # Thanh trang thai
            cv2.rectangle(frame, (0, 0), (320, 28), (0, 0, 0), -1)
            cv2.putText(frame, system_status, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            cv2.putText(frame, f"{fps:.1f} FPS", (250, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

            # Day frame len TFT
            tft_ui.render_tft(frame)

    except KeyboardInterrupt:
        print("\n>> Dung he thong.")
    finally:
        cap.release()
        tft_ui.close()
        RELAY_PIN.close()
        sb.set_device_offline()
        sb.stop_worker(timeout=6)

if __name__ == "__main__":
    main()