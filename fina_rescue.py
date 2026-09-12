"""fina-rescue: tu dong bat lai fina.service khi co lenh pending tu web.

Chay boi fina-rescue.timer (moi 10s, root). Chi hanh dong khi fina KHONG active:
- Lenh restart_service pending -> danh done (start = da restart) + start fina
- Lenh khac (checkin/checkout/register) -> chi start fina, Pi tu xu ly lenh
Mat mang / sync disabled -> im lang, tick sau thu lai.
"""
import subprocess
import sys

import supabase_client as sb


def fina_is_active():
    try:
        out = subprocess.run(
            ["systemctl", "is-active", "fina"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return out == "active"
    except Exception:
        return True  # khong chac chan -> khong lam gi


def main():
    if fina_is_active():
        return

    sb.ensure_device()
    cmd = sb.fetch_pending_command()
    if cmd is None:
        return

    ctype = cmd.get("command")
    if ctype == "restart_service":
        sb.set_command_status(
            cmd["id"], "done",
            message="Service da duoc khoi dong lai tu xa (fina-rescue)",
        )
    print(f">> [Rescue] fina dang tat, co lenh pending: {ctype} - dang start fina...")
    try:
        subprocess.run(["systemctl", "start", "fina"], timeout=15)
    except Exception as exc:
        print(">> [Rescue] start fina loi:", str(exc)[:150])


if __name__ == "__main__":
    sys.exit(main() or 0)