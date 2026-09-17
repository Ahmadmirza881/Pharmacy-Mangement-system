# Performance Baseline Report (BEFORE)

**System:** Mumtaz Pharmacy Management System  
**Environment:** Windows (PowerShell / Python 3.11 / FastAPI / SQLite / Chrome)  
**Date:** 2026-09-17  
**Measurement Method:** Real empirical benchmark via TestClient & SQLite `EXPLAIN QUERY PLAN` timer measurements.

---

## 1. Measured Performance Baseline

| Area / Operation | Before Metric | Payload Size | Status / Notes |
| :--- | :--- | :--- | :--- |
| **Initial Page Load (`/static/index.html`)** | **10.59 ms** | **658,388 bytes (658 KB)** | Uncompressed raw transfer, CDN dependencies |
| **Dashboard / Today Activities (`/api/activities/today`)** | **10.48 ms** | **14,797 bytes** | Full table scan on activity_logs with temp B-Tree sort |
| **Live Attendance Today (`/api/attendance/today`)** | **6.83 ms** | **3,214 bytes** | OK (200) |
| **Staff Directory (`/api/staff`)** | **6.55 ms** | **3,326 bytes** | OK (200) |
| **Customer List (`/api/customers`)** | **6.75 ms** | **3,311 bytes** | OK (200) |
| **Customer Ledger / Khata KPIs** | **5.59 ms** | **159 bytes** | OK (200) |
| **Staff Advances List (`/api/advances`)** | **8.24 ms** | **5,074 bytes** | Full table scan on advance_salaries |
| **Staff Leaves List (`/api/leaves`)** | **9.10 ms** | **5,951 bytes** | Full table scan on leaves |
| **Staff Search Input Keystroke Response** | **High Lag (Full DOM Rebuild)** | — | Fires oninput immediately without debounce |
| **Customer Search Input Keystroke Response** | **High Lag (Full DOM Rebuild)** | — | Fires oninput immediately without debounce |
| **Payroll Search Input Keystroke Response** | **High Lag (Full DOM Rebuild)** | — | Fires oninput immediately without debounce |
| **Kiosk Attendance Search Keystroke Response** | **High Lag (Full DOM Rebuild)** | — | Fires oninput immediately without debounce |
| **Lucide Icon Re-scan Overhead** | **54 Global Scans** | — | Scans entire 12,000-line DOM on every micro-render |
| **Browser CPU & Memory Impact** | **Elevated during search** | ~658 KB HTML in DOM | Layout thrashing on rapid keypresses |

---

## 2. SQL Query Plan & Latency Baseline (BEFORE Indexes)

| Query Type | Baseline Time | SQLite Query Plan | Bottleneck / Root Cause |
| :--- | :--- | :--- | :--- |
| `Monthly attendance date range` | `0.5491 ms` | `SCAN attendance_logs` | Missing index on `attendance_logs(date)` |
| `Activity logs (Recent 50)` | `1.7719 ms` | `SCAN activity_logs \| USE TEMP B-TREE FOR ORDER BY` | Missing index on `activity_logs(created_at DESC)` |
| `Customer khata by customer` | `0.0137 ms` | `SCAN customer_khata \| USE TEMP B-TREE FOR ORDER BY` | Missing index on `customer_khata(customer_id, date)` |
| `Staff by PIN (Kiosk Attendance)` | `0.0316 ms` | `SCAN staff` | Missing index on `staff(pin, is_active)` |
| `Staff by Phone` | `0.0091 ms` | `SCAN staff` | Missing index on `staff(phone)` |
| `Unsettled advances by staff` | `0.0109 ms` | `SCAN advance_salaries` | Missing index on `advance_salaries(staff_id, is_settled)` |
| `Customers by phone` | `0.0046 ms` | `SCAN customers` | Missing index on `customers(phone)` |
| `OTP Token Lookup` | `0.0049 ms` | `SEARCH otp_verifications USING INDEX idx_otp_token` | Indexed |

---

## 3. Frontend & Network Baseline

* **Duplicate External Libraries:** Redundant `xlsx.full.min.js` loaded twice (`/static/xlsx.full.min.js` and `https://cdn.jsdelivr.net/npm/xlsx...`).
* **Uncompressed HTML:** 658 KB single-file DOM loaded without HTTP GZip compression.
* **Active Polling Timers:** Unrestricted background timers running regardless of active tab state.
* **Search Input Lag:** 6 critical search fields lacking input debounce (120ms).
