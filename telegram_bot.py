import os
import re
import logging
import requests

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

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }

        try:
            logger.info(f"Sending message to Telegram chat {self.chat_id}...")
            r = requests.post(url, json=payload, timeout=15)
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
        post_name = escape_markdown_v2(data.get("post_name") or "N/A")
        category_number = escape_markdown_v2(data.get("category_number") or "N/A")
        department = escape_markdown_v2(data.get("department") or "N/A")
        qualification = escape_markdown_v2(data.get("qualification") or "N/A")
        age_limit = escape_markdown_v2(data.get("age_limit") or "N/A")
        pay_scale = escape_markdown_v2(data.get("pay_scale") or "N/A")
        last_date = escape_markdown_v2(data.get("last_date") or "N/A")
        
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
            f"📅 *Last Date:* `{last_date}`\n\n"
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
        title = escape_markdown_v2(data.get("title") or "N/A")
        date = escape_markdown_v2(data.get("date") or "N/A")
        summary = escape_markdown_v2(data.get("summary") or "N/A")
        important_dates = escape_markdown_v2(data.get("important_dates") or "N/A")
        examination_session = escape_markdown_v2(data.get("examination_session") or "N/A")
        
        pdf_url = escape_link_url(data.get("pdf_url"))
        notice_url = escape_link_url(data.get("notice_url"))
        
        pdf_link = f"[Download Notice PDF]({pdf_url})" if pdf_url else "N/A"
        notice_link = f"[Visit NTA Portal]({notice_url})" if notice_url else "N/A"

        msg = (
            "🎓 *UGC NET OFFICIAL UPDATE*\n\n"
            f"📢 *Title:* `{title}`\n\n"
            f"📅 *Published:* `{date}`\n"
            f"🏫 *Session:* `{examination_session}`\n\n"
            f"📝 *Summary:*\n{summary}\n\n"
            f"⏱️ *Dates & Deadlines:*\n{important_dates}\n\n"
            f"📥 *PDF:* {pdf_link}\n"
            f"🌐 *Source:* {notice_link}\n\n"
            "━━━━━━━━━━━━━━"
        )
        return msg
