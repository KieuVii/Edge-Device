# AGENTS.md

SmartLock edge device: Raspberry Pi face-recognition door lock (TFT ILI9341 + camera + relay) synced to Supabase.

## Location
- Active source is `D:\Samsung-Project\Edge-Device`. `D:\2026\SamSung_NIC\FINA_PROJECT` is deprecated — never edit it.
- This folder IS a git repo (origin `github.com/KieuVii/Edge-Device.git`) — the Pi clones from it (`~/edge-device/Edge-Device`), so commit + push, then `git pull` on the Pi.

## What runs where
- `main.py` / `register_face_multi.py` / `calibrate_threshold.py` are Raspberry Pi-only: `main.py` and `register_face_multi.py` import `spidev`, `gpiozero` and open GPIO 24/25/23 + SPI0.0 at module level — importing them on the dev PC crashes. Do not run them locally. `calibrate_threshold.py` only touches camera + ONNX (no GPIO) but still needs the Pi's `/dev/video0`.
- `supabase_client.py` is cross-platform and is the only module testable on the dev PC.

## Runtime prerequisites (not in repo)
- ONNX models are loaded from the **current working directory**: `face_detection_yunet_2023mar.onnx`, `face_recognition_sface_2021dec.onnx`. They must exist beside the scripts on the Pi (systemd unit uses `WorkingDirectory=/home/pi/fina`).
- `face_db.npy` is created by `register_face_multi.py`; its keys must equal `face_profiles.face_name` exactly, because `main.py` looks up profiles by that same name via `sb.get_face_profile()`. Each value is a **list of 3 templates** (L2-normalized, one per pose); old single-vector files still load (treated as 1 template).
- Pi needs: SPI enabled, camera at `/dev/video0`, user in `spi`/`gpio` groups.

## Supabase config (`.env` next to supabase_client.py)
- Keys: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `DEVICE_CODE` (=`DOOR_01`), `DEVICE_NAME`, optional `DEVICE_IP`/`ROOM_UUID`, `DRY_RUN`.
- `.env` has a built-in fallback parser (works without python-dotenv). Missing config ⇒ runs WITHOUT sync (recognition/door still work, logs just not sent). `DRY_RUN=1` prints payloads, sends nothing.
- The key is currently a **publishable key = anon role**, so the RLS policies in `supabase_rls_policies.sql` must exist: devices (select/insert/update), access_logs (select/insert), alerts (select/insert), face_profiles (select/update). There is **no anon insert on face_profiles** — profiles are created from the web app.

## Supabase client quirks (high-signal)
- Offline queue = sqlite `pending_ops.db` + background worker thread. Network errors are retried; permanent errors (401/403/404/400/RLS 42501) are logged then dropped.
- **Do not revert inserts/updates to default `returning=representation`.** access_logs/alerts have no anon SELECT policy, so the default PostgREST behavior fails with `42501`. Code deliberately uses `returning="minimal"` and pre-generates the `access_logs.id` (uuid) to link alerts via `access_log_id`.
- Storage bucket `access-captures` must exist and be public; `python-multipart` is required for the supabase storage upload.
- CHECK constraints: `access_logs.result` ∈ granted/denied/no_face/unknown and `alerts.alert_type` must be a valid value — anything else returns `23514`.
- Main flow (main.py): grant when cosine score ≥ 0.40; faces smaller than `MIN_FACE_SIZE=60`px are treated as unknown; `result=unknown` when no profile or score < 0.15, `denied` otherwise. Matching takes the **max score across all templates** of a person. YuNet detection threshold is 0.65 (both main.py and registration). Cooldowns: `GRANT_COOLDOWN=5.0`, `ALERT_COOLDOWN=3.0`, heartbeat every 15s.

## Verification / testing
- No test framework, lint, or typecheck config. Sanity-check with `py_compile`.
- On Windows console set `PYTHONIOENCODING=utf-8` (prints are Vietnamese); Pi (Linux) is fine.
- Dev-PC test path: `DRY_RUN=1` in `.env` + call `supabase_client` functions (e.g. `ensure_device`, `record_access`, `flush_pending`) — never run `main.py`.
- Registration (`register_face_multi.py`): exits early unless `.env` is configured AND a `face_profiles` row with the exact `face_name` already exists on Supabase (created via web app first). Collects 15 samples across 3 poses (thẳng/trái/phải, 5 mỗi pose), filters blurry (Laplacian variance ≥ 25) and small (< 60px) faces, writes `face_db.npy` (3 templates/person), updates profile status to `registered`.
- Threshold calibration (`calibrate_threshold.py`, Pi-only, camera + models only): `collect known|unknown <n>` saves embeddings+frames to `calib_*`/, then `score` prints score distributions vs `face_db.npy` and suggests a cosine threshold from real data.
- Deploy steps (pscp/git, venv, systemd `fina.service`) are in `DEPLOY.md`.

## Hardware constants
- TFT ILI9341 320x240 landscape, RGB565 over SPI (24 MHz, mode 0). GPIO24=DC, GPIO25=RST (held high), relay GPIO23 active-high. Frames pushed as RGB565 byteswapped via SPI at command `0x2C`.