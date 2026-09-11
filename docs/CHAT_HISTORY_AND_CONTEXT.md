# Mumtaz Pharmacy — Complete Project Memory & Chat History

This document contains a comprehensive record of all discussions, business decisions, technical discoveries, and client specifications for the **Mumtaz Pharmacy Biometric Attendance & Automated Payroll System**.

---

## 1. Project Background
* **Client:** Mumtaz Pharmacy (Pakistan).
* **Current Situation:** The pharmacy operates a desktop billing system on a local PC, but staff attendance was manual, leading to inaccurate hours, late-coming disputes, and tedious month-end salary calculations.
* **Initial Decision:** Rather than overhauling the live POS billing immediately, the client requested to first build and deploy a dedicated **Biometric Staff Attendance & Automated Payroll Management System**.

---

## 2. Key Decisions & Agreements Made During Discussion

### A. Branding & Theme:
* The user provided the official high-resolution logo for **Mumtaz Pharmacy**.
* **Colors Extracted:**
  * **Mumtaz Indigo:** `#232272` (Primary branding, headers, navigation).
  * **Forest Medical Green:** `#156D38` (Secondary accents, present badges, credits, action buttons).
  * **Clinical White / Slate:** `#FFFFFF` and `#F8FAFC`.

### B. Hardware Comparison & Conclusion:
* **Standalone Wall Machine (ZKTeco K50):** Has internal battery, screen, and speaker. Saves punches in memory and connects via Wi-Fi/LAN to our software via `pyzk`.
* **USB Desktop Scanner (DigitalPersona 4500):** Industry standard in Pakistan banks and NADRA. Cheaper refurbished on OLX/Hafeez Centre (Rs. 4,500 - 6,500 PKR).
* **Ultra-Budget Electronic Module (R307):** Optical module with USB-UART cable (Rs. 3,500 - 4,500 PKR on Daraz), supported natively by Python `pyfingerprint`.

### C. Architecture: "Hybrid Cloud Sync" (Local-First + Free Supabase):
* **Why not Pure Local?** If only local, the Owner cannot view attendance on their mobile when the shop PC is turned off at night.
* **Why not Pure Cloud?** If only cloud, an internet outage in the pharmacy prevents staff from checking in ("No Internet" error).
* **The Winning Solution:** 
  1. Punches save instantly (0.01s) to shop PC SQLite database (works 100% offline).
  2. Background worker auto-syncs logs to **Free Supabase Cloud Database** when internet is active.
  3. The **Owner Mobile App** reads directly from Supabase, allowing 24/7 access even with shop PC off.
  4. Real-time push notifications sent via **Firebase Cloud Messaging (FCM)** (100% Free).

---

## 3. The 12 Client-Specified Modules (Final Scope)

1. **Hardware Integration:** USB optical thumb-scanner / facial recognition at storefront.
2. **Mobile Geofencing:** Optional mobile punch restricted to within a 10–20 meter radius of store coordinates using Haversine formula.
3. **Automated Rules:** 15-minute grace period; 3 late marks $> 15\text{ mins}$ trigger automatic half-day deduction.
4. **One-Click Payroll:** Auto-computes net pay factoring attendance, overtime, late penalties, leaves, advances.
5. **Integrated Staff Ledger:** Dedicated tracking for salary advances, staff loans, and medicine credit purchases (auto-deducted from final monthly paycheck).
6. **Overtime Tracker:** Automatic calculation of hourly wages for hours clocked beyond designated shift.
7. **Daily Task Board:** Owner assigns pharmacy duties (*"Sort expiry batch"*, *"Clean Rack B"*) with staff *"Mark as Done"* button.
8. **Incentive Engine:** Sales commissions and monthly target bonuses mapped to staff logins.
9. **Leave Automation:** One-click approval/rejection panel for leave requests with automatic Loss of Pay (LOP) once quotas are breached.
10. **Live Owner Dashboard:** Real-time summary of active on-duty staff, late arrivals, and absent personnel.
11. **WhatsApp API Integration:** Automated delivery of digital salary slips to staff WhatsApp numbers.
12. **Staff Profiling Module:** Full staff dossier (CNIC, phone, emergency contact, home address, Bank/Easypaisa details, joining date).

---

## 4. Current Implementation Status
* Working FastAPI backend (`main.py`) with SQLite schema (`database.py`).
* Core Payroll Math Engine (`payroll_engine.py`) with 100% automated test coverage (`tests/test_payroll.py`).
* Interactive Mumtaz Pharmacy Branded UI (`static/index.html`) running on `http://localhost:8000`.
* Git repository pushed to: `https://github.com/mhusnain137/pharmacy-attendance-system`.
