"""Стартира белота локално.

    python run.py              # само локално и в същата мрежа (Wi-Fi)
    python run.py --tunnel     # + публичен линк през Cloudflare Tunnel (нужен е cloudflared)
"""
import argparse
import re
import shutil
import subprocess
import sys
import threading

from belot_app import app, lan_ip

# Конзолата на Windows понякога не е в UTF-8 и гърми на кирилицата.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def start_tunnel(port):
    exe = shutil.which("cloudflared")
    if not exe:
        print("\n[!] Не намирам cloudflared. Инсталирай го с:\n"
              "      winget install --id Cloudflare.cloudflared\n"
              "    и пусни отново с --tunnel.\n")
        return
    proc = subprocess.Popen([exe, "tunnel", "--url", f"http://localhost:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def read():
        for line in proc.stdout:
            m = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", line)
            if m:
                print("\n" + "=" * 60)
                print(f"  Линк за приятели през интернет:\n  {m.group(0)}")
                print("=" * 60 + "\n")
    threading.Thread(target=read, daemon=True).start()
    return proc


def main():
    p = argparse.ArgumentParser(description="Белот сървър")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--tunnel", action="store_true", help="публичен линк през Cloudflare")
    args = p.parse_args()

    ip = lan_ip()
    print("\n  Белот върви на:")
    print(f"    Този компютър:   http://localhost:{args.port}")
    if ip:
        print(f"    Същата мрежа:    http://{ip}:{args.port}")
    print()
    tunnel = start_tunnel(args.port) if args.tunnel else None
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        if tunnel:
            tunnel.terminate()


if __name__ == "__main__":
    main()
