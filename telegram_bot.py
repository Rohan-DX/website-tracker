import os
import re
import time
import logging
import requests
from datetime import datetime

logger = logging.getLogger("website_tracker")

import html

def escape_html(text):
    """
    Escapes HTML special characters for Telegram's HTML parse mode.
    """
    if text is None:
        return ""
    return html.escape(str(text))

# Backwards compatibility wrappers
def escape_markdown_v2(text):
    return escape_html(text)

def escape_link_url(url):
    if not url:
        return ""
    return str(url).replace("\"", "&quot;")

def escape_code_span(text):
    return escape_html(text)

def format_blockquote(text):
    """
    Formats the given text inside a Telegram HTML blockquote.
    """
    if not text:
        return ""
    return f"<blockquote>{text}</blockquote>"

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
    Formats a date string for Telegram HTML, appending a natively computed relative date string.
    Uses the new <tg-datetime> tag for rich dates if parseable.
    """
    if date_str and date_str != "N/A":
        escaped_date = escape_html(date_str)
        iso_date = ""
        ts = date_to_unix(date_str)
        if ts:
            try:
                iso_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except Exception:
                pass
        
        relative = get_relative_date_string(date_str)
        
        if iso_date:
            date_html = f'<tg-datetime datetime="{iso_date}">{escaped_date}</tg-datetime>'
        else:
            date_html = escaped_date
            
        if relative:
            escaped_relative = escape_html(relative)
            return f"{date_html} <i>({escaped_relative})</i>"
        return date_html
    return escape_html(fallback)

class TelegramBot:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else None

    def is_configured(self):
        return bool(self.token and self.chat_id)

    def send_message(self, text, parse_mode="HTML"):
        """
        Sends a message to the configured Telegram chat.
        Attempts to use sendRichMessage (HTML) for advanced rendering,
        falling back to legacy sendMessage (HTML) if unsupported or failed.
        """
        if not self.is_configured():
            logger.warning("Telegram Bot is not configured. Skipping message. "
                           "(Provide TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
            return False

        # Fallback truncation if too long for Rich Message (limit is 32,768 characters)
        if len(text) > 32768:
            logger.warning(f"Message length ({len(text)}) exceeds Telegram Rich Message limit. Truncating.")
            text = text[:32760] + "..."

        # 1. Attempt sendRichMessage (API 10.1+)
        url_rich = f"{self.base_url}/sendRichMessage"
        payload_rich = {
            "chat_id": self.chat_id,
            "rich_message": {
                "html": text
            }
        }
        
        try:
            logger.info(f"Attempting to send rich message via sendRichMessage to {self.chat_id}...")
            r = requests.post(url_rich, json=payload_rich, timeout=15)
            
            # Handle rate limiting (HTTP 429)
            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                logger.warning(f"Telegram rate limited. Retrying after {retry_after}s...")
                time.sleep(retry_after)
                r = requests.post(url_rich, json=payload_rich, timeout=15)
                
            if r.status_code == 200:
                logger.info("Telegram rich message sent successfully via sendRichMessage.")
                return True
            else:
                logger.warning(f"sendRichMessage failed (status {r.status_code}): {r.text}. Falling back to sendMessage HTML...")
        except Exception as e:
            logger.warning(f"Error calling sendRichMessage: {e}. Falling back to sendMessage HTML...")

        # 2. Fallback: Clean HTML text to use ONLY legacy supported HTML tags
        cleaned_text = text
        cleaned_text = cleaned_text.replace("<h3>", "<b>").replace("</h3>", "</b>\n")
        cleaned_text = cleaned_text.replace("<h4>", "<b>").replace("</h4>", "</b>\n")
        cleaned_text = cleaned_text.replace("<hr/>", "━━━━━━━━━━━━━━━━━━━━━━").replace("<hr>", "━━━━━━━━━━━━━━━━━━━━━━")
        cleaned_text = re.sub(r'<tg-datetime[^>]*>(.*?)</tg-datetime>', r'<b>\1</b>', cleaned_text)
        
        # Clean additional Rich HTML elements (sub, sup, mark, tables, and lists) for legacy rendering
        cleaned_text = cleaned_text.replace("<sub>", "(").replace("</sub>", ")")
        cleaned_text = cleaned_text.replace("<sup>", "^(").replace("</sup>", ")")
        cleaned_text = cleaned_text.replace("<mark>", "<b>").replace("</mark>", "</b>")
        cleaned_text = cleaned_text.replace("<ul>", "").replace("</ul>", "")
        cleaned_text = cleaned_text.replace("<ol>", "").replace("</ol>", "")
        cleaned_text = cleaned_text.replace("<li>", "• ").replace("</li>", "\n")
        
        if "<table>" in cleaned_text or "<table " in cleaned_text:
            cleaned_text = cleaned_text.replace("<table>", "").replace("</table>", "")
            cleaned_text = cleaned_text.replace("<thead>", "").replace("</thead>", "")
            cleaned_text = cleaned_text.replace("<tbody>", "").replace("</tbody>", "")
            cleaned_text = cleaned_text.replace("<tr>", "").replace("</tr>", "\n")
            cleaned_text = cleaned_text.replace("<th>", "<b>").replace("</th>", "</b> | ")
            cleaned_text = cleaned_text.replace("<td>", "").replace("</td>", " | ")
        
        if len(cleaned_text) > 4096:
            cleaned_text = cleaned_text[:4090] + "..."

        url_legacy = f"{self.base_url}/sendMessage"
        payload_legacy = {
            "chat_id": self.chat_id,
            "text": cleaned_text,
            "disable_web_page_preview": False,
            "parse_mode": "HTML"
        }

        try:
            logger.info("Sending message via legacy sendMessage HTML...")
            r = requests.post(url_legacy, json=payload_legacy, timeout=15)
            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(retry_after)
                r = requests.post(url_legacy, json=payload_legacy, timeout=15)

            # Fallback to plain text if still fails to parse
            if r.status_code == 400 and "can't parse entities" in r.text:
                logger.warning("Telegram failed to parse legacy HTML entities. Retrying as plain text...")
                payload_fallback = payload_legacy.copy()
                payload_fallback.pop("parse_mode", None)
                plain_text = re.sub(r'<[^>]*>', '', cleaned_text)
                payload_fallback["text"] = plain_text
                r = requests.post(url_legacy, json=payload_fallback, timeout=15)

            if r.status_code == 200:
                logger.info("Telegram message sent successfully via legacy fallback.")
                return True
            else:
                logger.error(f"Failed to send Telegram message. Status: {r.status_code}, Response: {r.text}")
                return False
        except Exception as e:
            logger.error(f"Error calling legacy Telegram API: {e}")
            return False

    def format_kpsc_message(self, data):
        """
        Formats a Kerala PSC notification into a premium, HTML Telegram message.
        """
        post_name = escape_code_span(data.get("post_name") or "N/A")
        category_number = escape_code_span(data.get("category_number") or "N/A")
        department = escape_code_span(data.get("department") or "N/A")
        pay_scale = escape_code_span(data.get("pay_scale") or "N/A")

        qualification_raw = data.get("qualification") or "N/A"
        if len(qualification_raw) > 1000:
            qualification_raw = qualification_raw[:1000] + "..."
        qualification = format_blockquote(escape_html(qualification_raw))
        
        age_limit_raw = data.get("age_limit") or "N/A"
        if len(age_limit_raw) > 1000:
            age_limit_raw = age_limit_raw[:1000] + "..."
        age_limit = format_blockquote(escape_html(age_limit_raw))
        
        last_date_str = data.get("last_date") or "N/A"
        last_date_display = format_telegram_time(last_date_str, last_date_str)
        
        pdf_url = data.get("pdf_url")
        notification_url = data.get("notification_url")
        
        pdf_link = f'<a href="{pdf_url}">Download PDF</a>' if pdf_url else "N/A"
        notif_link = f'<a href="{notification_url}">View Gazette Page</a>' if notification_url else "N/A"

        msg = (
            "<h3>🔔 NEW KERALA PSC NOTIFICATION</h3>\n"
            "<hr/>\n"
            f"📌 <b>Post:</b> <code>{post_name}</code>\n"
            f"🗂️ <b>Category No:</b> <code>{category_number}</code>\n"
            f"🏢 <b>Department:</b> <code>{department}</code>\n"
            f"💰 <b>Pay Scale:</b> <code>{pay_scale}</code>\n"
            f"📅 <b>Last Date:</b> {last_date_display}\n\n"
            f"<h4>⚙️ Qualifications</h4>\n{qualification}\n\n"
            f"<h4>👤 Age Limit</h4>\n{age_limit}\n\n"
            "<h4>🔗 Quick Links</h4>\n"
            f"📥 {pdf_link}\n"
            f"🌐 {notif_link}\n"
            "<hr/>"
        )
        return msg

    def format_ugc_net_message(self, data):
        """
        Formats a UGC NET notice into a premium, HTML Telegram message.
        """
        title = escape_code_span(data.get("title") or "N/A")
        examination_session = escape_code_span(data.get("examination_session") or "N/A")

        summary_raw = data.get("summary") or "N/A"
        if len(summary_raw) > 1500:
            summary_raw = summary_raw[:1500] + "..."
        summary = format_blockquote(escape_html(summary_raw))
        
        important_dates_raw = data.get("important_dates") or "N/A"
        if len(important_dates_raw) > 1000:
            important_dates_raw = important_dates_raw[:1000] + "..."
        important_dates = format_blockquote(escape_html(important_dates_raw))
        
        date_str = data.get("date") or "N/A"
        date_display = format_telegram_time(date_str, date_str)
        
        pdf_url = data.get("pdf_url")
        notice_url = data.get("notice_url")
        
        pdf_link = f'<a href="{pdf_url}">Download Notice PDF</a>' if pdf_url else "N/A"
        notice_link = f'<a href="{notice_url}">Visit NTA Portal</a>' if notice_url else "N/A"

        msg = (
            "<h3>🎓 UGC NET OFFICIAL UPDATE</h3>\n"
            "<hr/>\n"
            f"📢 <b>Title:</b> <code>{title}</code>\n"
            f"🏫 <b>Session:</b> <code>{examination_session}</code>\n"
            f"📅 <b>Published:</b> {date_display}\n\n"
            f"<h4>📝 Summary</h4>\n{summary}\n\n"
            f"<h4>⏱️ Dates & Deadlines</h4>\n{important_dates}\n\n"
            "<h4>🔗 Quick Links</h4>\n"
            f"📥 {pdf_link}\n"
            f"🌐 {notice_link}\n"
            "<hr/>"
        )
        return msg

    def format_hse_message(self, data):
        """
        Formats an HSE Kerala circular/notice into a premium, HTML Telegram message.
        """
        title = escape_code_span(data.get("title") or "N/A")
        notice_type = escape_code_span(data.get("notice_type") or "N/A")
        ref_number = escape_code_span(data.get("ref_number") or "N/A")
        
        date_str = data.get("ref_date") or "N/A"
        date_display = format_telegram_time(date_str, date_str)
        
        pdf_url = data.get("pdf_url")
        notice_url = data.get("notice_url")
        
        pdf_link = f'<a href="{pdf_url}">Download PDF Attachment</a>' if pdf_url else "N/A"
        notice_link = f'<a href="{notice_url}">HSE Circulars Page</a>' if notice_url else "N/A"

        msg = (
            "<h3>📢 HSE KERALA CIRCULAR / NOTICE</h3>\n"
            "<hr/>\n"
            f"📌 <b>Title:</b> <code>{title}</code>\n"
            f"🏢 <b>Type:</b> <code>{notice_type}</code>\n"
            f"🗂️ <b>Ref Number:</b> <code>{ref_number}</code>\n"
            f"📅 <b>Ref Date:</b> {date_display}\n\n"
            "<h4>🔗 Quick Links</h4>\n"
            f"📥 {pdf_link}\n"
            f"🌐 {notice_link}\n"
            "<hr/>"
        )
        return msg

