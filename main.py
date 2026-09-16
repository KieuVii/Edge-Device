import os
import signal
import socket
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
VERIFY_TIMEOUT = 45.0
POLL_INTERVAL = 3.0
HEARTBEAT_INTERVAL = 15.0
PROFILE_SYNC_INTERVAL = 60.0
WATCHDOG_INTERVAL = 10.0

blank = np.zeros((240, 320, 3), dtype=np.uint8)

# Flag: da co lenh dang chay trong worker thread (chan lenh chong nhau)
_command_busy = False


def _sd_notify(msg):
    """Gui thong bao den systemd qua NOTIFY_SOCKET (sd_notify khong can thu vien).
    Chi hoat dong khi service chay duoi systemd voi Type=notify (NOTIFY_SOCKET duoc set)."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(addr)
        sock.sendall(msg.encode())
        sock.close()
    except Exception:
        pass


def notify_ready():
    """Bao systemd rang khoi dong xong (Type=notify) — khong gui se bi TimeoutStartSec kill."""
    _sd_notify("READY=1")


def watchdog_ping():
    """Bao cho systemd rang process con song (WatchdogSec=30 trong fina.service)."""
    _sd_notify("WATCHDOG=1")


def _watchdog_loop():
    """Thread rieng: ping watchdog vo dieu kien moi 10s, KHONG phu thuoc main loop.
    Nen cac lenh dai (checkin 45s, registration 180s) khong bi systemd kill giua chung."""
    while True:
        watchdog_ping()
        time.sleep(WATCHDOG_INTERVAL)


def shutdown_cleanup():
    try:
        tft_ui.close()
    except Exception:
        pass
    try:
        RELAY_PIN.close()
    except Exception:
        pass
    sb.set_device_offline()
    sb.stop_worker(timeout=6)


def _restart_service():
    """Tu khoi dong lai bang os.execv: re-exec CUNG PID, systemd khong thay process thoat
    -> khong phu thuoc Restart= cua unit file. Chi chay sau khi da don dep sach."""
    print(">> Khoi dong lai service theo lenh tu web (execv)...")
    shutdown_cleanup()
    try:
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])
    except Exception as exc:
        print(">> execv loi, fallback sys.exit(0):", exc)
    sys.exit(0)


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


def open_camera():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    return cap


def show_idle():
    tft_ui.show_message(blank, ["WELCOME TO", "SMART LOCK"], (255, 255, 0))


def open_door_relay():
    sb.set_door_status("unlocked")
    RELAY_PIN.on()
    time.sleep(3.0)
    RELAY_PIN.off()
    sb.set_door_status("locked")


def record_verification(result, similarity, face_name, access_type):
    profile = sb.get_face_profile(face_name) if face_name else None
    sb.record_access(
        result=result, similarity=similarity, face_name=face_name,
        face_profile=profile, threshold=COSINE_THRESHOLD,
        note=f"{access_type} - {result} (similarity {similarity:.2f})",
        access_type=access_type,
    )


def run_verification(access_type, cap):
    """Mo camera, detect + match khuon mat cho checkin/checkout. Tra ve (ok, message)."""
    label = access_type.upper()
    deadline = time.time() + VERIFY_TIMEOUT

    while time.time() < deadline:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.resize(frame, (320, 240))
        disp = frame.copy()
        cv2.rectangle(disp, (0, 0), (320, 28), (0, 0, 0), -1)
        cv2.putText(disp, f"{label} - NHIN VAO CAMERA", (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(disp, f"{max(0, deadline - time.time()):.0f}s",
                    (270, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        detector.setInputSize((320, 240))
        _, faces = detector.detect(frame)

        if faces is not None and len(faces) > 0:
            areas = faces[:, 2] * faces[:, 3]
            face = faces[int(np.argmax(areas))]
            bx, by, bw, bh = face[:4].astype(int)
            cv2.rectangle(disp, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)

            top_name = None
            top_score = -1.0
            if bw >= MIN_FACE_SIZE and bh >= MIN_FACE_SIZE:
                aligned = recognizer.alignCrop(frame, face)
                feature = recognizer.feature(aligned)
                for name in face_db:
                    for db_feature in get_templates(name):
                        score = recognizer.match(feature, db_feature, cv2.FaceRecognizerSF_FR_COSINE)
                        if score > top_score:
                            top_score = score
                            top_name = name
            else:
                print(f">> [SKIP] Mat qua nho ({bw}x{bh}px < {MIN_FACE_SIZE})")

            if top_name is not None and top_score >= COSINE_THRESHOLD:
                record_verification("granted", top_score, top_name, access_type)
                cv2.rectangle(disp, (0, 200), (320, 240), (0, 0, 0), -1)
                cv2.putText(disp, f"{label} OK!", (40, 232),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
                tft_ui.render_tft(disp)
                print(f">> [{label}] XAC THUC THANH CONG: {top_name} (Score: {top_score:.2f})")
                time.sleep(2)
                Thread(target=open_door_relay, daemon=True).start()
                return True, f"{access_type} OK - {top_name} (score {top_score:.2f})"

            result = "unknown" if not top_name or top_score < DENIED_SIM_MIN else "denied"
            record_verification(result, top_score, top_name, access_type)
            cv2.rectangle(disp, (0, 200), (320, 240), (0, 0, 0), -1)
            cv2.putText(disp, f"KHONG NHAN DIEN ({result.upper()})", (25, 232),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            tft_ui.render_tft(disp)
            print(f">> [{label}] {result.upper()}: {top_name or 'NO_MATCH'} (Score: {top_score:.2f})")
            time.sleep(2)
            return False, f"Khong nhan dien duoc khuon mat ({result})"

        tft_ui.render_tft(disp)

    return False, f"Het thoi gian ({VERIFY_TIMEOUT:.0f}s) - khong thay khuon mat hop le"


def handle_command(cmd):
    """Xu ly mot lenh. Tra ve True neu can khoi dong lai service (lenh restart_service)."""
    global face_db
    cmd_id = cmd["id"]
    ctype = cmd["command"]
    payload = cmd.get("payload") or {}
    print(f">> [Lenh] Nhan lenh: {ctype} {payload}")

    sb.set_command_status(cmd_id, "running")
    ok = False
    msg = ""
    restart_requested = False
    cap = None
    try:
        if ctype == "start_register_face":
            face_name = payload.get("face_name")
            if not face_name:
                msg = "Thieu face_name trong payload"
            else:
                cap = open_camera()
                if cap is None or not cap.isOpened():
                    sb.set_device_error()
                    msg = "Khong mo duoc camera - kiem tra /dev/video0"
                else:
                    ok, msg = registration.run_registration(face_name, cap=cap)
        elif ctype in ("start_checkin", "start_checkout"):
            access_type = ctype.replace("start_", "")
            cap = open_camera()
            if cap is None or not cap.isOpened():
                sb.set_device_error()
                msg = "Khong mo duoc camera - kiem tra /dev/video0"
            else:
                ok, msg = run_verification(access_type, cap)
        elif ctype == "restart_service":
            sb.cancel_other_restarts(cmd_id)
            ok = True
            restart_requested = True
            msg = "Service dang khoi dong lai..."
        elif ctype == "manual_unlock":
            open_door_relay()
            ok = True
            msg = "Da mo khoa (unlock 3s)"
        elif ctype == "lock_door":
            RELAY_PIN.off()
            sb.set_door_status("locked")
            ok = True
            msg = "Da khoa cua"
        elif ctype == "restart_camera":
            cap = open_camera()
            frames_ok = 0
            for _ in range(3):
                ret, _frame = cap.read()
                if ret:
                    frames_ok += 1
            cap.release()
            cap = None
            if frames_ok > 0:
                ok = True
                msg = f"Camera hoat dong binh thuong ({frames_ok}/3 frame)"
            else:
                sb.set_device_error()
                msg = "Camera khong doc duoc frame - kiem tra /dev/video0"
        elif ctype == "sync_face_db":
            sync_face_db()
            sb.load_face_profiles()
            ok = True
            msg = "Da dong bo face_db voi face_profiles"
        else:
            msg = f"Chua ho tro lenh: {ctype}"
    except Exception as exc:
        ok = False
        msg = str(exc)
        print(">> [Lenh] Loi khi xu ly lenh:", exc)
    finally:
        if cap is not None:
            cap.release()
            cap = None

    sb.set_command_status(cmd_id, "done" if ok else "failed", message=msg)
    print(f">> [Lenh] Ket qua: {'OK' if ok else 'THAT BAI'} - {msg}")

    if ctype == "start_register_face":
        face_db = np.load("face_db.npy", allow_pickle=True).item() if os.path.exists("face_db.npy") else {}
        sb.load_face_profiles()
        sync_face_db()

    show_idle()
    return restart_requested


def _command_worker(cmd):
    """Chay lenh trong thread rieng de main loop khong bi block:
    - heartbeat + watchdog tiep tuc trong luc lenh chay (device khong bi coi offline)
    - restart_service van xu ly duoc khi lenh khac dang ket (thoat hiem tu web)"""
    global _command_busy
    restart_requested = False
    try:
        restart_requested = handle_command(cmd)
    except Exception as exc:
        print(">> [Lenh] Loi khong mong muon:", exc)
        try:
            sb.set_command_status(cmd["id"], "failed", message=str(exc)[:500])
        except Exception:
            pass
    finally:
        _command_busy = False
    if restart_requested:
        _restart_service()


# 4. Luong chinh
def main():
    global face_db
    global _command_busy
    tft_ui.init_tft()
    show_idle()

    sb.start_worker()
    sb.ensure_device()
    sb.load_face_profiles()
    sync_face_db()
    sb.recover_stale_commands()
    notify_ready()

    last_heartbeat = 0
    last_profile_sync = 0
    last_cmd_check = 0

    Thread(target=_watchdog_loop, name="watchdog", daemon=True).start()

    print(">> HE THONG SMART LOCK DA SAN SANG - doi lenh tu web (Register/Checkin/Checkout/Restart)")

    try:
        while True:
            current_time = time.time()

            if current_time - last_cmd_check >= POLL_INTERVAL:
                cmd = sb.fetch_pending_command()
                if cmd is not None:
                    if not _command_busy:
                        _command_busy = True
                        Thread(target=_command_worker, args=(cmd,), name="command-worker", daemon=True).start()
                    elif cmd.get("command") == "restart_service":
                        # Thoat hiem: lenh restart duoc xu ly ngay ca khi lenh khac dang ket
                        Thread(target=_command_worker, args=(cmd,), name="command-restart", daemon=True).start()
                    else:
                        print(">> [Lenh] Dang ban voi lenh khac, de pending:", cmd.get("command"))
                last_cmd_check = time.time()

            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                sb.heartbeat_tick()
                last_heartbeat = current_time

            if current_time - last_profile_sync >= PROFILE_SYNC_INTERVAL:
                sync_face_db()
                last_profile_sync = current_time

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n>> Dung he thong.")
    finally:
        shutdown_cleanup()


if __name__ == "__main__":
    main()