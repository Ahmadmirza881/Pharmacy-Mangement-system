# Root-Cause Performance Audit Report

This audit documents all confirmed bottlenecks and stability issues across Frontend, Backend, Database, and Network layers of the Mumtaz Pharmacy Management System.

---

### Audit Finding #1: Un-debounced Search Inputs & High UI Latency
* **Problem:** Typing in any search field (Staff, Customers, Kiosk Attendance, Payroll, Ledger) causes noticeable input lag, dropped frames, and sluggish UI response.
* **File:** `static/index.html`
* **Components / Functions:** `syncStaffSearch()`, `handleStaffFilter()`, `filterLeavesTable()`, `filterCustomerTable()`, `filterKioskStaff()`, `filterPayrollTable()`, `handleAdvSearch()`
* **Root Cause:** Raw `oninput="..."` triggers immediate JS filtering, full table DOM wipe & rebuild, and full document icon scan on every single keystroke.
* **Impact:** 60fps drops to <15fps during typing; UI freezes for milliseconds on each character typed.
* **Severity:** **CRITICAL**
* **Evidence:** 17 search inputs firing immediate DOM updates without timing control.
* **Recommended Solution:** Implement a centralized, lightweight `debounce(fn, wait=120)` wrapper for all interactive search and filter event handlers.

---

### Audit Finding #2: Global Lucide Icon Scanning Thrashing
* **Problem:** Calling `lucide.createIcons()` scans and mutates the entire 12,000-line DOM document every time any small card or row is rendered.
* **File:** `static/index.html`
* **Functions:** `renderStaffCards()`, `renderCustomerTable()`, `renderPayrollTable()`, `renderLeavesTable()`, `renderAdvances()`, `renderKioskStaffGrid()`
* **Root Cause:** 54 separate calls to `lucide.createIcons()` without element scoping, forcing browser to re-traverse the entire `document.body` tree.
* **Impact:** Excessive layout recalculations (DOM thrashing) and browser main thread blocking.
* **Severity:** **HIGH**
* **Evidence:** Grep found 54 distinct invocations of `lucide.createIcons()`.
* **Recommended Solution:** Replace un-scoped global icon calls with a debounced / microtask-batched icon scheduler (`scheduleIconsRender(container)`).

---

### Audit Finding #3: Missing SQLite Indexes & Temp B-Tree Sorting
* **Problem:** Database queries for activity feeds, monthly attendance logs, customer ledger lookups, and staff PIN validation perform full table scans and disk/memory temp sorting.
* **File:** `database.py`
* **Queries Affected:** 
  - `SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 50` -> `SCAN activity_logs | USE TEMP B-TREE`
  - `SELECT * FROM attendance_logs WHERE date >= ? AND date <= ?` -> `SCAN attendance_logs`
  - `SELECT * FROM customer_khata WHERE customer_id = ? ORDER BY date DESC` -> `SCAN customer_khata | USE TEMP B-TREE`
  - `SELECT * FROM staff WHERE pin = ? AND is_active = 1` -> `SCAN staff`
* **Root Cause:** Lack of composite and single-column indexes on high-frequency filtering and ordering fields.
* **Impact:** Query latency scales linearly $O(N)$ and degrades rapidly as records accumulate.
* **Severity:** **HIGH**
* **Evidence:** Verified via `EXPLAIN QUERY PLAN` showing full table scans and temp B-Tree allocations.
* **Recommended Solution:** Add targeted `CREATE INDEX IF NOT EXISTS` statements for:
  - `idx_attendance_date` on `attendance_logs(date)`
  - `idx_activity_created` on `activity_logs(created_at DESC)`
  - `idx_customer_khata_cust_date` on `customer_khata(customer_id, date DESC)`
  - `idx_staff_pin` on `staff(pin, is_active)`
  - `idx_staff_phone` on `staff(phone)`
  - `idx_advances_staff_settled` on `advance_salaries(staff_id, is_settled)`
  - `idx_leaves_staff_date` on `leaves(staff_id, date)`

---

### Audit Finding #4: SQLite Disk I/O & Memory Cache Sub-optimization
* **Problem:** Default SQLite connection settings under Windows perform disk flushes and maintain a small 2MB cache.
* **File:** `database.py` (`get_db_connection`)
* **Root Cause:** Missing performance PRAGMAs (`synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`, `mmap_size=268435456`).
* **Impact:** Unnecessary disk write locks and memory cache misses.
* **Severity:** **MEDIUM**
* **Evidence:** Only WAL mode and Foreign Keys were enabled in `get_db_connection()`.
* **Recommended Solution:** Enable safe high-performance PRAGMAs in `get_db_connection()`.

---

### Audit Finding #5: Duplicate External Library Loading
* **Problem:** `xlsx.full.min.js` (SheetJS) is loaded twice in `static/index.html`.
* **File:** `static/index.html` (Lines 11 & 14)
* **Root Cause:** Local script tag `<script src="/static/xlsx.full.min.js"></script>` AND CDN `<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>` are both present.
* **Impact:** Redundant network request, double JS parsing/eval time, potential race conditions if offline.
* **Severity:** **MEDIUM**
* **Evidence:** Found both script tags in `static/index.html`.
* **Recommended Solution:** Remove the external CDN tag and rely on the local fast bundled asset.

---

### Audit Finding #6: Uncompressed 658 KB Payload Delivery
* **Problem:** The entire single-page frontend application (`index.html`) is 658 KB of uncompressed text.
* **File:** `main.py`
* **Root Cause:** FastAPI does not have `GZipMiddleware` enabled.
* **Impact:** Increased network transfer time and higher bandwidth consumption on local and network clients.
* **Severity:** **MEDIUM**
* **Evidence:** Measured baseline payload: 658,388 bytes transferred raw.
* **Recommended Solution:** Add `GZipMiddleware(app, minimum_size=1000)` to compress HTML/JSON/JS payloads (expected size reduction: ~80-85%).

---

### Audit Finding #7: Background Polling on Inactive Views
* **Problem:** Live Clock and Live Attendance dashboard intervals run continuously.
* **File:** `static/index.html`
* **Root Cause:** Inefficient polling without checking page visibility or tab active state.
* **Impact:** Battery drain, unnecessary CPU cycles when user is in other tabs or application is minimized.
* **Severity:** **LOW**
* **Recommended Solution:** Guard intervals with `document.hidden` check and tab active verification.
