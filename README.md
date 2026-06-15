# Website Notification Monitor & Telegram Alerter

A production-ready, modular, and config-driven Python system to monitor government and university websites for new announcements, results, or notifications, parse PDFs, and send detailed alerts to a Telegram channel.

It runs entirely on free tier services utilizing **GitHub Actions** for scheduling (every 15 minutes) and state management.

---

## Features

- **Multi-Site Monitoring**: Monitors MGU Results, Kerala PSC Notifications, and UGC NET Public Notices out-of-the-box.
- **Dynamic Scrapers**: Support for MGU Old Result portal, KPSC Gazette/Notifications, UGC NET announcements, RSS feeds, and generic sites.
- **Smart PDF Processing**: Downloads notice PDFs and extracts metadata fields (like Category, Post Name, Deadlines, and Pay Scales) using `pdfplumber` with fallback to `PyMuPDF`.
- **Scanned PDF Support**: Handles scanned UGC NET PDFs elegantly by fallback parsing of date/session metadata from titles and upload URL structures.
- **Telegram Channel Integration**: Formats beautiful alerts using Telegram's MarkdownV2 syntax with a robust regex-based escaping layer to avoid API crashes.
- **Daily Digest Summary**: Sends a consolidated summary of all new notifications found in the last 24 hours at a configurable summary time.
- **CSV Data Export**: Automatically logs all detected notifications to a queryable `notifications.csv` archive.
- **Keyword Filtering**: Support for global include and exclude keyword filtering defined in `config.json`.
- **Duplicate Prevention**: State-tracking in `state.json` via SHA256 hashes of the notification title and link.
- **Anti-Spam State Seeding**: On the initial run, the system seeds existing notifications to the state database without triggering alerts, protecting Telegram rate limits from historical results.

---

## File Structure

```
project/
│
├── main.py                # System entrypoint, orchestrates scraping and alert dispatch
├── scraper.py             # Scraping modules for MGU, KPSC, UGC NET, RSS, and generic pages
├── telegram_bot.py        # Telegram Bot API client and message formatting engine
├── pdf_parser.py          # PDF text extraction and regex field extraction logic
├── config.json            # Configuration file for targets, keywords, and timeouts
├── state.json             # State file tracking seen notifications and run times
├── requirements.txt       # Python dependencies
├── README.md              # Installation and deployment documentation
└── .github/
    └── workflows/
        └── monitor.yml    # GitHub Actions workflow for scheduling and state sync
```

---

## Setup & Configuration

### `config.json` options

Add more sites by modifying `config.json`. For example:

```json
{
  "user_agent": "Mozilla/5.0 ...",
  "request_timeout_seconds": 15,
  "max_retries": 3,
  "retry_backoff_factor": 2,
  "daily_summary_time": "18:00",
  "csv_export_path": "notifications.csv",
  "keywords": {
    "include": ["engineer", "officer"],
    "exclude": ["archives", "helper"]
  },
  "websites": [
    {
      "id": "my_new_site",
      "name": "My Custom Portal",
      "url": "https://example.com/notices",
      "type": "generic",
      "enabled": true,
      "pdf_download": false
    }
  ]
}
```

Available `type` attributes:
- `mgu_results` (MG University specific parsing)
- `kpsc_notifications` (Kerala PSC Gazette and PDF parsing)
- `ugc_net` (UGC NET Notice board and scanned PDF fallback)
- `rss` (Generic RSS feed parser)
- `generic` (Standard page link extractor)

---

## Deploying to GitHub Actions (Free)

1. **Create a Private/Public Repository**: Push this directory to GitHub.
2. **Setup Telegram Bot**:
   - Create a Bot on Telegram via [@BotFather](https://t.me/BotFather) and copy the **HTTP Bot Token**.
   - Create a channel or group and add the bot as an Admin.
   - Send a test message and get your Chat ID (e.g. using `https://api.telegram.org/bot<TOKEN>/getUpdates` or [@userinfobot](https://t.me/userinfobot)).
3. **Configure Secrets**:
   - Go to your GitHub Repository -> **Settings** -> **Secrets and variables** -> **Actions**.
   - Add the following Repository Secrets:
     - `TELEGRAM_BOT_TOKEN`: Your bot HTTP token.
     - `TELEGRAM_CHAT_ID`: Your chat or channel ID.
4. **Enable Actions Permissions**:
   - Go to **Settings** -> **Actions** -> **General** -> **Workflow permissions**.
   - Select **Read and write permissions** (needed so the runner can commit back the updated `state.json` and `notifications.csv`).
5. **Run**: The workflow will automatically run every 15 minutes, or you can run it manually via the **Actions** tab.

---

## Local Development & Testing

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   # On Windows:
   $env:TELEGRAM_BOT_TOKEN="your_bot_token"
   $env:TELEGRAM_CHAT_ID="your_chat_id"
   
   # On Linux/macOS:
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

3. Run the program:
   ```bash
   python main.py
   ```
