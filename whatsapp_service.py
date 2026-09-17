"""
Mumtaz Pharmacy - WhatsApp Notification & OTP Dispatcher Engine
100% Free messaging service for Staff PIN attendance verification.
Handles:
- Check-IN OTP delivery to Admin WhatsApp Number
- Check-OUT OTP delivery to Staff WhatsApp Number
- Pakistani number normalization (0300xxxxxxx -> 92300xxxxxxx)
- Live message logging and in-memory recent alerts buffer
"""

import re
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List

class WhatsAppService:
    def __init__(self):
        self.service_name = "Mumtaz Pharmacy WhatsApp Dispatcher"
        self.status = "ONLINE"
        # Keeps last 50 dispatched messages in memory for UI feed & audit
        self.message_history: List[Dict[str, Any]] = []

    def normalize_phone(self, phone: Optional[str]) -> str:
        """Converts local Pakistani numbers (03xx / +923xx) to clean 923xxxxxxxxx format."""
        if not phone:
            return ""
        digits = re.sub(r'[^0-9]', '', str(phone))
        if digits.startswith('03') and len(digits) == 11:
            return '92' + digits[1:]
        elif digits.startswith('3') and len(digits) == 10:
            return '92' + digits
        elif digits.startswith('92') and len(digits) == 12:
            return digits
        elif digits.startswith('0092') and len(digits) == 14:
            return digits[2:]
        return digits

    def mask_phone(self, phone: Optional[str]) -> str:
        """Masks middle digits for friendly UI display, e.g. 0300-***-4567."""
        if not phone:
            return "Unknown"
        clean = re.sub(r'[^0-9]', '', str(phone))
        if len(clean) >= 10:
            return f"{clean[:4]}-***-{clean[-4:]}"
        return phone

    def get_local_ip(self) -> str:
        """Auto-detects local Wi-Fi / LAN IP address of the pharmacy machine."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def shorten_url(self, url: str) -> str:
        """Converts raw local IP links (e.g. http://192.168.x.x:8000/...) into clickable short links (tinyurl)."""
        if not url:
            return ""
        try:
            import urllib.request
            encoded_url = urllib.parse.quote(url, safe='')
            api_url = f"https://tinyurl.com/api-create.php?url={encoded_url}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "MumtazPharmacy/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                short = resp.read().decode('utf-8').strip()
                if short.startswith("http"):
                    return short
        except Exception:
            pass
        return url

    def build_in_otp_message(self, staff_name: str, designation: str, time_str: str, reveal_link: str = "", otp_code: str = "") -> str:
        """Creates formal WhatsApp message template for Admin Check-IN authorization via secure link."""
        if reveal_link:
            link_block = (
                f"👉 *GET OTP & APPROVE (Tap Secure Link):*\n"
                f"{reveal_link}\n\n"
                f"🛡️ _Link khol kar apna Admin Password darj karein taake OTP unlock ho._\n"
            )
            otp_block = ""
        else:
            link_block = ""
            otp_block = f"🔑 *Instant OTP Code:* *{otp_code}*\n" if otp_code else ""

        return (
            f"🔔 *MUMTAZ PHARMACY — STAFF CHECK-IN REQUEST*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Staff: *{staff_name}* ({designation or 'Staff'})\n"
            f"⏰ Request Time: *{time_str}*\n"
            f"📍 Action: *Duty Check-IN*\n\n"
            f"{link_block}"
            f"{otp_block}"
            f"⏱️ _Yeh link 5 minute ke liye valid hai._\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

    def build_out_otp_message(self, staff_name: str, designation: str, time_str: str, reveal_link: str = "", otp_code: str = "") -> str:
        """Creates formal WhatsApp message template for Admin Check-OUT authorization via secure link."""
        if reveal_link:
            link_block = (
                f"👉 *GET OTP & APPROVE (Tap Secure Link):*\n"
                f"{reveal_link}\n\n"
                f"🛡️ _Link khol kar apna Admin Password darj karein taake OTP unlock ho._\n"
            )
            otp_block = ""
        else:
            link_block = ""
            otp_block = f"🔑 *Instant OTP Code:* *{otp_code}*\n" if otp_code else ""

        return (
            f"🔔 *MUMTAZ PHARMACY — STAFF CHECK-OUT REQUEST*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Staff: *{staff_name}* ({designation or 'Staff'})\n"
            f"⏰ Request Time: *{time_str}*\n"
            f"📍 Action: *Duty Check-OUT*\n\n"
            f"{link_block}"
            f"{otp_block}"
            f"⏱️ _Yeh link 5 minute ke liye valid hai._\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

    def send_otp(self, target_phone: str, staff_name: str, designation: str, otp_code: str, action: str, reveal_link: str = "") -> Dict[str, Any]:
        """
        Dispatches OTP message to Admin's WhatsApp number with secure reveal link.
        Supports both Check-IN and Check-OUT requests.
        """
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        wa_number = self.normalize_phone(target_phone)

        clean_link = self.shorten_url(reveal_link) if reveal_link else ""
        if action.upper() == "IN":
            message_text = self.build_in_otp_message(staff_name, designation, time_str, reveal_link=clean_link, otp_code=otp_code)
        else:
            message_text = self.build_out_otp_message(staff_name, designation, time_str, reveal_link=clean_link, otp_code=otp_code)

        recipient_label = f"Admin ({self.mask_phone(target_phone)})"

        encoded_text = urllib.parse.quote(message_text)
        direct_link = f"https://wa.me/{wa_number}?text={encoded_text}" if wa_number else ""

        entry = {
            "id": len(self.message_history) + 1,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time_label": time_str,
            "action": action.upper(),
            "staff_name": staff_name,
            "target_phone": target_phone,
            "wa_number": wa_number,
            "masked_phone": self.mask_phone(target_phone),
            "recipient_label": recipient_label,
            "otp_code": otp_code,
            "reveal_link": reveal_link,
            "message_text": message_text,
            "direct_link": direct_link,
            "status": "SENT"
        }

        self.message_history.insert(0, entry)
        if len(self.message_history) > 50:
            self.message_history = self.message_history[:50]

        log_summary = f"[WHATSAPP-DISPATCH] -> To {recipient_label} | OTP: {otp_code} | Action: {action.upper()}"
        try:
            print(f"\n{log_summary}\n{message_text}\n")
        except Exception:
            print(f"\n{log_summary}\n{message_text.encode('ascii', 'replace').decode('ascii')}\n")
        return entry

    def send_test_message(self, phone: str, custom_text: str = None) -> Dict[str, Any]:
        """Sends a test WhatsApp message to verify number configuration."""
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        wa_number = self.normalize_phone(phone)
        text = custom_text or (
            f"✅ *MUMTAZ PHARMACY — WHATSAPP TEST ALERT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Aapka WhatsApp notification system kamiyabi se connect ho gaya hai.\n"
            f"Tamam Staff Check-IN confirmation codes isi number par aayenge.\n"
            f"⏰ Time: *{time_str}*\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

        encoded = urllib.parse.quote(text)
        link = f"https://wa.me/{wa_number}?text={encoded}" if wa_number else ""

        entry = {
            "id": len(self.message_history) + 1,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time_label": time_str,
            "action": "TEST",
            "staff_name": "Admin",
            "target_phone": phone,
            "wa_number": wa_number,
            "masked_phone": self.mask_phone(phone),
            "recipient_label": f"Admin ({self.mask_phone(phone)})",
            "otp_code": "TEST",
            "message_text": text,
            "direct_link": link,
            "status": "SENT"
        }
        self.message_history.insert(0, entry)
        return entry

    def _safe_format(self, template_str: str, values: Dict[str, Any]) -> str:
        res = template_str
        for k, v in values.items():
            res = res.replace(f"{{{k}}}", str(v))
        return res

    def build_delivery_dispatch_admin_message(self, delivery: Dict[str, Any]) -> str:
        """Formal WhatsApp message for Admin when order is dispatched."""
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        invoice = delivery.get("invoice_no", "N/A")
        cust_name = delivery.get("customer_name", "Customer")
        cust_phone = delivery.get("customer_phone", "")
        address = delivery.get("customer_address") or delivery.get("delivery_address") or ""
        raw_amt = delivery.get("bill_amount") if delivery.get("bill_amount") is not None else delivery.get("total_amount", 0.0)
        amount = float(raw_amt or 0.0)
        payment_method = delivery.get("payment_method", "Cash on Delivery")
        rider = delivery.get("delivery_person_name") or delivery.get("rider_name") or "Rider"
        rider_phone = delivery.get("delivery_person_phone") or delivery.get("rider_phone") or ""
        notes = (delivery.get("notes") or "").strip()
        notes_str = f"📝 *Notes:* {notes}\n" if notes else ""

        try:
            from database import get_delivery_wa_templates
            tmpl = get_delivery_wa_templates().get("admin_dispatch")
        except Exception:
            tmpl = None

        if tmpl:
            return self._safe_format(tmpl, {
                "invoice": invoice,
                "customer_name": cust_name,
                "customer_phone": cust_phone,
                "address": address,
                "amount": f"{amount:,.0f}",
                "payment_method": payment_method,
                "rider_name": rider,
                "rider_phone": rider_phone,
                "time": time_str,
                "notes": notes_str
            })

        return (
            f"🚀 *MUMTAZ PHARMACY — ORDER DISPATCHED*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Invoice:* #{invoice}\n"
            f"💰 *Bill Amount:* Rs. {amount:,.0f} ({payment_method})\n"
            f"👤 *Customer:* {cust_name} ({cust_phone})\n"
            f"📍 *Address:* {address}\n"
            f"🛵 *Rider:* {rider} ({rider_phone})\n"
            f"⏰ *Dispatched At:* {time_str}\n"
            f"{notes_str}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Admin Audit:* Operational OUT_FOR_DELIVERY • Pending End-of-Day cash reconciliation."
        )

    def build_delivery_dispatch_customer_message(self, delivery: Dict[str, Any]) -> str:
        """Formal WhatsApp message for Customer when order is on the way."""
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        cust_name = delivery.get("customer_name", "Valued Customer")
        invoice = delivery.get("invoice_no", "N/A")
        cust_phone = delivery.get("customer_phone", "")
        address = delivery.get("customer_address") or delivery.get("delivery_address") or ""
        raw_amt = delivery.get("bill_amount") if delivery.get("bill_amount") is not None else delivery.get("total_amount", 0.0)
        amount = float(raw_amt or 0.0)
        payment_method = delivery.get("payment_method", "Cash on Delivery")
        rider = delivery.get("delivery_person_name") or delivery.get("rider_name") or "Rider"
        rider_phone = delivery.get("delivery_person_phone") or delivery.get("rider_phone") or ""
        notes = (delivery.get("notes") or "").strip()
        notes_str = f"📝 *Notes:* {notes}\n" if notes else ""

        try:
            from database import get_delivery_wa_templates
            tmpl = get_delivery_wa_templates().get("customer_dispatch")
        except Exception:
            tmpl = None

        if tmpl:
            return self._safe_format(tmpl, {
                "invoice": invoice,
                "customer_name": cust_name,
                "customer_phone": cust_phone,
                "address": address,
                "amount": f"{amount:,.0f}",
                "payment_method": payment_method,
                "rider_name": rider,
                "rider_phone": rider_phone,
                "time": time_str,
                "notes": notes_str
            })

        return (
            f"📦 *MUMTAZ PHARMACY — YOUR ORDER IS ON THE WAY!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dear *{cust_name}*,\n"
            f"Your medicine / pharmacy order has been dispatched.\n\n"
            f"🧾 *Invoice:* #{invoice}\n"
            f"💰 *Amount Payable:* Rs. {amount:,.0f} ({payment_method})\n"
            f"🛵 *Delivery Rider:* {rider}\n"
            f"📞 *Rider Contact:* {rider_phone}\n\n"
            f"Our rider will arrive shortly. Please have the exact cash ready if paying on delivery.\n"
            f"Thank you for choosing Mumtaz Pharmacy! 🏥\n"
            f"📍 Model Town, Lahore"
        )

    def build_delivery_return_admin_message(self, delivery: Dict[str, Any]) -> str:
        """Formal WhatsApp message for Admin when rider confirms return."""
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        invoice = delivery.get("invoice_no", "N/A")
        cust_name = delivery.get("customer_name", "Customer")
        cust_phone = delivery.get("customer_phone", "")
        address = delivery.get("customer_address") or delivery.get("delivery_address") or ""
        raw_amt = delivery.get("bill_amount") if delivery.get("bill_amount") is not None else delivery.get("total_amount", 0.0)
        amount = float(raw_amt or 0.0)
        payment_method = delivery.get("payment_method", "Cash on Delivery")
        rider = delivery.get("delivery_person_name") or delivery.get("rider_name") or "Rider"
        rider_phone = delivery.get("delivery_person_phone") or delivery.get("rider_phone") or ""

        try:
            from database import get_delivery_wa_templates
            tmpl = get_delivery_wa_templates().get("admin_return")
        except Exception:
            tmpl = None

        if tmpl:
            return self._safe_format(tmpl, {
                "invoice": invoice,
                "customer_name": cust_name,
                "customer_phone": cust_phone,
                "address": address,
                "amount": f"{amount:,.0f}",
                "payment_method": payment_method,
                "rider_name": rider,
                "rider_phone": rider_phone,
                "time": time_str
            })

        res_type = delivery.get("delivery_result") or ("RETURNED" if delivery.get("status") == "RETURNED" else "DELIVERED")
        is_delivered = (res_type == "DELIVERED")
        status_header = "✅ *MUMTAZ PHARMACY — DELIVERY COMPLETED*" if is_delivered else "❌ *MUMTAZ PHARMACY — ORDER RETURNED*"

        delivery_charges = float(delivery.get("delivery_charges") or 0.0)
        paid_amt = float(delivery.get("paid_amount") or (amount if is_delivered else 0.0))
        bal_amt = float(delivery.get("balance_amount") or 0.0)
        pay_status = delivery.get("payment_status", "FULL")
        ret_reason = delivery.get("return_reason", "")

        msg = (
            f"{status_header}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Invoice:* #{invoice}\n"
            f"🛵 *Rider:* {rider} ({rider_phone})\n"
            f"👤 *Customer:* {cust_name} ({cust_phone})\n"
            f"📍 *Address:* {address}\n"
            f"💵 *Medicine Bill:* Rs. {amount:,.0f}\n"
            f"🚚 *Delivery Charges:* Rs. {delivery_charges:,.0f}\n"
            f"💰 *Net Total:* Rs. {(amount + delivery_charges):,.0f}\n"
        )
        if is_delivered:
            msg += (
                f"💳 *Payment Method:* {payment_method}\n"
                f"📊 *Payment Status:* {pay_status} (Paid: Rs. {paid_amt:,.0f} | Remaining: Rs. {bal_amt:,.0f})\n"
            )
        else:
            msg += f"⚠️ *Return Reason:* {ret_reason}\n"

        msg += (
            f"⏰ *Return Time:* {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Action Required:* Please verify hisaab in Admin Portal."
        )
        return msg

    def dispatch_delivery_alerts(self, delivery: Dict[str, Any], admin_phone: str = "") -> Dict[str, Any]:
        """Dispatches dispatch alerts for both Admin and Customer and returns WhatsApp direct links."""
        admin_text = self.build_delivery_dispatch_admin_message(delivery)
        cust_text = self.build_delivery_dispatch_customer_message(delivery)
        
        adm_wa = self.normalize_phone(admin_phone)
        cust_wa = self.normalize_phone(delivery.get("customer_phone", ""))

        adm_link = f"https://wa.me/{adm_wa}?text={urllib.parse.quote(admin_text)}" if adm_wa else ""
        cust_link = f"https://wa.me/{cust_wa}?text={urllib.parse.quote(cust_text)}" if cust_wa else ""

        now = datetime.now()
        if adm_link:
            self.message_history.insert(0, {
                "id": len(self.message_history) + 1,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "time_label": now.strftime("%I:%M %p"),
                "action": "DELIVERY_DISPATCH_ADMIN",
                "staff_name": delivery.get("delivery_person_name", "Rider"),
                "target_phone": admin_phone,
                "wa_number": adm_wa,
                "masked_phone": self.mask_phone(admin_phone),
                "recipient_label": f"Admin ({self.mask_phone(admin_phone)})",
                "otp_code": f"INV-{delivery.get('invoice_no')}",
                "message_text": admin_text,
                "direct_link": adm_link,
                "status": "SENT"
            })
        if cust_link:
            self.message_history.insert(0, {
                "id": len(self.message_history) + 1,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "time_label": now.strftime("%I:%M %p"),
                "action": "DELIVERY_DISPATCH_CUSTOMER",
                "staff_name": delivery.get("customer_name", "Customer"),
                "target_phone": delivery.get("customer_phone", ""),
                "wa_number": cust_wa,
                "masked_phone": self.mask_phone(delivery.get("customer_phone", "")),
                "recipient_label": f"Customer ({self.mask_phone(delivery.get('customer_phone', ''))})",
                "otp_code": f"INV-{delivery.get('invoice_no')}",
                "message_text": cust_text,
                "direct_link": cust_link,
                "status": "SENT"
            })
        
        if len(self.message_history) > 50:
            self.message_history = self.message_history[:50]

        return {
            "admin_message": admin_text,
            "admin_link": adm_link,
            "customer_message": cust_text,
            "customer_link": cust_link
        }

    def dispatch_delivery_return_alert(self, delivery: Dict[str, Any], admin_phone: str = "") -> Dict[str, Any]:
        """Dispatches return alert to Admin and returns direct WhatsApp link."""
        return_text = self.build_delivery_return_admin_message(delivery)
        adm_wa = self.normalize_phone(admin_phone)
        adm_link = f"https://wa.me/{adm_wa}?text={urllib.parse.quote(return_text)}" if adm_wa else ""

        now = datetime.now()
        if adm_link:
            self.message_history.insert(0, {
                "id": len(self.message_history) + 1,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "time_label": now.strftime("%I:%M %p"),
                "action": "DELIVERY_RETURN_ADMIN",
                "staff_name": delivery.get("delivery_person_name", "Rider"),
                "target_phone": admin_phone,
                "wa_number": adm_wa,
                "masked_phone": self.mask_phone(admin_phone),
                "recipient_label": f"Admin ({self.mask_phone(admin_phone)})",
                "otp_code": f"INV-{delivery.get('invoice_no')}",
                "message_text": return_text,
                "direct_link": adm_link,
                "status": "SENT"
            })
        if len(self.message_history) > 50:
            self.message_history = self.message_history[:50]

        return {
            "admin_message": return_text,
            "admin_link": adm_link
        }

    def get_recent_messages(self, limit: int = 15) -> List[Dict[str, Any]]:
        return self.message_history[:limit]

whatsapp_service = WhatsAppService()
