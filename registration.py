"""Shared face-registration flow (Pi-only, camera + TFT + models).

Used by register_face_multi.py (interactive CLI) and main.py (remote trigger
via Supabase device_commands). Captures 3 poses x 5 sharp samples, writes
face_db.npy (3 L2-normalized templates) and marks the face_profiles row
'registered' on Supabase.

run_registration(name, cap=None) -> (ok: bool, message: str)
"""

import os
import time
import unicodedata

import cv2
import numpy as np

import supabase_client as sb
import tft_ui

POSE_COUNT = 3
SAMPLES_PER_POSE = 5
MIN_FACE_SIZE = 60
BLUR_MIN_VAR = 25.0
POSE_TIMEOUT = 60.0
POSE_NAMES = ["NHIN THANG", "NGHIENG TRAI", "NGHIENG PHAI"]

DB_FILE = "face_db.npy"

cv2.setNumThreads(4)
detector = cv2.FaceDetectorYN.create('face_detection_yunet_2023mar.onnx', '', (320, 240), 0.65)
recognizer = cv2.FaceRecognizerSF.create('face_recognition_sface_2021dec.onnx', '')


def fold_name(name):
    name = name.replace("\u0111", "d").replace("\u0110", "D")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", name)
        if unicodedata.category(ch) != "Mn"
    )


def run_registration(canonical_name, cap=None):
    blank = np.zeros((240, 320, 3), dtype=np.uint8)
    own_cap = cap is None
    if own_cap:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    try:
        face_db = np.load(DB_FILE, allow_pickle=True).item() if os.path.exists(DB_FILE) else {}

        features_by_pose = []
        for pose_idx in range(POSE_COUNT):
            pose_samples = []
            pose_name = POSE_NAMES[pose_idx]
            pose_deadline = time.time() + POSE_TIMEOUT

            if pose_idx > 0:
                tft_ui.show_message(blank, [f"POSE {pose_idx} XONG!", f"CHUYEN SANG POSE {pose_idx + 1}"], (0, 255, 255))
                time.sleep(1.2)

            while len(pose_samples) < SAMPLES_PER_POSE:
                if time.time() > pose_deadline:
                    return False, f"Het thoi gian pose {pose_idx + 1} - khong bat du du mau (anh sang/vi tri camera)."

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

                disp = tft_ui.render_capture(
                    disp, fold_name(canonical_name), pose_idx + 1, POSE_COUNT,
                    pose_name, len(pose_samples), SAMPLES_PER_POSE,
                    pose_idx * SAMPLES_PER_POSE + len(pose_samples),
                    POSE_COUNT * SAMPLES_PER_POSE, msg, color,
                )
                tft_ui.render_tft(disp)

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

        cv2.rectangle(disp, (0, 0), (320, 240), (0, 0, 0), -1)
        cv2.putText(disp, "DANG KY HOAN TAT!", (25, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
        cv2.putText(disp, f"USER: {fold_name(canonical_name).upper()}", (60, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        tft_ui.render_tft(disp)

        for key in [k for k in face_db if k.lower() == canonical_name.lower() and k != canonical_name]:
            del face_db[key]

        face_db[canonical_name] = templates
        np.save(DB_FILE, face_db)

        sample_total = POSE_COUNT * SAMPLES_PER_POSE
        sync_result = sb.mark_face_registered(canonical_name, sample_total)
        time.sleep(2)
        return True, f"Da dang ky [{canonical_name}] voi {sample_total} mau / {len(templates)} template (supabase: {sync_result})"
    except Exception as exc:
        cv2.rectangle(blank, (0, 0), (320, 240), (0, 0, 0), -1)
        cv2.putText(blank, "DANG KY THAT BAI", (55, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(blank, str(exc)[:40], (20, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tft_ui.render_tft(blank)
        return False, str(exc)
    finally:
        if own_cap:
            cap.release()