"""Calibrate the SFace cosine threshold on the Pi using real camera data.

Usage (run on Raspberry Pi, camera attached, models + face_db.npy in CWD):

    python calibrate_threshold.py collect known   30
    python calibrate_threshold.py collect unknown 30
    python calibrate_threshold.py score

- `collect <group> [count]` records frames + SFace embeddings of one person
  (group = known or unknown) into calib_<group>/. Stand still, turn slightly,
  the script auto-saves when a sharp, large enough face is detected.
- `score` compares all collected embeddings against face_db.npy templates and
  prints the score distribution of known vs unknown + a suggested threshold.

This script touches the camera + ONNX models only - no GPIO/TFT/relay.
"""

import os
import sys
import time

import cv2
import numpy as np

MIN_FACE_SIZE = 60
BLUR_MIN_VAR = 25.0
MAX_FRAMES_WITHOUT_FACE = 120

YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"
DB_FILE = "face_db.npy"


def load_models():
    if not (os.path.exists(YUNET) and os.path.exists(SFACE)):
        print(f">> Thieu model: can {YUNET} va {SFACE} trong thu muc hien hanh.")
        sys.exit(1)
    detector = cv2.FaceDetectorYN.create(YUNET, "", (320, 240), 0.65)
    recognizer = cv2.FaceRecognizerSF.create(SFACE, "")
    return detector, recognizer


def load_db():
    if not os.path.exists(DB_FILE):
        print(">> Chua co face_db.npy - hay chay register_face_multi.py truoc.")
        sys.exit(1)
    return np.load(DB_FILE, allow_pickle=True).item()


def get_templates(feats):
    if isinstance(feats, np.ndarray):
        return [feats]
    return list(feats)


def detect_best_face(detector, frame):
    detector.setInputSize((frame.shape[1], frame.shape[0]))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None, None
    areas = faces[:, 2] * faces[:, 3]
    face = faces[int(np.argmax(areas))]
    return face, face[:4].astype(int)


def collect(group, count):
    if group not in ("known", "unknown"):
        print(">> group phai la 'known' hoac 'unknown'.")
        sys.exit(1)
    out_dir = f"calib_{group}"
    os.makedirs(out_dir, exist_ok=True)

    detector, recognizer = load_models()
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    if not cap.isOpened():
        print(">> Khong mo duoc camera (/dev/video0).")
        sys.exit(1)

    saved = 0
    blank_run = 0
    print(f">> Bat dau thu {count} mau cho nhom '{group}'. Dung truoc camera, hoi xoay dau.")
    while saved < count:
        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.resize(frame, (320, 240))

        face, box = detect_best_face(detector, frame)
        if face is None:
            blank_run += 1
            if blank_run >= MAX_FRAMES_WITHOUT_FACE:
                print(">> Khong thay mat trong 120 khung - kiem tra camera/anh sang.")
                break
            time.sleep(0.05)
            continue

        bw, bh = box[2], box[3]
        if bw < MIN_FACE_SIZE or bh < MIN_FACE_SIZE:
            time.sleep(0.05)
            continue
        face_gray = cv2.cvtColor(frame[box[1]:box[1] + bh, box[0]:box[0] + bw], cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(face_gray, cv2.CV_64F).var() < BLUR_MIN_VAR:
            time.sleep(0.05)
            continue

        aligned = recognizer.alignCrop(frame, face)
        feat = recognizer.feature(aligned)
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{saved:03d}"
        cv2.imwrite(os.path.join(out_dir, f"{stamp}.jpg"), frame)
        np.save(os.path.join(out_dir, f"{stamp}.npy"), feat)
        saved += 1
        blank_run = 0
        print(f">> [{group}] Da luu {saved}/{count} (box {bw}x{bh}px)")
        time.sleep(0.5)

    cap.release()
    print(f">> Xong nhom '{group}': {saved} mau trong {out_dir}/")


def score():
    _, recognizer = load_models()
    face_db = load_db()
    if not face_db:
        print(">> face_db trong.")
        sys.exit(1)

    groups = {}
    for group in ("known", "unknown"):
        files = sorted(
            f for f in os.listdir(f"calib_{group}")
            if f.endswith(".npy")
        ) if os.path.isdir(f"calib_{group}") else []
        groups[group] = [np.load(os.path.join(f"calib_{group}", f)) for f in files]
        print(f">> Nhom '{group}': {len(groups[group])} embedding")

    def best_scores(feats_list):
        out = []
        for feats in feats_list:
            best = -1.0
            for name in face_db:
                for tpl in get_templates(face_db[name]):
                    s = recognizer.match(feats, tpl, cv2.FaceRecognizerSF_FR_COSINE)
                    if s > best:
                        best = s
            out.append(best)
        return out

    def describe(values):
        if not values:
            return "(khong co du lieu)"
        arr = np.array(values)
        return (f"n={len(arr)} min={arr.min():.3f} max={arr.max():.3f} "
                f"mean={arr.mean():.3f} median={np.median(arr):.3f}")

    known_scores = best_scores(groups["known"])
    unknown_scores = best_scores(groups["unknown"])
    print("\n>> PHAN PHOI SCORE (cosine, so voi face_db):")
    print(f"   Quen : {describe(known_scores)}")
    print(f"   La   : {describe(unknown_scores)}")

    if known_scores and unknown_scores:
        print("\n   Sap xep (thap -> cao):")
        print(f"   Quen : {sorted(round(s, 3) for s in known_scores)}")
        print(f"   La   : {sorted(round(s, 3) for s in unknown_scores)}")

        max_unknown = max(unknown_scores)
        min_known = min(known_scores)
        if max_unknown < min_known:
            suggested = round((max_unknown + min_known) / 2, 3)
            print(f"\n>> NGUONG DE XUAT: {suggested} "
                  f"(cach biet max_la={max_unknown:.3f} / min_quen={min_known:.3f})")
        else:
            print("\n>> WARN: Vung score quen/la CHONG NHAU - can dang ky lai voi chat luong tot hon,"
                  " tang so mau, hoac xem xet doi model.")
        for t in (0.40, 0.45):
            fa = sum(1 for s in unknown_scores if s >= t) / len(unknown_scores)
            fr = sum(1 for s in known_scores if s < t) / len(known_scores)
            print(f"   Tai nguong {t:.2f}: nguoi la lot={fa * 100:.1f}% | nguoi quen bi chan={fr * 100:.1f}%")
    else:
        print(">> Can thu ca 2 nhom truoc: python calibrate_threshold.py collect <known|unknown> <so mau>")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "collect":
        group = sys.argv[2] if len(sys.argv) > 2 else "known"
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        collect(group, count)
    elif mode == "score":
        score()
    else:
        print(__doc__)
        sys.exit(1)