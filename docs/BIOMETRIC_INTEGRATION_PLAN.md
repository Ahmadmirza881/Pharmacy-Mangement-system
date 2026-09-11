# Standalone Plan: Biometric Fingerprint & Face Verification Integration
## Mumtaz Pharmacy Attendance Platform — Future / Sub-Module Plan

> **Note:** This module is decoupled from the active core HR & Payroll application so that your teammate/friend can work on it independently. The core system provides standard check-in/out endpoints that this module will call once ready.

---

## 1. Overview & Objective

Connect physical USB optical fingerprint scanners (e.g., **DigitalPersona U.are.U 4500**, **ZKTeco Live20R**, or compatible Windows Biometric Framework / SDK devices) or Face Recognition camera streams to the Mumtaz Pharmacy attendance system.

---

## 2. Decoupled Integration Architecture

```
┌─────────────────────────┐
│ USB Fingerprint Scanner │
│ (DigitalPersona / ZKTeco)│
└───────────┬─────────────┘
            │ 1. Raw Scan & Feature Extraction
            ▼
┌─────────────────────────┐
│ Biometric Service / SDK │ (Python win32 / C# wrapper / Native DLL)
│ - Enrolls staff fingers │
│ - Matches template      │
└───────────┬─────────────┘
            │ 2. Identified Staff ID or Token
            ▼
┌─────────────────────────────────────────────────────────┐
│ Active API Endpoint (Already Implemented in Core):       │
│ POST /api/punch                                         │
│ Body: { "staff_id": 1, "method": "FINGERPRINT" }        │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Scope of Work for Fingerprint Teammate

### Task A: Hardware SDK Selection & Driver Setup
1. Identify physical scanner model plugged into the pharmacy counter PC (e.g., DigitalPersona One Touch for Windows SDK or ZKTeco ZKBiosecurity / Standalone SDK).
2. Install device drivers on Windows.

### Task B: Fingerprint Enrollment (`POST /api/biometrics/enroll`)
1. Create a function or desktop utility to capture 3 successive thumb scans of a staff member.
2. Generate an encrypted base64 template or unique biometric token (`fingerprint_id`).
3. Store this token in the `staff.fingerprint_id` column in `mumtaz_attendance.db`.

### Task C: Live Punch Hook
1. Run a background listener on the counter PC waiting for a finger touch on the glass prism.
2. When a finger is touched:
   - Match template locally against enrolled staff database (`1:N` verification).
   - If matched $\rightarrow$ Send HTTP POST request to:
     ```json
     POST http://127.0.0.1:8000/api/punch
     {
       "staff_id": <matched_staff_id>,
       "method": "FINGERPRINT"
     }
     ```
   - If not matched $\rightarrow$ Play audible rejection buzzer / error tone.

---

## 4. Fallback Strategy

* If your friend finishes the integration successfully: It immediately connects via the `POST /api/punch` endpoint.
* If your friend is unable to complete it: The core application already has a fully functional Check-In / Check-Out counter terminal and Manual Admin Attendance Marking, so the pharmacy operations will run smoothly without any disruption.
