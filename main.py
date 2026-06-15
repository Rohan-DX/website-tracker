import os
import csv
import json
import logging
import hashlib
from datetime import datetime
from scraper import WebScraper
from pdf_parser import parse_kpsc_pdf, parse_ugc_net_pdf, download_pdf
from telegram_bot import TelegramBot

# Setup Logging
logger = logging.getLogger("website_tracker")
logger.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# Log file handler
log_file = "tracker.log"
fh = logging.FileHandler(log_file, encoding='utf-8')
fh.setFormatter(formatter)
logger.addHandler(fh)


def load_config():
    """
    Loads configuration from config.json.
    """
    config_path = "config.json"
    if not os.path.exists(config_path):
        logger.error(f"Configuration file {config_path} not found!")
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading config.json: {e}")
        return {}


def load_state():
    """
    Loads state from state.json.
    """
    state_path = "state.json"
    default_state = {
        "last_run": None,
        "daily_summary_sent_date": None,
        "seen_notifications": {}
    }
    if not os.path.exists(state_path):
        logger.info(f"State file {state_path} not found. Creating default state.")
        return default_state
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
            # Ensure required keys exist
            for key, val in default_state.items():
                if key not in state:
                    state[key] = val
            return state
    except Exception as e:
        logger.error(f"Error reading state.json: {e}. Reverting to default state.")
        return default_state


def save_state(state):
    """
    Saves state to state.json.
    """
    state_path = "state.json"
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        logger.info("state.json updated successfully.")
    except Exception as e:
        logger.error(f"Error writing state.json: {e}")


def append_to_csv(csv_path, timestamp, site_id, title, link, details_dict):
    """
    Appends a new notification record to a CSV file.
    """
    file_exists = os.path.exists(csv_path)
    
    # Flatten details dict into a readable string
    details_str = "; ".join([f"{k}: {v}" for k, v in details_dict.items() if v and v != "N/A"])
    
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                # Write header
                writer.writerow(["Timestamp", "Site ID", "Title", "Link", "Details"])
            writer.writerow([timestamp, site_id, title, link, details_str])
        logger.info(f"Notification appended to CSV: {csv_path}")
    except Exception as e:
        logger.error(f"Error appending to CSV: {e}")


def passes_keyword_filter(title, text_content, config_keywords):
    """
    Checks if a notification title and text match the include/exclude keyword filters.
    """
    if not config_keywords:
        return True
        
    include_kws = [k.lower() for k in config_keywords.get("include", []) if k.strip()]
    exclude_kws = [k.lower() for k in config_keywords.get("exclude", []) if k.strip()]
    
    combined_text = (title + " " + (text_content or "")).lower()
    
    # 1. Exclude check: reject if any exclude keyword is present
    for kw in exclude_kws:
        if kw in combined_text:
            logger.info(f"Skipping notification due to exclude keyword '{kw}': {title}")
            return False
            
    # 2. Include check: if include list is not empty, at least one must match
    if include_kws:
        matched = False
        for kw in include_kws:
            if kw in combined_text:
                matched = True
                break
        if not matched:
            logger.info(f"Skipping notification because it doesn't match any include keywords: {title}")
            return False
            
    return True


