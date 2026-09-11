# Mumtaz Pharmacy — Comprehensive Biometric Attendance & Payroll System
## Full Client Specification Blueprint (12 Modules)

![Mumtaz Pharmacy Logo](C:\Users\M.Husnain\.gemini\antigravity\brain\794dfdeb-2520-4409-a9a6-c6087e8e241a\mumtaz_pharmacy_logo.jpg)

---

## 1. Executive Summary & Client Scope Alignment

The client has provided an exact 12-point specification for the **Mumtaz Pharmacy Staff Management, Attendance & Payroll Platform**. This plan maps every client requirement to concrete software components, ensuring 100% feature coverage with zero ambiguity.

---

## 2. The 12 Client Feature Modules

### Module 1: Hardware Biometric Synchronization
* **Functionality:** Full synchronization with storefront USB optical biometric thumb scanner (*DigitalPersona 4500* / *ZKTeco*).
* **Technical Flow:**
  * 0.5s sub-second fingerprint template verification.
  * Audible audio-visual confirmation chime at the counter screen.
  * Real-time hardware event hook pushing logs directly to the local SQLite and Supabase Cloud sync layer.

---

### Module 2: Mobile Geofencing Attendance (10–20m Store Radius)
* **Functionality:** Optional mobile app punch restriction allowing staff to mark attendance from mobile **ONLY** when physically present inside the pharmacy.
* **Technical Flow:**
  * System stores **Mumtaz Pharmacy Store Coordinates** (`latitude`, `longitude`, `radius_meters = 15`).
  * When a mobile punch is attempted, the app captures GPS coordinates from device hardware.
  * Uses the **Haversine Geodetic Formula**:
    $$d = 2r \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)}\right)$$
  * If calculated distance $> 20\text{ meters}$, punch is **REJECTED**:  
    ❌ *"Access Denied: You are outside Mumtaz Pharmacy premises (Current distance: 85m)."*
  * If distance $\le 20\text{ meters}$, punch is **ACCEPTED** ✅.

---

### Module 3: Automated Rules Engine (Grace Period & Late Penalties)
* **15-Minute Grace Period:** Shift starts at e.g. 09:00 AM; arrivals up to 09:15 AM have zero penalty.
* **3-Late Penalty Trigger:**
  * Tracking cumulative monthly late marks $> 15\text{ mins}$.
  * Every 3 late marks automatically trigger a **0.5 Day Wage Deduction** in the payroll calculation.

---

### Module 4: One-Click Automated Payroll Engine
* **Formula:**
  $$\text{Net Salary} = \text{Basic Salary} - \text{Absent Cuts} - \text{Late Cuts} - \text{LOP Cuts} - \text{Ledger Balance} + \text{Overtime Pay} + \text{Incentives}$$
* **Execution:** On the 1st of each month, Owner clicks **"Calculate Payroll"** $\rightarrow$ full transparent audit sheet generated in 2 seconds.

---

### Module 5: Integrated Staff Ledger (Advances, Loans & Medicine Credit)
* **Categories Tracked:**
  1. **Cash Advances:** Counter till emergency cash borrowed by staff.
  2. **Staff Loans:** Longer-term employee loans with installment deductions.
  3. **Medicine Credit Purchases:** Medicines taken by staff on credit for personal/family use.
* **Automated Settlement:** All unsettled ledger items are automatically deducted from the final monthly paycheck.

---

### Module 6: Overtime Tracker
* **Functionality:** Automatic hourly wage calculation for hours clocked beyond designated shift end.
* **Formula:**
  $$\text{Hourly Wage} = \frac{\text{Monthly Salary}}{\text{Days in Month} \times \text{Shift Hours}}$$
  $$\text{Overtime Pay} = \text{Overtime Hours} \times \text{Hourly Wage} \times 1.0\text{ (or }1.25\times\text{)}$$

---

### Module 7: Pharmacy Daily Task Board
* **Functionality:** Owner/Manager assigns operational duties to staff; staff updates progress.
* **Task Capabilities:**
  * Task Types: *“Sort expiry batch Rack A”*, *“Clean Fridge & Audit Insulin”*, *“Stock audit Panadol”*, *“Restock Surgicals”*.
  * Properties: Priority (`HIGH`, `MEDIUM`, `ROUTINE`), Assigned Staff, Due Time.
  * Staff Action: Interactive **“Mark as Done”** button with completion timestamp and optional note.

---

### Module 8: Incentive & Sales Commission Engine
* **Functionality:** Reward staff for sales performance and promoting high-margin medicines.
* **Rules Configuration:**
  * Admin sets incentives: e.g., *Ali $\rightarrow$ Multivitamin X $\rightarrow$ Rs. 50/bottle* or *Monthly target bonus Rs. 2,000*.
  * System tallies performance and automatically adds earned incentives as a positive bonus in the monthly payroll sheet.

---

