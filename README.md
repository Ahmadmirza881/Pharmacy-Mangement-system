# Mumtaz Pharmacy — Biometric Staff Attendance & Payroll System

A dedicated, high-performance Biometric Staff Attendance and Automated Payroll Management System engineered for **Mumtaz Pharmacy**.

## Features
- **Official Brand Theme:** Styled in Mumtaz Indigo (`#232272`) and Medical Forest Green (`#156D38`).
- **Biometric Punch Terminal:** Live digital clock, 0.5s fingerprint matching, visual badges (On-time, Late arrival, Shift complete).
- **Multi-Shift Scheduling:** Morning (9 AM - 5 PM) and Evening/Night (5 PM - 1 AM) with 15-minute grace periods.
- **Automated Salary Deduction Engine:**
  - Automatic 1-day wage deduction for absences (`Monthly Salary / Days in Month`).
  - Late arrival penalty (3 late marks = 0.5 day wage cut).
  - Half-day calculation (worked < 4 hours).
  - Overtime accumulation.
- **Staff Advance Khata:** Counter drawer cash advance tracking and automatic month-end settlement.
- **1-Click Month-End Payroll:** Computes net payable salary and generates branded, printable digital payslips.
- **Owner Dashboard:** Real-time pulse cards (Total staff, Present, Late, Absent).

## Tech Stack
- **Backend:** Python 3.13 / FastAPI / Uvicorn
- **Database:** SQLite (WAL mode, offline-first) with Supabase Cloud Sync capability
- **Frontend:** HTML5, TailwindCSS, Lucide Icons

## Quick Start
```bash
# 1. Install dependencies
pip install fastapi uvicorn

# 2. Run automated tests
python tests/test_payroll.py

# 3. Start the application
python main.py
```
Open browser at: `http://localhost:8000`