def get_notification_hash(title, link):
    """
    Generates a unique SHA256 hash for duplicate detection.
    """
    raw_str = f"{title}_{link or ''}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def run_daily_summary(state, config, bot):
    """
    Compiles and sends a daily summary of all notifications found since the last summary.
    """
    daily_summary_time_str = config.get("daily_summary_time", "18:00")
    try:
        summary_hour, summary_minute = map(int, daily_summary_time_str.split(":"))
    except Exception:
        summary_hour, summary_minute = 18, 0

    now = datetime.now()
    current_date_str = now.strftime("%Y-%m-%d")
    
    # Check if we already sent summary today
    if state.get("daily_summary_sent_date") == current_date_str:
        return

    # Check if current time is >= daily_summary_time
    if now.hour < summary_hour or (now.hour == summary_hour and now.minute < summary_minute):
        return

    logger.info("Executing Daily Summary checks...")
    
    # Collect notifications not yet summarized
    unsent_notifications = []
    seen_notifications = state.get("seen_notifications", {})
    
    for notif_hash, notif in seen_notifications.items():
        if not notif.get("sent_in_summary", False):
            unsent_notifications.append(notif)

    if not unsent_notifications:
        logger.info("No new notifications to summarize today.")
        state["daily_summary_sent_date"] = current_date_str
        return

    # Group by site
    grouped = {}
    for notif in unsent_notifications:
        site_id = notif.get("site_id", "Other")
        if site_id not in grouped:
            grouped[site_id] = []
        grouped[site_id].append(notif)

    # Format Summary Message
    from telegram_bot import escape_markdown_v2, escape_link_url
    
    date_display = now.strftime("%d %B %Y")
    summary_msg = f"📋 *Daily Digest \\- {escape_markdown_v2(date_display)}*\n\n"
    
    for site_id, items in grouped.items():
        site_name = escape_markdown_v2(site_id.upper().replace("_", " "))
        summary_msg += f"🔸 *{site_name}* \\({len(items)}\\):\n"
        for idx, item in enumerate(items[:10], 1): # Limit to 10 per site in summary to prevent message size limit
            title_esc = escape_markdown_v2(item.get("title", "N/A"))
            link_esc = escape_link_url(item.get("link", ""))
            if link_esc:
                summary_msg += f"{idx}\\. [{title_esc}]({link_esc})\n"
            else:
                summary_msg += f"{idx}\\. {title_esc}\n"
        if len(items) > 10:
            summary_msg += f"_\\+ {len(items) - 10} more notifications_\n"
        summary_msg += "\n"

    summary_msg += "━━━━━━━━━━━━━━"

    # Send message
    success = bot.send_message(summary_msg)
    if success:
        logger.info("Daily summary sent successfully.")
        # Mark all as sent
        for notif in unsent_notifications:
            notif["sent_in_summary"] = True
        state["daily_summary_sent_date"] = current_date_str
    else:
        logger.error("Failed to send daily summary. Will retry in next execution.")


