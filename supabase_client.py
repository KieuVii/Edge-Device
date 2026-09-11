import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        return
    except ImportError:
        pass
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
DEVICE_CODE = os.getenv("DEVICE_CODE", "DOOR_01").strip()
DEVICE_NAME = os.getenv("DEVICE_NAME", "SmartLock Door").strip()
DEVICE_IP = os.getenv("DEVICE_IP", "").strip()
ROOM_UUID = os.getenv("ROOM_UUID", "").strip()
DRY_RUN = os.getenv("DRY_RUN", "0").strip() in ("1", "true", "True")

CAPTURE_BUCKET = "access-captures"
DB_PATH = BASE_DIR / "pending_ops.db"
CAPTURE_DIR = BASE_DIR / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

_CONFIGURED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)
if not _CONFIGURED:
    print(">> [Supabase] Chua cau hinh SUPABASE_URL/SERVICE_KEY -> chay KHONG dong bo (van nhan dien & mo khoa binh thuong).")
elif DRY_RUN:
    print(">> [Supabase] Dang o che do DRY_RUN - chi in payload, khong gui len Supabase.")

_client_obj = None
_device_id = None
_face_profiles = {}
_offline = False
_stop_evt = threading.Event()
_worker = None
_db_lock = threading.Lock()


def configured():
    return _CONFIGURED


def dry_run_enabled():
    return DRY_RUN


def enabled():
    return _CONFIGURED and not DRY_RUN


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _client():
    global _client_obj
    if _client_obj is None:
        from supabase import create_client
        _client_obj = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client_obj


def _resp_rows(resp):
    if resp is None:
        return []
    if hasattr(resp, "data"):
        return resp.data or []
    if isinstance(resp, dict):
        return resp.get("data") or []
    return []


def _init_db():
    with _db_lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        try:
            con.execute("CREATE TABLE IF NOT EXISTS pending ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                        "kind TEXT NOT NULL,"
                        "payload TEXT NOT NULL,"
                        "attempts INTEGER DEFAULT 0,"
                        "last_error TEXT,"
                        "created_at TEXT DEFAULT (datetime('now')))")
            con.commit()
        finally:
            con.close()


def _enqueue(kind, payload):
    _init_db()
    with _db_lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        try:
            con.execute("INSERT INTO pending(kind, payload) VALUES(?, ?)",
                        (kind, json.dumps(payload, ensure_ascii=False)))
            con.commit()
        finally:
            con.close()