### Module 9: Leave Automation & Loss of Pay (LOP) Quotas
* **Functionality:** Employee leave management with automated quota enforcement.
* **Rules:**
  * Monthly Paid Leave Quota: e.g., 2 days per month.
  * Owner panel with 1-click **Approve / Reject** buttons.
  * If approved leaves exceed monthly quota $\rightarrow$ excess days automatically marked as **Loss of Pay (LOP)** and deducted as unpaid days from salary.

---

### Module 10: Live Owner Dashboard
* **Functionality:** Real-time pulse monitoring on PC and Mobile.
* **Metrics:**
  * Who is currently on duty in the shop right now.
  * Late arrivals today with exact minutes late.
  * Absent personnel with zero punches.
  * Outstanding staff ledger balance.
  * Today's task completion progress (e.g. 4/5 tasks completed).

---

### Module 11: WhatsApp API Integration for Digital Payslips
* **Functionality:** Automated delivery of salary slips directly to staff WhatsApp numbers upon payroll generation.
* **Message Format:**
  > *"Assalam-o-Alaikum [Staff Name]! Your Mumtaz Pharmacy Payslip for [Month Year] has been generated.*  
  > *Basic Pay: Rs. [Amount]*  
  > *(-) Absent & LOP Cuts: Rs. [Amount]*  
  > *(-) Late Fines: Rs. [Amount]*  
  > *(-) Ledger/Advance Deductions: Rs. [Amount]*  
  > *(+) Overtime & Incentives: Rs. [Amount]*  
  > *━━━━━━━━━━━━━*  
  > **NET PAYABLE: Rs. [Amount]**  
  > *May Allah bless your hard work! Mumtaz Pharmacy Management."*

---

### Module 12: Comprehensive Staff Profiling Module
* **Full Staff Dossier:**
  * **Personal:** Full Name, Father's Name, Phone, WhatsApp Number, CNIC Number, Home Address.
  * **Emergency Contact:** Next of kin name, relationship, emergency phone.
  * **Employment Details:** Staff Role (*Senior Pharmacist, Counter Sales, Runner*), Assigned Shift, Monthly Basic Salary, Joining Date.
  * **Financial Details:** Payment preference (Cash, Bank Account Number / IBAN, Easypaisa / JazzCash Number).
  * **Biometric Profile:** Enrolled Fingerprint ID token status.

---

## 3. Database Schema Extensions

```sql
-- Store Coordinates for Geofencing
CREATE TABLE IF NOT EXISTS store_settings (
    id INTEGER PRIMARY KEY,
    store_name TEXT DEFAULT "Mumtaz Pharmacy",
    latitude REAL DEFAULT 31.5204,   -- Replace with exact store lat
    longitude REAL DEFAULT 74.3587,  -- Replace with exact store lng
    geofence_radius_meters INTEGER DEFAULT 20
);

-- Daily Task Board
CREATE TABLE IF NOT EXISTS daily_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    assigned_to INTEGER NOT NULL,
    priority TEXT DEFAULT "MEDIUM", -- HIGH, MEDIUM, LOW
    status TEXT DEFAULT "PENDING",  -- PENDING, IN_PROGRESS, COMPLETED
    due_date TEXT NOT NULL,
    completed_at TIMESTAMP,
    completion_notes TEXT,
    FOREIGN KEY (assigned_to) REFERENCES staff(id)
);

-- Staff Ledger (Advances, Loans & Medicine Credit)
CREATE TABLE IF NOT EXISTS staff_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    entry_type TEXT NOT NULL, -- "ADVANCE", "LOAN", "MEDICINE_CREDIT"
    amount REAL NOT NULL,
    date TEXT NOT NULL,
    description TEXT,
    is_settled INTEGER DEFAULT 0,
    settled_month INTEGER,
    settled_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);

-- Staff Incentives & Commissions
CREATE TABLE IF NOT EXISTS staff_incentives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    amount REAL NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);

-- Leave Quotas & Requests
CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    total_days INTEGER NOT NULL,
    reason TEXT,
    status TEXT DEFAULT "PENDING", -- PENDING, APPROVED, REJECTED
    is_lop INTEGER DEFAULT 0,      -- 1 if breached monthly quota
    approved_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);
```

---

## 4. Verification Plan

### Automated Tests (`tests/test_client_features.py`)
1. **Geofencing Calculation:** Verify that distance $< 20\text{m}$ returns `ALLOW` and distance $> 20\text{m}$ returns `DENY`.
2. **Staff Ledger Auto-Deduction:** Verify that advances, loans, and medicine credit are all correctly summed and subtracted from payroll.
3. **Task Board Workflow:** Verify task assignment, status transition (`PENDING` $\rightarrow$ `COMPLETED`), and timestamping.
4. **Leave Quotas & LOP:** Verify that leaves within quota (2 days) have no deduction, and excess days trigger exact Loss of Pay deduction.
5. **Incentive Engine Math:** Verify incentives add positively to net salary.

### UI & WhatsApp Verification
1. Launch UI and test Task Board interaction (Owner assigns task $\rightarrow$ Staff marks as done).
2. Test WhatsApp digital payslip formatter output payload.
3. Test staff profile form with full CNIC, Easypaisa, and emergency contact details.
