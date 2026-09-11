# Mumtaz Pharmacy — Antigravity IDE Project Memory & Rules

This project workspace is the **Mumtaz Pharmacy Biometric Staff Attendance & Payroll System**.
Whenever working inside this workspace in Antigravity IDE, strictly adhere to these rules, context, and standards:

## 1. Brand Identity & Colors
* **Client Name:** Mumtaz Pharmacy (Official logo is located in `static/logo.jpg`).
* **Primary Brand Color (Mumtaz Indigo):** `#232272` (Main headers, navigation bar, punch terminal frame).
* **Secondary Brand Color (Pharmacy Green):** `#156D38` (Present status, verified punches, action buttons, credits).
* **Backgrounds:** Clean White `#FFFFFF` and Soft Slate `#F8FAFC`.

## 2. Core Architecture (Local-First + Hybrid Cloud Sync)
* **Local Counter Engine:** Python 3.13 / FastAPI running on the shop PC with SQLite in WAL mode.
* **Offline-First Guarantee:** Fingerprint punches are saved locally in 0.01 seconds even if the internet is down.
* **Cloud Sync:** Background worker syncs attendance records to a free **Supabase** cloud database so the Owner can check live reports 24/7 on mobile, even when the shop PC is turned off at night.
* **Cost:** Rs. 0 / Month running cost.

## 3. The 12 Client-Specified Modules
1. **Hardware Integration:** USB Biometric Scanner (DigitalPersona 4500 / ZKTeco ZK4500) with 0.5s match.
2. **Mobile Geofencing:** Optional mobile punch restricted to within 10-20 meters of store GPS coordinates using Haversine formula.
3. **Automated Rules:** 15-minute grace period; 3 lates in a month = 0.5 day wage cut.
4. **One-Click Payroll:** Auto-computes net pay: `Basic - Absent Cuts - Late Cuts - Advances + Overtime + Incentives`.
5. **Integrated Staff Ledger:** Tracks cash advances, staff loans, and medicine credit purchases; auto-deducted at month end.
6. **Overtime Tracker:** Automatic calculation of extra hours clocked beyond shift end.
7. **Daily Task Board:** Owner assigns pharmacy duties (*"Sort expiry batch"*, *"Clean Rack B"*) with staff *"Mark as Done"* button.
8. **Incentive Engine:** Sales commissions and monthly target bonuses mapped to staff logins.
9. **Leave Automation & LOP:** Monthly leave quota (e.g. 2 paid leaves); excess days automatically trigger Loss of Pay (LOP) deduction.
10. **Live Owner Dashboard:** Real-time summary of active on-duty staff, late arrivals, and absent personnel.
11. **WhatsApp API Integration:** Automated delivery of formatted digital salary slips to staff WhatsApp upon payroll generation.
12. **Staff Profiling Module:** Full dossier (CNIC, phone, emergency contact, home address, Bank/Easypaisa details, joining date).

## 4. Running the System
```bash
# Start backend server
python main.py
# Access Web UI
http://localhost:8000
# Run automated test suite
python tests/test_payroll.py
```
