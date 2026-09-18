"""
Mumtaz Pharmacy - Server Executable Builder (PyInstaller)
=========================================================
Run this script to compile the FastAPI server, static frontend, and database
into a standalone, production-ready 'MumtazPharmacy_Server.exe'.

Usage:
    python build_server.py
"""

import os
import sys
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
MAIN_PY = os.path.join(BASE_DIR, "main.py")
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")

def main():
    print("=" * 60)
    print(" MUMTAZ PHARMACY - BUILDING STANDALONE SERVER.EXE")
    print("=" * 60)

    # 1. Verify PyInstaller is installed
    try:
        import PyInstaller
        print(f"[OK] Found PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("[!] PyInstaller not found. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Build PyInstaller arguments
    # We include static folder using OS-appropriate separator
    sep = ";" if os.name == "nt" else ":"
    static_arg = f"{STATIC_DIR}{sep}static"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",                          # onedir is faster to launch and preserves SQLite & static files
        "--name", "MumtazPharmacy_Server",
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
        MAIN_PY
    ]

    print(f"\n[1/3] Running PyInstaller compiler...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=BASE_DIR)

    # 3. Copy starter database and batch launcher to dist folder if not present
    output_folder = os.path.join(DIST_DIR, "MumtazPharmacy_Server")
    source_db = os.path.join(BASE_DIR, "mumtaz_attendance.db")
    target_db = os.path.join(output_folder, "mumtaz_attendance.db")

    if os.path.exists(source_db) and not os.path.exists(target_db):
        print(f"\n[2/3] Copying live database to output folder: {target_db}")
        shutil.copy2(source_db, target_db)

    # Create convenient launcher script inside output folder
    launcher_path = os.path.join(output_folder, "RUN_SERVER.bat")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write('@echo off\n')
        f.write('title Mumtaz Pharmacy Server\n')
        f.write('cd /d "%~dp0"\n')
        f.write('start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"\n')
        f.write('MumtazPharmacy_Server.exe\n')
        f.write('pause\n')

    print("\n" + "=" * 60)
    print(" [SUCCESS] BUILD COMPLETE!")
    print(f" Output Location: {output_folder}")
    print(" Executable: MumtazPharmacy_Server.exe")
    print("=" * 60)

if __name__ == "__main__":
    main()