def main():
    logger.info("--- Starting Website Tracker Execution ---")
    
    config = load_config()
    if not config:
        logger.error("Configuration empty or missing. Terminating.")
        return
        
    state = load_state()
    bot = TelegramBot()
    scraper = WebScraper(config)
    
    is_first_run = (not state["seen_notifications"])
    if is_first_run:
        logger.info("First run detected. State will be seeded without sending Telegram alerts.")
    elif not bot.is_configured():
        logger.warning("Telegram Telegram Bot credentials missing in environment variables.")

    # Track how many new notifications were processed in this run
    new_notifs_found = 0
    csv_path = config.get("csv_export_path", "notifications.csv")

    for site in config.get("websites", []):
        if not site.get("enabled", True):
            logger.info(f"Site {site['id']} is disabled. Skipping.")
            continue
            
        site_id = site["id"]
        site_type = site["type"]
        site_url = site["url"]
        
        logger.info(f"Processing site: {site['name']} ({site_id})")
        
        try:
            items = []
            if site_type == "kpsc_notifications":
                items = scraper.scrape_kpsc_notifications(site)
            elif site_type == "ugc_net":
                items = scraper.scrape_ugc_net(site)
            elif site_type == "hse_kerala":
                items = scraper.scrape_hse_kerala(site)
            elif site_type == "rss":
                items = scraper.scrape_rss_feed(site)
            else:
                items = scraper.scrape_generic_site(site)
                
            for item in items:
                # Standardize title and link for duplicate detection
                title = item.get("result_title") or item.get("title") or "N/A"
                link = item.get("result_link") or item.get("pdf_url") or item.get("link") or ""
                
                notif_hash = get_notification_hash(title, link)
                
                # Check if already processed
                if notif_hash in state["seen_notifications"]:
                    continue
                    
                # Generate timestamp
                timestamp = datetime.now().isoformat()
                
                # Setup seen state entry
                state["seen_notifications"][notif_hash] = {
                    "title": title,
                    "link": link,
                    "timestamp": timestamp,
                    "site_id": site_id,
                    "sent_in_summary": False
                }
                
                # Seeding logic: don't alert or parse PDFs on first run
                if is_first_run:
                    # Mark as already sent in summary so first-run items don't flood the daily summary either
                    state["seen_notifications"][notif_hash]["sent_in_summary"] = True
                    continue

                # Run PDF downloading and parsing if configured
                parsed_details = {}
                pdf_download_configured = site.get("pdf_download", False)
                pdf_url = item.get("pdf_url") or (link if link.lower().endswith(".pdf") else None)
                
                temp_pdf_path = None
                if pdf_download_configured and pdf_url:
                    temp_pdf_path = download_pdf(pdf_url, scraper.headers, scraper.timeout)
                
                # Extract text for keyword filters if PDF is available
                pdf_text = ""
                if temp_pdf_path:
                    # Import dynamically inside method call or helper
                    from pdf_parser import extract_text_from_pdf
                    pdf_text = extract_text_from_pdf(temp_pdf_path) or ""

                # Keyword filtering
                if not passes_keyword_filter(title, pdf_text, config.get("keywords")):
                    # Delete temp file if skipped
                    if temp_pdf_path and os.path.exists(temp_pdf_path):
                        os.remove(temp_pdf_path)
                    continue

                # Proceed with detailed PDF parsing
                if pdf_download_configured and pdf_url:
                    try:
                        if site_type == "kpsc_notifications":
                            parsed_details = parse_kpsc_pdf(temp_pdf_path, pdf_url, item.get("notification_url"))
                        elif site_type == "ugc_net":
                            parsed_details = parse_ugc_net_pdf(temp_pdf_path, title, pdf_url, item.get("notice_url"))
                    except Exception as e:
                        logger.error(f"Error parsing PDF fields: {e}")
                    finally:
                        # Clean up temp file
                        if temp_pdf_path and os.path.exists(temp_pdf_path):
                            os.remove(temp_pdf_path)
                            logger.debug(f"Removed temporary PDF file: {temp_pdf_path}")
                
                # Format Telegram Notification
                message_text = ""
                if site_type == "kpsc_notifications":
                    # Merge item details
                    kpsc_data = {
                        "post_name": title,
                        "pdf_url": pdf_url,
                        "notification_url": item.get("notification_url")
                    }
                    kpsc_data.update(parsed_details)
                    message_text = bot.format_kpsc_message(kpsc_data)
                elif site_type == "ugc_net":
                    ugc_data = {
                        "title": title,
                        "pdf_url": pdf_url,
                        "notice_url": item.get("notice_url")
                    }
                    ugc_data.update(parsed_details)
                    message_text = bot.format_ugc_net_message(ugc_data)
                elif site_type == "hse_kerala":
                    # Merge item details
                    hse_data = {
                        "title": title,
                        "pdf_url": pdf_url,
                        "notice_url": site_url
                    }
                    hse_data.update(item) # Includes notice_type, ref_date, ref_number
                    message_text = bot.format_hse_message(hse_data)
                else:
                    # Generic format
                    from telegram_bot import escape_markdown_v2, escape_link_url
                    escaped_title = escape_markdown_v2(title)
                    escaped_link = escape_link_url(link)
                    escaped_site_name = escape_markdown_v2(site["name"])
                    
                    message_text = (
                        f"📢 *New Update from {escaped_site_name}*\n\n"
                        f"{escaped_title}\n\n"
                        f"[Link]({escaped_link})" if escaped_link else ""
                    )

                # Send Alert
                logger.info(f"Sending Telegram Alert for notification: {title}")
                bot.send_message(message_text)
                
                # Export to CSV
                append_to_csv(csv_path, timestamp, site_id, title, link, parsed_details)
                new_notifs_found += 1
                
        except Exception as e:
            logger.error(f"Error processing website {site_id}: {e}", exc_info=True)
            # Proceed to next website
            continue

    # Save state
    state["last_run"] = datetime.now().isoformat()
    
    # Process Daily Summary
    if not is_first_run:
        run_daily_summary(state, config, bot)
        
    save_state(state)
    logger.info(f"--- Finished Execution. New notifications processed: {new_notifs_found} ---")


if __name__ == "__main__":
    main()
