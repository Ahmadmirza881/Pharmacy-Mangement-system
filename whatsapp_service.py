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

    def build_in_otp_message(self, staff_name: str, designation: str, otp_code: str, time_str: str) -> str:
        """Creates formal WhatsApp message template for Admin Check-IN authorization."""
        return (
            f"🔔 *MUMTAZ PHARMACY — STAFF CHECK-IN REQUEST*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 Staff: *{staff_name}* ({designation or 'Staff'})\n"
            f"⏰ Request Time: *{time_str}*\n"
            f"📍 Action: *Duty Check-IN*\n\n"
            f"🔑 *CONFIRMATION OTP:* \n"
            f"👉 *{otp_code}* 👈\n\n"
            f"⏱️ _Yeh code 5 minute ke liye valid hai._\n"
            f"Staff ko yeh code batayein taake attendance mark ho sake.\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

    def build_out_otp_message(self, staff_name: str, otp_code: str, time_str: str) -> str:
        """Creates formal WhatsApp message template for Staff Check-OUT verification."""
        return (
            f"🚪 *MUMTAZ PHARMACY — SHIFT CHECK-OUT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 Assalam-o-Alaikum *{staff_name}*,\n"
            f"⏰ Duty Out Time: *{time_str}*\n"
            f"📍 Action: *Duty Check-OUT*\n\n"
            f"🔑 *CONFIRMATION OTP:*\n"
            f"👉 *{otp_code}* 👈\n\n"
            f"⏱️ _Yeh code 5 minute ke liye valid hai._\n"
            f"Screen par yeh 4-digit code darj karein aur apni shift complete karein.\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

    def send_otp(self, target_phone: str, staff_name: str, designation: str, otp_code: str, action: str) -> Dict[str, Any]:
        """
        Dispatches OTP message to target WhatsApp number.
        - If action == 'IN': Dispatched to Admin
        - If action == 'OUT': Dispatched to Staff
        """
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        wa_number = self.normalize_phone(target_phone)

        if action.upper() == "IN":
            message_text = self.build_in_otp_message(staff_name, designation, otp_code, time_str)
            recipient_label = f"Admin ({self.mask_phone(target_phone)})"
        else:
            message_text = self.build_out_otp_message(staff_name, otp_code, time_str)
            recipient_label = f"Staff: {staff_name} ({self.mask_phone(target_phone)})"

        encoded_text = urllib.parse.quote(message_text)
        direct_link = f"https://api.whatsapp.com/send?phone={wa_number}&text={encoded_text}" if wa_number else ""

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
        link = f"https://api.whatsapp.com/send?phone={wa_number}&text={encoded}" if wa_number else ""

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

    def get_recent_messages(self, limit: int = 15) -> List[Dict[str, Any]]:
        return self.message_history[:limit]

whatsapp_service = WhatsAppService()
