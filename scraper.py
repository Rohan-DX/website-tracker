import re
import time
import logging
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

logger = logging.getLogger("website_tracker")

def fetch_url_with_retries(url, headers, timeout=15, max_retries=3, backoff_factor=2):
    """
    Fetches a URL using requests with exponential backoff retries for transient errors.
    """
    last_exception = None
    # Disable SSL verification warnings for insecure university portals
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Fetching URL: {url} (Attempt {attempt}/{max_retries})")
            # verify=False is needed for some government/university portals with expired SSL certs
            response = requests.get(url, headers=headers, timeout=timeout, verify=False)
            
            # Treat 5xx server errors as transient and retry
            if response.status_code >= 500:
                logger.warning(f"Server error {response.status_code} on {url}. Retrying...")
                time.sleep(backoff_factor ** attempt)
                continue
                
            return response
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"Network error on {url}: {e}. Retrying...")
            last_exception = e
            time.sleep(backoff_factor ** attempt)
            
    logger.error(f"Failed to fetch {url} after {max_retries} attempts.")
    if last_exception:
        raise last_exception
    else:
        raise requests.exceptions.RequestException(f"HTTP requests failed with code >= 500")


class WebScraper:
    def __init__(self, config):
        self.config = config
        self.headers = {
            "User-Agent": config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        }
        self.timeout = config.get("request_timeout_seconds", 15)
        self.max_retries = config.get("max_retries", 3)
        self.backoff_factor = config.get("retry_backoff_factor", 2)


    def scrape_kpsc_notifications(self, site_config):
        """
        Scrapes Kerala Public Service Commission notifications.
        First parses the main table, follows links to gazette pages, and extracts PDF links.
        """
        url = site_config["url"]
        logger.info(f"Starting scraping for Kerala PSC notifications from {url}")
        
        response = fetch_url_with_retries(
            url, self.headers, self.timeout, self.max_retries, self.backoff_factor
        )
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Kerala PSC notifications are listed in a table
        tables = soup.find_all("table")
        if not tables:
            logger.error("No tables found on Kerala PSC notifications page.")
            return []
            
        main_table = tables[0]
        rows = main_table.find_all("tr")
        
        notifications = []
        # Skip header row (index 0)
        for row in rows[1:]:
            cols = row.find_all(["td", "th"])
            if not cols:
                continue
                
            # Columns: [Title, Category Number, Last Date]
            title_col = cols[0]
            
            # Find the link to follow (the subpage)
            subpage_link = title_col.find("a")
            if not subpage_link:
                continue
                
            subpage_href = subpage_link.get("href")
            if not subpage_href:
                continue
                
            subpage_url = urljoin(url, subpage_href)
            gazette_title = title_col.text.strip().replace('\n', ' ')
            gazette_title = re.sub(r'\s+', ' ', gazette_title)
            
            logger.info(f"Following Gazette subpage: {subpage_url} ({gazette_title})")
            
            # Visit the subpage to find individual PDF attachments
            try:
                sub_response = fetch_url_with_retries(
                    subpage_url, self.headers, self.timeout, self.max_retries, self.backoff_factor
                )
                sub_soup = BeautifulSoup(sub_response.text, "html.parser")
                
                # Find all PDF links in subpage
                for a in sub_soup.find_all("a"):
                    href = a.get("href", "")
                    text = a.text.strip().replace('\n', ' ')
                    text = re.sub(r'\s+', ' ', text)
                    
                    if "pdf" in href.lower() and text:
                        # Skip general non-notification links like authorized signatory
                        if "authorised-signatory" in href.lower() or "instruction" in text.lower():
                            continue
                            
                        pdf_url = urljoin(subpage_url, href)
                        notifications.append({
                            "title": text,
                            "pdf_url": pdf_url,
                            "notification_url": subpage_url,
                            "gazette_title": gazette_title
                        })
            except Exception as e:
                logger.error(f"Error scraping KPSC subpage {subpage_url}: {e}")
                # Continue processing other rows
                continue
                
        logger.info(f"Found {len(notifications)} notifications from Kerala PSC subpages.")
        return notifications

    def scrape_ugc_net(self, site_config):
        """
        Scrapes UGC NET public notices section.
        """
        url = site_config["url"]
        logger.info(f"Starting scraping for UGC NET notices from {url}")
        
        response = fetch_url_with_retries(
            url, self.headers, self.timeout, self.max_retries, self.backoff_factor
        )
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Look for container div with id 'whats-new' or class containing 'whats-new'
        container = soup.find(id="whats-new")
        if not container:
            container = soup.find(class_=re.compile("whats-new|whatsnew", re.I))
            
        if not container:
            logger.warning("UGC NET 'whats-new' container not found. Fallback to all pdf links.")
            container = soup # Fallback to whole page if container not found
            
        notices = []
        links = container.find_all("a")
        for a in links:
            href = a.get("href", "").strip()
            text = a.text.strip().replace('\n', ' ')
            text = re.sub(r'\s+', ' ', text)
            
            # Check if it's a PDF link
            if "pdf" in href.lower() and text:
                # Filter out utility links like information bulletins or archive pages
                if "bulletin" in text.lower() or "archive" in text.lower() or "sitemap" in href.lower():
                    continue
                    
                absolute_url = urljoin(url, href)
                notices.append({
                    "title": text,
                    "pdf_url": absolute_url,
                    "notice_url": url
                })
                
        logger.info(f"Found {len(notices)} notices on UGC NET site.")
        return notices

    def scrape_rss_feed(self, site_config):
        """
        Scrapes a standard RSS feed.
        """
        url = site_config["url"]
        logger.info(f"Scraping RSS feed: {url}")
        
        response = fetch_url_with_retries(
            url, self.headers, self.timeout, self.max_retries, self.backoff_factor
        )
        
        items = []
        try:
            # Parse XML
            root = ET.fromstring(response.content)
            for item in root.findall(".//item"):
                title = item.find("title")
                link = item.find("link")
                description = item.find("description")
                pub_date = item.find("pubDate")
                
                title_text = title.text.strip() if title is not None else "N/A"
                link_text = link.text.strip() if link is not None else ""
                desc_text = description.text.strip() if description is not None else ""
                date_text = pub_date.text.strip() if pub_date is not None else "N/A"
                
                # Check for PDF links in link or description
                pdf_url = ""
                if link_text.lower().endswith(".pdf"):
                    pdf_url = link_text
                
                items.append({
                    "title": title_text,
                    "link": link_text,
                    "description": desc_text,
                    "pub_date": date_text,
                    "pdf_url": pdf_url
                })
        except Exception as e:
            logger.error(f"Error parsing RSS feed {url}: {e}")
            
        return items

    def scrape_generic_site(self, site_config):
        """
        Scrapes a generic website based on link extraction.
        """
        url = site_config["url"]
        logger.info(f"Scraping generic website: {url}")
        
        response = fetch_url_with_retries(
            url, self.headers, self.timeout, self.max_retries, self.backoff_factor
        )
        soup = BeautifulSoup(response.text, "html.parser")
        
        links = soup.find_all("a")
        items = []
        for a in links:
            href = a.get("href", "").strip()
            text = a.text.strip().replace('\n', ' ')
            text = re.sub(r'\s+', ' ', text)
            
            if not href or not text or len(text) < 5:
                continue
                
            absolute_url = urljoin(url, href)
            # Simple deduplication
            if not any(item["link"] == absolute_url for item in items):
                items.append({
                    "title": text,
                    "link": absolute_url,
                    "pdf_url": absolute_url if absolute_url.lower().endswith(".pdf") else ""
                })
        return items
