"""
Build All Executables for Mumtaz Pharmacy
=========================================
Generates:
1. FOR_MAIN_SERVER_PC -> MumtazPharmacy_Server.exe (+ static files & database)
2. FOR_COUNTER_PCS    -> MumtazPharmacy_Client.exe (Single standalone executable)
"""

import os
import sys
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
MAIN_PY = os.path.join(BASE_DIR, "main.py")
CLIENT_PY = os.path.join(BASE_DIR, "client_launcher.py")
OUTPUT_DIR = os.path.join(BASE_DIR, "READY_FOR_CLIENT")
SERVER_OUT = os.path.join(OUTPUT_DIR, "FOR_MAIN_SERVER_PC")
CLIENT_OUT = os.path.join(OUTPUT_DIR, "FOR_COUNTER_PCS")

def main():
    print("=" * 65)
    print("   MUMTAZ PHARMACY - BUILDING ALL CLIENT & SERVER EXEs")
    print("=" * 65)

    # 1. Ensure PyInstaller is installed
    try:
        import PyInstaller
        print(f"[OK] PyInstaller found: {PyInstaller.__version__}")
    except ImportError:
        print("[!] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Clean / prepare output folders
    os.makedirs(SERVER_OUT, exist_ok=True)
    os.makedirs(CLIENT_OUT, exist_ok=True)

    # 2. Build MumtazPharmacy_Client.exe (Single standalone EXE for counters)
    client_exe = os.path.join(CLIENT_OUT, "MumtazPharmacy_Client.exe")
    if not os.path.exists(client_exe):
        print("\n" + "-" * 65)
        print("[1/2] Compiling MumtazPharmacy_Client.exe for Counter PCs...")
        print("-" * 65)
        client_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name", "MumtazPharmacy_Client",
            "--distpath", CLIENT_OUT,
            CLIENT_PY
        ]
        subprocess.check_call(client_cmd, cwd=BASE_DIR)
    else:
        print("[OK] MumtazPharmacy_Client.exe is already built in FOR_COUNTER_PCS!")

    # 3. Build MumtazPharmacy_Server.exe (Server package with backend & static assets)
    print("\n" + "-" * 65)
    print("[2/2] Compiling MumtazPharmacy_Server.exe for Main PC...")
    print("-" * 65)
    sep = ";" if os.name == "nt" else ":"
    static_arg = f"{STATIC_DIR}{sep}static"

    server_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name", "MumtazPharmacy_Server",
        "--distpath", SERVER_OUT,
        "--add-data", static_arg,
        "--hidden-import", "uvicorn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "fastapi",
        "--hidden-import", "pydantic",
        "--hidden-import", "openpyxl",
        "--hidden-import", "sqlite3",
        "--hidden-import", "license_manager",
        "--hidden-import", "payroll_engine",
        "--hidden-import", "biometric_service",
        "--hidden-import", "whatsapp_service",
        # Exclude huge unused anaconda packages for ultra-fast build and small size
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "IPython",
        "--exclude-module", "notebook",
        "--exclude-module", "sphinx",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PyQt6",
        "--exclude-module", "PySide2",
        "--exclude-module", "PySide6",
        "--exclude-module", "tornado",
        "--exclude-module", "pytest",
        MAIN_PY
    ]
    subprocess.check_call(server_cmd, cwd=BASE_DIR)

    # 4. Copy starter database to Server folder
    server_bundle_dir = os.path.join(SERVER_OUT, "MumtazPharmacy_Server")
    source_db = os.path.join(BASE_DIR, "mumtaz_attendance.db")
    target_db = os.path.join(server_bundle_dir, "mumtaz_attendance.db")
    if os.path.exists(source_db) and not os.path.exists(target_db):
        shutil.copy2(source_db, target_db)

    # Copy convenient launcher batch script into Server folder
    launcher_path = os.path.join(server_bundle_dir, "RUN_SERVER.bat")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write('@echo off\n')
        f.write('title Mumtaz Pharmacy Server\n')
        f.write('cd /d "%~dp0"\n')
        f.write('start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"\n')
        f.write('MumtazPharmacy_Server.exe\n')
        f.write('pause\n')

    print("\n" + "=" * 65)
    print("   [SUCCESS] ALL EXECUTABLES CREATED SUCCESSFULLY!")
    print("=" * 65)
    print(f"Folder: {OUTPUT_DIR}")
    print(" 1. FOR_MAIN_SERVER_PC  -> MumtazPharmacy_Server/ (Main PC ke liye)")
    print(" 2. FOR_COUNTER_PCS     -> MumtazPharmacy_Client.exe (Baqi 3-4 PCs ke liye)")
    print("=" * 65)

if __name__ == "__main__":
    main()
