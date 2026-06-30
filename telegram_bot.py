import os
import re
import time
import logging
import requests
from datetime import datetime

logger = logging.getLogger("website_tracker")

def escape_markdown_v2(text):
    """
    Escapes Telegram MarkdownV2 special characters.
    """
    if text is None:
        return ""
    # Characters that need escaping outside of code block and link URL targets
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', str(text))

def escape_link_url(url):
    """
    Escapes characters in MarkdownV2 link target URLs (backslash and closing parenthesis).
    """
    if not url:
        return ""
    return str(url).replace("\\", "\\\\").replace(")", "\\)")

def date_to_unix(date_str):
    """
    Parses various date string formats and returns a Unix timestamp.
    """
    if not date_str or date_str == "N/A":
        return None
    cleaned = date_str.strip()
    
    # 1. Extract date using regex
    # Match DD.MM.YYYY or DD-MM-YYYY or DD/MM/YYYY
    match_dmy = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", cleaned)
    if match_dmy:
        day, month, year = map(int, match_dmy.groups())
        try:
            dt = datetime(year, month, day)
            return int(dt.timestamp())
        except Exception:
            pass
            
    # Match YYYY-MM-DD or YYYY.MM.DD or YYYY/MM/DD
    match_ymd = re.search(r"(\d{4})[./-](\d{2})[./-](\d{2})", cleaned)
    if match_ymd:
        year, month, day = map(int, match_ymd.groups())
        try:
            dt = datetime(year, month, day)
            return int(dt.timestamp())
        except Exception:
            pass
            
    return None

def get_relative_date_string(date_str):
    """
    Computes relative date string from date_str (e.g. '3 days ago' or 'in 2 days').
    """
    ts = date_to_unix(date_str)
    if not ts:
        return ""
    
    try:
        # Calculate days difference
        target = datetime.fromtimestamp(ts)
        today = datetime.now()
        target_date = target.date()
        today_date = today.date()
        
        diff = (target_date - today_date).days
        
        if diff == 0:
            return "today"
        elif diff == 1:
            return "tomorrow"
        elif diff == -1:
            return "yesterday"
        elif diff > 1:
            return f"in {diff} days"
        else:
            return f"{abs(diff)} days ago"
    except Exception:
        return ""

def format_telegram_time(date_str, fallback="N/A"):
    """
    Formats a date string for Telegram, appending a natively computed relative date string.
    """
    if date_str and date_str != "N/A":
        escaped_date = escape_markdown_v2(date_str)
        relative = get_relative_date_string(date_str)
        if relative:
            escaped_relative = escape_markdown_v2(relative)
            return f"{escaped_date} \\({escaped_relative}\\)"
        return escaped_date
    return escape_markdown_v2(fallback)

def escape_code_span(text):
    """
    Escapes only backtick and backslash for code/pre entities in MarkdownV2.
    """
    if text is None:
        return ""
    return str(text).replace("\\", "\\\\").replace("`", "\\`")