def _drain(limit=30):
    with _db_lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute("SELECT id, kind, payload, attempts FROM pending ORDER BY id LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            con.close()
    return rows


def _mark_error(row_id, attempts, err):
    with _db_lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        try:
            con.execute("UPDATE pending SET attempts = ?, last_error = ? WHERE id = ?",
                        (attempts, str(err)[:300], row_id))
            con.commit()
        finally:
            con.close()


def _delete(row_id):
    with _db_lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        try:
            con.execute("DELETE FROM pending WHERE id = ?", (row_id,))
            con.commit()
        finally:
            con.close()


def _is_offline_error(exc):
    s = str(exc).lower()
    hints = ("timed out", "timeout", "connection", "connecterror", "network",
             "name resolution", "unreachable", "getaddrinfo", "remote host closed",
             "read timed out", "max retries", "broken pipe", "refused")
    return any(h in s for h in hints)


def _is_permanent_error(exc):
    s = str(exc)
    hints = ("401", "403", "404", "400", "invalid api key", "jwt", "permission denied",
             "duplicate key", "42p01", "42703", "rpc", "preflight", "cors")
    return any(h in s for h in hints)


def _upload_capture(path):
    name = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    _client().storage.from_(CAPTURE_BUCKET).upload(
        name, data, {"content-type": "image/jpeg"})
    return f"{SUPABASE_URL}/storage/v1/object/public/{CAPTURE_BUCKET}/{name}"


def _try_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _handle_access_event(payload):
    local_image = payload.pop("local_image", None)
    alert = payload.pop("alert", None)

    image_url = None
    if local_image and os.path.exists(local_image):
        image_url = _upload_capture(local_image)
        _try_remove(local_image)

    log_id = str(uuid.uuid4())
    if image_url:
        payload["captured_image_url"] = image_url
    payload["id"] = log_id
    _client().table("access_logs").insert(payload, returning="minimal").execute()

    if alert:
        if image_url:
            alert["image_url"] = image_url
        alert["access_log_id"] = log_id
        alert["device_id"] = payload.get("device_id")
        alert["room_id"] = payload.get("room_id")
        alert["user_id"] = payload.get("user_id")
        alert.setdefault("severity", "medium")
        alert["updated_at"] = _now_iso()
        _client().table("alerts").insert(alert, returning="minimal").execute()


def _handle_device_state(payload):
    fields = {k: v for k, v in payload.items() if v is not None}
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    _client().table("devices").update(fields, returning="minimal").eq("device_code", DEVICE_CODE).execute()


def _handle_face_registered(payload):
    face_name = payload["face_name"]
    fields = {k: v for k, v in payload.items() if k != "face_name" and v is not None}
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    _client().table("face_profiles").update(fields, returning="minimal").eq("face_name", face_name).execute()


_HANDLERS = {
    "access_event": _handle_access_event,
    "device_state": _handle_device_state,
    "face_registered": _handle_face_registered,
}


def _cleanup_payload_file(payload):
    if isinstance(payload, dict):
        _try_remove(payload.get("local_image"))


def _process(row):
    kind = row["kind"]
    payload = json.loads(row["payload"])
    _HANDLERS[kind](payload)


def _worker_loop():
    global _offline
    while not _stop_evt.is_set():
        rows = _drain(20)
        if not rows:
            _stop_evt.wait(2)
            continue
        for row in rows:
            if _stop_evt.is_set():
                break
            try:
                _process(row)
                _offline = False
                _delete(row["id"])
            except Exception as exc:
                if _is_permanent_error(exc):
                    print(">> [Supabase] Bo ghi nhan (loi cau hinh/khong the xu ly):", str(exc)[:200])
                    try:
                        payload = json.loads(row["payload"])
                        _cleanup_payload_file(payload)
                    except Exception:
                        pass
                    _delete(row["id"])
                elif _is_offline_error(exc):
                    _offline = True
                    print(">> [Supabase] Mat ket noi, cac ban ghi se gui lai khi co mang...")
                    break
                else:
                    attempts = int(row["attempts"]) + 1
                    _mark_error(row["id"], attempts, str(exc))
                    print(">> [Supabase] Gui that bai, se thu lai:", str(exc)[:150])
        time.sleep(2 if not _offline else 8)


def start_worker():
    global _worker
    if not enabled():
        return
    _init_db()
    if _worker is not None and _worker.is_alive():
        return
    _stop_evt.clear()
    _worker = threading.Thread(target=_worker_loop, name="supabase-sync", daemon=True)
    _worker.start()


def flush_pending(timeout=8):
    if not enabled():
        return
    _init_db()
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = _drain(20)
        if not rows:
            return
        progressed = False
        for row in rows:
            try:
                _process(row)
                _delete(row["id"])
                progressed = True
            except Exception as exc:
                if _is_permanent_error(exc):
                    print(">> [Supabase] Bo ghi nhan (flush):", str(exc)[:200])
                    _delete(row["id"])
                    progressed = True
                elif _is_offline_error(exc):
                    print(">> [Supabase] Van chua co mang, con ban ghi cho gui lai sau.")
                    return
                else:
                    attempts = int(row["attempts"]) + 1
                    _mark_error(row["id"], attempts, str(exc))
        if not progressed:
            time.sleep(1)


def stop_worker(timeout=8):
    _stop_evt.set()
    if _worker is not None:
        _worker.join(timeout=2)
    flush_pending(timeout)
    if enabled():
        remaining = _drain(1)
        if remaining:
            print(f">> [Supabase] Con {len(_drain(100))} ban ghi chua gui duoc (da luu local, se gui khi chay lai).")


def ensure_device():
    global _device_id
    if not enabled():
        return None
    payload = {
        "device_code": DEVICE_CODE,
        "device_name": DEVICE_NAME,
        "status": "online",
    }
    if ROOM_UUID:
        payload["room_id"] = ROOM_UUID
    if DEVICE_IP:
        payload["ip_address"] = DEVICE_IP
    payload["updated_at"] = _now_iso()
    try:
        resp = _client().table("devices").upsert(payload, on_conflict="device_code").execute()
        rows = _resp_rows(resp)
        if rows:
            _device_id = rows[0]["id"]
            return _device_id
    except Exception as exc:
        print(">> [Supabase] ensure_device loi:", str(exc)[:150])
    return None


def device_id():
    return _device_id


def load_face_profiles():
    global _face_profiles
    _face_profiles = {}
    if not enabled():
        return None
    try:
        resp = _client().table("face_profiles").select("id, user_id, room_id, face_name").execute()
        for p in _resp_rows(resp):
            if p.get("face_name"):
                _face_profiles[p["face_name"]] = {
                    "face_profile_id": p.get("id"),
                    "user_id": p.get("user_id"),
                    "room_id": p.get("room_id"),
                }
    except Exception as exc:
        print(">> [Supabase] load_face_profiles loi:", str(exc)[:150])
        return None
    return _face_profiles


def get_face_profile(face_name):
    return _face_profiles.get(face_name)


def save_capture(frame, label=""):
    import cv2
    tag = "".join(ch for ch in label if ch.isalnum()) or "capture"
    name = f"{DEVICE_CODE}_{tag}_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    path = str(CAPTURE_DIR / name)
    ok = cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return path if ok else None


def record_access(result, similarity=None, face_name=None, face_profile=None,
                  threshold=0.32, note="", alert=None, local_image=None, access_type=None):
    if not enabled():
        if DRY_RUN:
            print("[DRY-RUN] access_logs:", json.dumps({
                "device_code": DEVICE_CODE, "face_name": face_name, "result": result,
                "similarity": similarity, "threshold": threshold, "note": note,
                "access_type": access_type,
            }, ensure_ascii=False, default=str))
            if alert:
                print("[DRY-RUN] alerts:", json.dumps(alert, ensure_ascii=False, default=str))
        return False

    payload = {
        "device_id": _device_id,
        "face_name": face_name,
        "result": result,
        "similarity": similarity,
        "threshold": threshold,
        "note": note,
    }
    if access_type:
        payload["access_type"] = access_type
    if face_profile:
        payload["user_id"] = face_profile.get("user_id")
        payload["face_profile_id"] = face_profile.get("face_profile_id")
        payload["room_id"] = face_profile.get("room_id")
    if alert:
        payload["alert"] = {k: v for k, v in alert.items() if v is not None}
    if local_image:
        payload["local_image"] = local_image
    _enqueue("access_event", payload)
    return True


def set_door_status(status):
    if DRY_RUN:
        print(f"[DRY-RUN] device door_status={status}")
    if not enabled():
        return False
    _enqueue("device_state", {"door_status": status, "status": "online"})
    return True


def heartbeat_tick():
    if not enabled() or _offline:
        return
    _enqueue("device_state", {"status": "online", "last_seen": _now_iso()})


def set_device_offline():
    if DRY_RUN:
        print("[DRY-RUN] device status=offline")
    if not enabled():
        return
    _enqueue("device_state", {"status": "offline"})


def find_face_profile(name):
    if not enabled():
        return None
    try:
        resp = _client().table("face_profiles").select("*").ilike("face_name", name).limit(1).execute()
        rows = _resp_rows(resp)
        return rows[0] if rows else None
    except Exception as exc:
        print(">> [Supabase] find_face_profile loi:", str(exc)[:150])
        return None


def mark_face_registered(face_name, sample_count=10):
    if not enabled():
        return "disabled"
    fields = {
        "status": "registered",
        "sample_count": sample_count,
        "registered_at": _now_iso(),
        "registered_by_device_id": _device_id,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    try:
        _client().table("face_profiles").update(fields, returning="minimal").eq("face_name", face_name).execute()
        return "ok"
    except Exception as exc:
        if _is_offline_error(exc) or _is_permanent_error(exc):
            print(">> [Supabase] mark_face_registered tam hoan, se gui lai:", str(exc)[:150])
            _enqueue("face_registered", {"face_name": face_name, **fields})
            return "queued"
        print(">> [Supabase] mark_face_registered loi:", str(exc)[:150])
        return "error"


def fetch_pending_command():
    if not enabled() or not _device_id:
        return None
    try:
        resp = (
            _client()
            .table("device_commands")
            .select("id, command, payload, status")
            .eq("device_id", _device_id)
            .eq("status", "pending")
            .order("requested_at")
            .limit(1)
            .execute()
        )
        rows = _resp_rows(resp)
        return rows[0] if rows else None
    except Exception as exc:
        print(">> [Supabase] fetch_pending_command loi:", str(exc)[:150])
        return None


def set_command_status(command_id, status, message=None):
    if not enabled():
        return False
    fields = {"status": status}
    if message:
        fields["result_message"] = str(message)[:500]
    if status in ("done", "failed", "cancelled"):
        fields["executed_at"] = _now_iso()
    try:
        _client().table("device_commands").update(fields, returning="minimal").eq("id", command_id).execute()
        return True
    except Exception as exc:
        print(">> [Supabase] set_command_status loi:", str(exc)[:150])
        return False
