import cv2
import numpy as np
import os
import time

# Chay tren Pi: camera + model ONNX, khong dung GPIO -> an toan.
# Muc dich: kiem tra face_db.npy co dung nguoi khong, camera co bi dong bang khong.

print("cv2 version:", cv2.__version__)

if not os.path.exists("face_db.npy"):
    print("Khong co face_db.npy - chua dang ky ai.")
    exit(1)

face_db = np.load("face_db.npy", allow_pickle=True).item()
names = list(face_db.keys())
print("Profiles trong face_db:", names)


def norm_vec(f):
    f = np.asarray(f, dtype=np.float32).reshape(1, -1)
    n = np.linalg.norm(f)
    return f / n if n > 0 else f


def cos(a, b):
    return float(np.dot(norm_vec(a), norm_vec(b).T)[0, 0])


print("\n-- Chi tiet tung profile --")
for name in names:
    feats = face_db[name]
    arr = feats if isinstance(feats, list) else [feats]
    arr = [np.asarray(f) for f in arr]
    norms = [round(float(np.linalg.norm(f)), 3) for f in arr]
    print(f"  {name}: {len(arr)} template, shapes={[f.shape for f in arr]}, norms={norms}")
    for i in range(len(arr)):
        for j in range(i + 1, len(arr)):
            print(f"    intra cos[{i},{j}] = {cos(arr[i], arr[j]):.3f}")

print("\n-- Cosine giua cac profile (max) --")
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a = face_db[names[i]] if isinstance(face_db[names[i]], list) else [face_db[names[i]]]
        b = face_db[names[j]] if isinstance(face_db[names[j]], list) else [face_db[names[j]]]
        best = max(cos(x, y) for x in a for y in b)
        print(f"  {names[i]} vs {names[j]}: max cos = {best:.3f}"
              + ("  <-- CUNG MOT NGUOI?" if best >= 0.50 else ""))

print("\n-- Kiem tra camera: 10 frame cach nhau 0.3s --")
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.65)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')

prev = None
embeddings = []
for i in range(10):
    ret, frame = cap.read()
    if not ret:
        print(f"  frame {i}: khong doc duoc!")
        continue
    frame = cv2.resize(frame, (320, 240))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev is not None:
        diff = float(np.abs(gray.astype(np.int16) - prev.astype(np.int16)).mean())
        print(f"  frame {i}: thay doi trung binh = {diff:.1f}  (0.0 = camera dong bang, frame lap lai)")
    prev = gray
    detector.setInputSize((320, 240))
    _, faces = detector.detect(frame)
    if faces is not None and len(faces) > 0:
        areas = faces[:, 2] * faces[:, 3]
        face = faces[int(np.argmax(areas))]
        aligned = recognizer.alignCrop(frame, face)
        embeddings.append(recognizer.feature(aligned))
        print(f"  frame {i}: co mat, box={face[:4].astype(int).tolist()}")
    else:
        print(f"  frame {i}: KHONG co mat - hay nhin thang vao camera")
    time.sleep(0.3)
cap.release()

if embeddings:
    avg = np.mean(embeddings, axis=0)
    print("\n-- So khop khuon mat HIEN TAI (nguoi dang dung truoc camera) --")
    print("-- Neu cos >= 0.40 la template cua CHINH nguoi nay --")
    for name in names:
        feats = face_db[name] if isinstance(face_db[name], list) else [face_db[name]]
        best = max(cos(avg, f) for f in feats)
        verdict = "TRUNG KHOP (>= 0.40)" if best >= 0.40 else "khong khop"
        print(f"  {name}: cos = {best:.3f} -> {verdict}")
else:
    print("\nKhong thu duoc embedding nao.")