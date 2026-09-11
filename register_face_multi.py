import cv2
import numpy as np
import time
import spidev
import os
from gpiozero import OutputDevice

import supabase_client as sb

if not sb.configured():
    print("\n>> Supabase chưa được cấu hình (.env). Không thể đồng bộ face_profiles.")
    print(">> Hãy điền SUPABASE_URL / SUPABASE_SERVICE_KEY / DEVICE_CODE trong .env rồi chạy lại.")
    exit(1)

# ==========================================
# 1. CẤU HÌNH PHẦN CỨNG TFT
# ==========================================
DC_PIN = OutputDevice(24)   # Pin 18 (GPIO 24)
RST_PIN = OutputDevice(25)  # Pin 22 (GPIO 25)
RST_PIN.on()                # Kéo chân RESET lên mức HIGH (3.3V) để kích hoạt màn hình

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
    # Kích hoạt phần cứng màn hình
    RST_PIN.on()
    time.sleep(0.01)
    
    send_cmd(0x01); time.sleep(0.12) # SW Reset
    send_cmd(0x11); time.sleep(0.12) # Sleep Out
    
    send_cmd(0x3A); send_data(0x55)  # Chuẩn màu 16-bit RGB565
    send_cmd(0x36); send_data(0x70)  # Landscape 320x240
    send_cmd(0x20)                   # Inversion OFF (Màu thực)
    
    # Nạp chuỗi thanh ghi đồng bộ quét xung tấm nền
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
    # Khóa vùng ghi lại trước mỗi khung hình
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
# 2. KHỞI TẠO MÔ HÌNH AI & DATABASE
# ==========================================
cv2.setNumThreads(4)
detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.6)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')

db_file = "face_db.npy"
face_db = np.load(db_file, allow_pickle=True).item() if os.path.exists(db_file) else {}

# Nhập tên trước trên terminal
new_name = input("Nhập tên người cần đăng ký (khớp face_name trên Supabase): ").strip()
if not new_name:
    print("Tên không hợp lệ!")
    exit(1)

profile = sb.find_face_profile(new_name)
if profile is None:
    print(f"\n>> KHÔNG tìm thấy face_profiles '{new_name}' trên Supabase.")
    print(">> Hãy tạo user + face_profiles trong ứng dụng web trước (face_name phải khớp chính xác), rồi chạy lại.")
    exit(1)

canonical_name = profile["face_name"]
sb.ensure_device()

# Bật màn hình và Camera
init_tft()
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

features_list = []
print(f">> Màn hình đã bật! Hãy nhìn vào camera và nghiêng nhẹ đầu để lấy mẫu cho [{canonical_name}]...")

try:
    while len(features_list) < 10:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.resize(frame, (320, 240))
        disp = frame.copy()

        detector.setInputSize((320, 240))
        _, faces = detector.detect(frame)

        if faces is not None and len(faces) > 0:
            face = faces[0]
            box = face[:4].astype(int)
            cv2.rectangle(disp, (box[0], box[1]), (box[0]+box[2], box[1]+box[3]), (0, 255, 0), 2)
            
            aligned = recognizer.alignCrop(frame, face)
            feat = recognizer.feature(aligned)
            features_list.append(feat)

            # Thanh trạng thái tiến độ
            cv2.rectangle(disp, (0, 0), (320, 30), (0, 0, 0), -1)
            cv2.putText(disp, f"TIEN DO: {len(features_list)*10}%", (10, 22), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            time.sleep(0.12)
        else:
            cv2.rectangle(disp, (0, 0), (320, 30), (0, 0, 0), -1)
            cv2.putText(disp, "CANH CHINH KHUON MAT", (10, 22), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        render_tft(disp)

    # Hiển thị thông báo hoàn tất lên màn hình
    cv2.rectangle(disp, (0, 0), (320, 240), (0, 0, 0), -1)
    cv2.putText(disp, "DANG KY HOAN TAT!", (25, 110), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
    cv2.putText(disp, f"USER: {canonical_name.upper()}", (60, 150), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    render_tft(disp)

    # Tính vector trung bình và chuẩn hóa L2
    avg_feature = np.mean(features_list, axis=0)
    norm = np.linalg.norm(avg_feature)
    if norm > 0:
        avg_feature = avg_feature / norm

    for key in [k for k in face_db if k.lower() == canonical_name.lower() and k != canonical_name]:
        del face_db[key]

    face_db[canonical_name] = avg_feature
    np.save(db_file, face_db)

    sync_result = sb.mark_face_registered(canonical_name, len(features_list))
    print(f"\n>> ĐÃ ĐĂNG KÝ XONG CHO [{canonical_name}] VỚI {len(features_list)} MẪU ĐẶC TRƯNG!")
    print(f">> Danh sách hiện có trong DB: {list(face_db.keys())}")
    if sync_result == "ok":
        print(f">> [Supabase] face_profiles '{canonical_name}' đã cập nhật: registered.")
    elif sync_result == "queued":
        print(">> [Supabase] Mạng không ổn định - cập nhật face_profiles sẽ gửi lại khi có mạng.")
    else:
        print(">> [Supabase] Không thể cập nhật face_profiles (chưa cấu hình hoặc lỗi).")
    time.sleep(2)

finally:
    cap.release()
    spi.close()
    DC_PIN.close()
    RST_PIN.close()