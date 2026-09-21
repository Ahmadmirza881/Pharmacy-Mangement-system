"""
Mumtaz Pharmacy - Smart Client Counter Desktop Launcher
========================================================
Compiled into 'MumtazPharmacy_Client.exe' for Counter PCs (PC 2, 3, 4).
1. Automatically checks if the saved server IP is reachable (1.5s timeout).
2. If reachable: Instantly launches fullscreen App Mode in 0.5s!
3. If NOT reachable or first run: Automatically shows the IP setup dialog
   so you are NEVER stuck, and can easily change the IP!
"""

import os
import sys
import socket
import subprocess
import tkinter as tk
from tkinter import messagebox

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "server_ip.txt")

def is_server_reachable(ip, port=8000, timeout=1.5):
    """Quick socket check to verify if the server is actively listening."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        return True
    except Exception:
        return False

def find_browser_app_cmd(ip, port=8000):
    url = f"http://{ip}:{port}"
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in edge_paths + chrome_paths:
        if os.path.exists(p):
            return [p, f"--app={url}"]
    return ["cmd", "/c", "start", url]

def launch_app(ip, save=True):
    ip = ip.strip()
    if not ip:
        messagebox.showerror("Error", "Server IP address likhna zaroori hai!")
        return
    if save:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(ip)
        except Exception:
            pass
    cmd = find_browser_app_cmd(ip)
    try:
        subprocess.Popen(cmd)
        sys.exit(0)
    except Exception as e:
        messagebox.showerror("Error", f"Browser open karne me error: {str(e)}")

def main():
    saved_ip = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    saved_ip = content
        except Exception:
            pass

    # If we have a saved IP, test if the server is alive right now
    if saved_ip:
        if is_server_reachable(saved_ip, port=8000, timeout=1.5):
            # Server is alive! Auto-launch immediately
            launch_app(saved_ip, save=False)
            return

    # If unreachable or first run: Show Friendly IP Dialog
    root = tk.Tk()
    root.title("Mumtaz Pharmacy - Counter Connection")
    root.geometry("460x320")
    root.resizable(False, False)
    root.configure(bg="#0f172a")

    root.eval('tk::PlaceWindow . center')

    title_label = tk.Label(
        root,
        text="MUMTAZ PHARMACY",
        font=("Segoe UI", 16, "bold"),
        fg="#34d399",
        bg="#0f172a"
    )
    title_label.pack(pady=(16, 2))

    status_text = "Server IP Connect Karein"
    status_fg = "#94a3b8"
    if saved_ip:
        status_text = f"Pichla IP ({saved_ip}) connect nahi hua. Naya IP dalein:"
        status_fg = "#f87171" # Rose red warning

    sub_label = tk.Label(
        root,
        text=status_text,
        font=("Segoe UI", 9, "bold" if saved_ip else "normal"),
        fg=status_fg,
        bg="#0f172a"
    )
    sub_label.pack(pady=(0, 12))

    frame = tk.Frame(root, bg="#0f172a")
    frame.pack(pady=4, padx=24, fill="x")

    ip_label = tk.Label(
        frame,
        text="Main Server PC ka IP Address:",
        font=("Segoe UI", 10, "bold"),
        fg="#e2e8f0",
        bg="#0f172a"
    )
    ip_label.pack(anchor="w", pady=(0, 4))

    ip_entry = tk.Entry(
        frame,
        font=("Segoe UI", 12),
        bg="#1e293b",
        fg="#ffffff",
        insertbackground="#34d399",
        relief="flat",
        highlightthickness=1,
        highlightbackground="#334155",
        highlightcolor="#34d399"
    )
    # Default to 127.0.0.1 if saved_ip not set
    ip_entry.insert(0, saved_ip if saved_ip else "127.0.0.1")
    ip_entry.pack(fill="x", ipady=4)
    ip_entry.focus_set()
    ip_entry.select_range(0, tk.END)

    hint_label = tk.Label(
        frame,
        text="Ghar me test karne k liye: 127.0.0.1 dalein\nPharmacy me: Main PC ki screen par likha IP dalein",
        font=("Segoe UI", 8),
        justify="left",
        fg="#94a3b8",
        bg="#0f172a"
    )
    hint_label.pack(anchor="w", pady=(6, 12))

    btn = tk.Button(
        root,
        text="Connect & Open System",
        font=("Segoe UI", 11, "bold"),
        bg="#059669",
        fg="#ffffff",
        activebackground="#10b981",
        activeforeground="#ffffff",
        relief="flat",
        cursor="hand2",
        command=lambda: launch_app(ip_entry.get())
    )
    btn.pack(fill="x", padx=24, ipady=6, pady=(0, 10))

    root.bind("<Return>", lambda e: launch_app(ip_entry.get()))
    root.mainloop()

if __name__ == "__main__":
    main()
