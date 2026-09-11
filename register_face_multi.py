"""Interactive face-registration CLI (Pi-only).

Usage:
    python register_face_multi.py [face_name]

- face_name can be passed as argument (used by scripts), otherwise prompted.
- The name MUST match an existing face_profiles.face_name on Supabase exactly
  (create the profile in the web app first, or trigger registration remotely
  from the web app which runs this flow inside main.py).

The capture logic itself lives in registration.py (shared with main.py).
"""

import sys
import time
import unicodedata

import numpy as np

import supabase_client as sb

try:
    import tft_ui
    import registration
except Exception as exc:
    print("\n>> KHONG MO DUOC GPIO/SPI:", exc)
    print(">> Co the main.py hoac fina.service dang chay va giu GPIO/SPI.")
    print(">> Dung truoc roi chay lai: sudo systemctl stop fina  (hoac Ctrl+C terminal main.py)")
    exit(1)

if not sb.configured():
    print("\n>> Supabase chua duoc cau hinh (.env). Khong the dong bo face_profiles.")
    print(">> Hay dien SUPABASE_URL / SUPABASE_SERVICE_KEY / DEVICE_CODE trong .env roi chay lai.")
    exit(1)


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


def main():
    blank = np.zeros((240, 320, 3), dtype=np.uint8)

    tft_ui.init_tft()
    print(">> TFT da khoi tao xong")
    for _ in range(3):
        tft_ui.show_message(blank, ["DANG KY KHUON MAT", "NHAP TEN TREN TERMINAL"], (255, 255, 0))
        time.sleep(0.15)
    print(">> Da gui man hinh huong dan - neu TFT van trang, xem loi in o tren terminal")

    new_name = sys.argv[1] if len(sys.argv) > 1 else read_name(
        "Nhap ten nguoi can dang ky (khop face_name tren Supabase): ")
    if not new_name:
        print("Ten khong hop le!")
        exit(1)

    profile = sb.find_face_profile(new_name)
    if profile is None:
        tft_ui.show_message(blank, ["KHONG TIM THAY HO SO", f"'{fold_name(new_name)}'", "TREN SUPABASE"], (0, 0, 255))
        print(f"\n>> KHONG tim thay face_profiles '{new_name}' tren Supabase.")
        print(">> Hay tao user + face_profiles trong ung dung web truoc (face_name phai khop chinh xac), roi chay lai.")
        exit(1)

    canonical_name = profile["face_name"]
    sb.ensure_device()

    print(f">> Man hinh da bat! Hay nhin vao camera cho [{canonical_name}]...")
    print(">> Moi pose thu 5 mau: nhin thang / nghieng trai / nghieng phai.")

    ok, msg = registration.run_registration(canonical_name)
    print(f">> {'OK' if ok else 'THAT BAI'}: {msg}")
    if not ok:
        exit(1)


if __name__ == "__main__":
    main()