class TelegramBot:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else None

    def is_configured(self):
        return bool(self.token and self.chat_id)

    def send_message(self, text, parse_mode="MarkdownV2"):
        """
        Sends a message to the configured Telegram chat.
        """
        if not self.is_configured():
            logger.warning("Telegram Bot is not configured. Skipping message. "
                           "(Provide TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
            return False

        # Fallback truncation: if still > 4096 despite raw caps, strip formatting and slice plain text
        if len(text) > 4096:
            logger.warning(f"Message length ({len(text)}) exceeds Telegram limit. Truncating and stripping formatting.")
            text = text[:4090] + "..."
            parse_mode = None

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            logger.info(f"Sending message to Telegram chat {self.chat_id}...")
            r = requests.post(url, json=payload, timeout=15)
            
            # Handle rate limiting (HTTP 429)
            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                logger.warning(f"Telegram rate limited. Retrying after {retry_after}s...")
                time.sleep(retry_after)
                r = requests.post(url, json=payload, timeout=15)

            # Fallback if MarkdownV2 entities fail to parse (HTTP 400 with 'can\'t parse entities')
            if r.status_code == 400 and "can't parse entities" in r.text:
                logger.warning("Telegram failed to parse MarkdownV2 entities. Retrying as plain text...")
                payload_fallback = payload.copy()
                payload_fallback.pop("parse_mode", None)
                r = requests.post(url, json=payload_fallback, timeout=15)

            if r.status_code == 200:
                logger.info("Telegram message sent successfully.")
                return True
            else:
                logger.error(f"Failed to send Telegram message. Status: {r.status_code}, Response: {r.text}")
                return False
        except Exception as e:
            logger.error(f"Error calling Telegram API: {e}")
            return False

    def format_kpsc_message(self, data):
        """
        Formats a Kerala PSC notification into a premium, rich Telegram MarkdownV2 message.
        """
        post_name = escape_code_span(data.get("post_name") or "N/A")
        category_number = escape_code_span(data.get("category_number") or "N/A")
        department = escape_code_span(data.get("department") or "N/A")
        pay_scale = escape_code_span(data.get("pay_scale") or "N/A")

        qualification_raw = data.get("qualification") or "N/A"
        if len(qualification_raw) > 1000:
            qualification_raw = qualification_raw[:1000] + "..."
        qualification = escape_markdown_v2(qualification_raw)
        
        age_limit_raw = data.get("age_limit") or "N/A"
        if len(age_limit_raw) > 1000:
            age_limit_raw = age_limit_raw[:1000] + "..."
        age_limit = escape_markdown_v2(age_limit_raw)
        
        last_date_str = data.get("last_date") or "N/A"
        last_date_display = format_telegram_time(last_date_str, last_date_str)
        
        pdf_url = escape_link_url(data.get("pdf_url"))
        notification_url = escape_link_url(data.get("notification_url"))
        
        pdf_link = f"[Download PDF Target]({pdf_url})" if pdf_url else "N/A"
        notif_link = f"[View Gazette page]({notification_url})" if notification_url else "N/A"

        msg = (
            "🔔 *NEW KERALA PSC NOTIFICATION*\n\n"
            f"📌 *Post:* `{post_name}`\n"
            f"🗂️ *Category No:* `{category_number}`\n"
            f"🏢 *Department:* `{department}`\n"
            f"💰 *Pay Scale:* `{pay_scale}`\n"
            f"📅 *Last Date:* {last_date_display}\n\n"
            f"⚙️ *Qualifications:*\n{qualification}\n\n"
            f"👤 *Age Limit:*\n{age_limit}\n\n"
            f"📥 *PDF:* {pdf_link}\n"
            f"🌐 *Source:* {notif_link}\n\n"
            "━━━━━━━━━━━━━━"
        )
        return msg

    def format_ugc_net_message(self, data):
        """
        Formats a UGC NET notice into a premium, rich Telegram MarkdownV2 message.
        """
        title = escape_code_span(data.get("title") or "N/A")
        examination_session = escape_code_span(data.get("examination_session") or "N/A")

        summary_raw = data.get("summary") or "N/A"
        if len(summary_raw) > 1500:
            summary_raw = summary_raw[:1500] + "..."
        summary = escape_markdown_v2(summary_raw)
        
        important_dates_raw = data.get("important_dates") or "N/A"
        if len(important_dates_raw) > 1000:
            important_dates_raw = important_dates_raw[:1000] + "..."
        important_dates = escape_markdown_v2(important_dates_raw)
        
        date_str = data.get("date") or "N/A"
        date_display = format_telegram_time(date_str, date_str)
        
        pdf_url = escape_link_url(data.get("pdf_url"))
        notice_url = escape_link_url(data.get("notice_url"))
        
        pdf_link = f"[Download Notice PDF]({pdf_url})" if pdf_url else "N/A"
        notice_link = f"[Visit NTA Portal]({notice_url})" if notice_url else "N/A"

        msg = (
            "🎓 *UGC NET OFFICIAL UPDATE*\n\n"
            f"📢 *Title:* `{title}`\n\n"
            f"📅 *Published:* {date_display}\n"
            f"🏫 *Session:* `{examination_session}`\n\n"
            f"📝 *Summary:*\n{summary}\n\n"
            f"⏱️ *Dates & Deadlines:*\n{important_dates}\n\n"
            f"📥 *PDF:* {pdf_link}\n"
            f"🌐 *Source:* {notice_link}\n\n"
            "━━━━━━━━━━━━━━"
        )
        return msg

    def format_hse_message(self, data):
        """
        Formats an HSE Kerala circular/notice into a premium, rich Telegram MarkdownV2 message.
        """
        title = escape_code_span(data.get("title") or "N/A")
        notice_type = escape_code_span(data.get("notice_type") or "N/A")
        ref_number = escape_code_span(data.get("ref_number") or "N/A")
        
        date_str = data.get("ref_date") or "N/A"
        date_display = format_telegram_time(date_str, date_str)
        
        pdf_url = escape_link_url(data.get("pdf_url"))
        notice_url = escape_link_url(data.get("notice_url"))
        
        pdf_link = f"[Download PDF Attachment]({pdf_url})" if pdf_url else "N/A"
        notice_link = f"[HSE Circulars page]({notice_url})" if notice_url else "N/A"

        msg = (
            "📢 *HSE KERALA CIRCULAR / NOTICE*\n\n"
            f"📌 *Title:* `{title}`\n"
            f"🏢 *Type:* `{notice_type}`\n"
            f"🗂️ *Ref Number:* `{ref_number}`\n"
            f"📅 *Ref Date:* {date_display}\n\n"
            f"📥 *PDF:* {pdf_link}\n"
            f"🌐 *Source:* {notice_link}\n\n"
            "━━━━━━━━━━━━━━"
        )
        return msg

