"""
Mumtaz Pharmacy - Client Counter Desktop Launcher
=================================================
Compiled into 'MumtazPharmacy_Client.exe' for Counter PCs (PC 2, 3, 4).
1. First time: Prompts for Server IP and saves it to 'server_ip.txt'.
2. Subsequent runs: Auto-launches immediately in 0.5 seconds with ZERO prompts!
3. To reconfigure IP: Hold 'Shift' key while opening, or delete 'server_ip.txt'.
"""

import os
import sys
import subprocess
import ctypes
import tkinter as tk
from tkinter import messagebox

# Path for persistent config file in the same directory as the exe
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "server_ip.txt")

def is_shift_held():
    """Detects if user is holding the Shift key while launching."""
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
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

    # If already configured and Shift is NOT held, launch instantly!
    if saved_ip and not is_shift_held():
        launch_app(saved_ip, save=False)
        return

    # First time OR user held Shift: Show IP Configuration Dialog
    root = tk.Tk()
    root.title("Mumtaz Pharmacy - Counter Setup")
    root.geometry("450x290")
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

    sub_label = tk.Label(
        root,
        text="LAN Counter Client Setup (Only Needed Once)",
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#0f172a"
    )
    sub_label.pack(pady=(0, 14))

    frame = tk.Frame(root, bg="#0f172a")
    frame.pack(pady=4, padx=24, fill="x")

    ip_label = tk.Label(
        frame,
        text="Main Server PC ka IP Address likhein:",
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
    ip_entry.insert(0, saved_ip if saved_ip else "192.168.100.90")
    ip_entry.pack(fill="x", ipady=4)
    ip_entry.focus_set()

    hint_label = tk.Label(
        frame,
        text="* Ye IP sirf pehli dafa save hoga, roz roz dalna nahi parega.",
        font=("Segoe UI", 8),
        fg="#10b981",
        bg="#0f172a"
    )
    hint_label.pack(anchor="w", pady=(4, 12))

    btn = tk.Button(
        root,
        text="Save & Open Pharmacy System",
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
