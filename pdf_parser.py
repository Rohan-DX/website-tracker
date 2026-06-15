import os
import re
import logging
import requests
import tempfile

logger = logging.getLogger("website_tracker")

# Try importing pdfplumber
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# Try importing fitz (PyMuPDF)
try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def download_pdf(url, headers, timeout=30):
    """
    Downloads a PDF from a URL to a temporary file.
    Returns the path to the temporary file, or None if failed.
    """
    try:
        logger.info(f"Downloading PDF from: {url}")
        r = requests.get(url, headers=headers, timeout=timeout, verify=False) # verify=False for portals with SSL certificate issues
        if r.status_code == 200:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.write(r.content)
            temp_file.close()
            logger.info(f"PDF downloaded to temporary file: {temp_file.name}")
            return temp_file.name
        else:
            logger.error(f"Failed to download PDF. Status: {r.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None


def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a local PDF file using pdfplumber, with fallback to PyMuPDF.
    """
    text = ""
    # Try pdfplumber first
    if HAS_PDFPLUMBER:
        try:
            logger.info("Attempting text extraction using pdfplumber...")
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = []
                for idx, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                text = "\n".join(pages_text).strip()
                if text:
                    logger.info(f"Extracted {len(text)} characters using pdfplumber.")
                    return text
        except Exception as e:
            logger.warning(f"pdfplumber text extraction failed: {e}")

    # Fallback to PyMuPDF
    if HAS_PYMUPDF:
        try:
            logger.info("Attempting text extraction using PyMuPDF (fitz) fallback...")
            doc = fitz.open(pdf_path)
            pages_text = []
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    pages_text.append(page_text)
            text = "\n".join(pages_text).strip()
            if text:
                logger.info(f"Extracted {len(text)} characters using PyMuPDF.")
                return text
        except Exception as e:
            logger.error(f"PyMuPDF text extraction failed: {e}")

    if not HAS_PDFPLUMBER and not HAS_PYMUPDF:
        logger.error("Neither pdfplumber nor PyMuPDF is installed. Cannot extract PDF text.")
    
    return text


def parse_kpsc_pdf(pdf_path, pdf_url=None, notification_url=None):
    """
    Parses Kerala PSC PDF and extracts required fields.
    """
    data = {
        "post_name": "N/A",
        "category_number": "N/A",
        "department": "N/A",
        "qualification": "N/A",
        "age_limit": "N/A",
        "pay_scale": "N/A",
        "last_date": "N/A",
        "pdf_url": pdf_url,
        "notification_url": notification_url
    }

    if not pdf_path or not os.path.exists(pdf_path):
        return data

    text = extract_text_from_pdf(pdf_path)
    if not text:
        logger.warning("No text extracted from KPSC PDF. Returning empty fields.")
        return data

    # 1. Category Number
    cat_match = re.search(r"CATEGORY\s*NO\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if cat_match:
        data["category_number"] = cat_match.group(1).strip()

    # 2. Department
    dept_match = re.search(r"\bDepartment\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if not dept_match:
        # try search with numbers
        dept_match = re.search(r"\b\d+\.?\s*Department\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if dept_match:
        data["department"] = dept_match.group(1).strip()

    # 3. Post Name
    post_match = re.search(r"\b(?:Name of\s+)?Post\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if not post_match:
        post_match = re.search(r"\b\d+\.?\s*(?:Name of\s+)?Post\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if post_match:
        data["post_name"] = post_match.group(1).strip()

    # 4. Pay Scale
    pay_match = re.search(r"\b(?:Scale of\s+)?pay\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if not pay_match:
        pay_match = re.search(r"\b\d+\.?\s*(?:Scale of\s+)?pay\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if pay_match:
        data["pay_scale"] = pay_match.group(1).strip()

    # 5. Age Limit (capture until next numbered item or Note)
    age_match = re.search(r"\b\d*\.?\s*Age\s*limit\s*:\s*(.*?)(?=\r?\n\s*\d+\.\s*|\r?\n\s*Note:)", text, re.IGNORECASE | re.DOTALL)
    if age_match:
        data["age_limit"] = age_match.group(1).strip().replace('\n', ' ')

    # 6. Qualifications (capture until next numbered item)
    qual_match = re.search(r"\b\d*\.?\s*Qualifications\s*:\s*(.*?)(?=\r?\n\s*\d+\.\s*|\r?\n\s*Mode of submitting)", text, re.IGNORECASE | re.DOTALL)
    if qual_match:
        data["qualification"] = qual_match.group(1).strip().replace('\n', ' ')

    # 7. Last Date
    last_match = re.search(r"\bLast\s*date\s*for\s*receipt\s*of\s*applications:-?\s*([^\n\r]+)", text, re.IGNORECASE)
    if not last_match:
        last_match = re.search(r"\b\d+\.?\s*Last\s*date\s*for\s*receipt\s*of\s*applications:-?\s*([^\n\r]+)", text, re.IGNORECASE)
    if last_match:
        data["last_date"] = last_match.group(1).strip()

    return data


def parse_ugc_net_pdf(pdf_path, notice_title, pdf_url=None, notice_url=None):
    """
    Parses UGC NET Notice PDF and extracts required fields.
    If the PDF is a scanned image (0 text), falls back to metadata extraction.
    """
    data = {
        "title": notice_title,
        "date": "N/A",
        "examination_session": "N/A",
        "important_dates": "N/A",
        "application_deadline": "N/A",
        "exam_dates": "N/A",
        "result_dates": "N/A",
        "admit_card_announcement": "N/A",
        "answer_key_announcement": "N/A",
        "summary": "N/A",
        "pdf_url": pdf_url,
        "notice_url": notice_url
    }

    # Extract date from URL path if available (e.g. .../uploads/2026/06/20260610...)
    if pdf_url:
        # Look for YYYYMMDD at the beginning of the filename in the URL
        fn_match = re.search(r"/uploads/\d{4}/\d{2}/(\d{4})(\d{2})(\d{2})", pdf_url)
        if fn_match:
            data["date"] = f"{fn_match.group(1)}-{fn_match.group(2)}-{fn_match.group(3)}"
        else:
            # Fallback to year/month matching
            ym_match = re.search(r"/uploads/(\d{4})/(\d{2})/", pdf_url)
            if ym_match:
                data["date"] = f"{ym_match.group(1)}-{ym_match.group(2)}"

    # Parse Exam Session from Notice Title (e.g. "UGC-NET June 2026")
    session_match = re.search(r"UGC-NET\s*([A-Za-z]+\s*\d{4})", notice_title, re.IGNORECASE)
    if session_match:
        data["examination_session"] = session_match.group(1).strip()
    else:
        # Try finding general month + year
        gen_session = re.search(r"\b(June|December|Cycle)\s*(\d{4})", notice_title, re.IGNORECASE)
        if gen_session:
            data["examination_session"] = f"{gen_session.group(1)} {gen_session.group(2)}"

    # Set initial summary based on notice title
    data["summary"] = notice_title

    # Populate announcements based on title keywords if scanned
    for field, keyword in [
        ("admit_card_announcement", "admit card|city intimation"),
        ("answer_key_announcement", "answer key|challenge"),
        ("result_dates", "result|declaration of result"),
        ("application_deadline", "last date|extension|online application"),
        ("exam_dates", "schedule|date of exam|subject-wise")
    ]:
        if re.search(keyword, notice_title, re.IGNORECASE):
            data[field] = notice_title

    if not pdf_path or not os.path.exists(pdf_path):
        data["important_dates"] = "Scanned PDF - See official notice for details."
        return data

    text = extract_text_from_pdf(pdf_path)
    if not text:
        logger.info("PDF has no readable text (probably scanned). Using title-based fallback parsing.")
        data["important_dates"] = "Scanned PDF - Details could not be extracted automatically."
        return data

    # PDF has text, let's extract fields using regex
    # 1. Publish Date
    date_match = re.search(r"(?:Dated?|Date)\s*:\s*(\d{2}[./-]\d{2}[./-]\d{4})", text, re.IGNORECASE)
    if date_match:
        data["date"] = date_match.group(1).strip()

    # 2. Session
    sess_match = re.search(r"UGC\s*-\s*NET\s*([A-Za-z]+\s*\d{4})", text, re.IGNORECASE)
    if sess_match:
        data["examination_session"] = sess_match.group(1).strip()

    # 3. Important Dates / Deadlines / Exam dates
    # Often, UGC NET notices have sections or tables:
    # "Submission of Online Application Form: DD.MM.YYYY to DD.MM.YYYY"
    deadline_match = re.search(r"(?:Submission of Online Application|Last date for submission|Last Date).*?(\d{2}[./-]\d{2}[./-]\d{4}.*?to.*?\d{2}[./-]\d{2}[./-]\d{4}|\d{2}[./-]\d{2}[./-]\d{4})", text, re.IGNORECASE | re.DOTALL)
    if deadline_match:
        data["application_deadline"] = deadline_match.group(1).strip().replace('\n', ' ')

    exam_match = re.search(r"(?:Dates? of Examination|Date of Exam|Examination Dates).*?(\d{2}.*?(?:to|and).*?\d{2}.*?\w+\s+\d{4}|\d{2}[./-]\d{2}[./-]\d{4})", text, re.IGNORECASE | re.DOTALL)
    if exam_match:
        data["exam_dates"] = exam_match.group(1).strip().replace('\n', ' ')

    # Let's capture the main date schedule block as "important_dates"
    # Search for blocks starting with "Events" or "Activity" or containing multiple dates
    schedule_block = re.search(r"(?:Submission of Online Application|Online Submission|Activity\s+Dates).*?(?=\bInformation\b|\bFor\b|\bCandidates\b|\bNotes\b|\bThe\b)", text, re.IGNORECASE | re.DOTALL)
    if schedule_block:
        data["important_dates"] = schedule_block.group(0).strip()
    else:
        # Fallback: assemble fields
        parts = []
        if data["application_deadline"] != "N/A":
            parts.append(f"Application Deadline: {data['application_deadline']}")
        if data["exam_dates"] != "N/A":
            parts.append(f"Exam Dates: {data['exam_dates']}")
        data["important_dates"] = "\n".join(parts) if parts else "See notice details."

    # Parse details to create a summary
    # Grab the first 2-3 paragraphs or sentences
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    summary_lines = []
    found_intro = False
    for line in lines:
        if re.search(r"public notice|advisory|subject|information", line, re.IGNORECASE):
            found_intro = True
        if found_intro:
            summary_lines.append(line)
            if len(summary_lines) >= 4:
                break
    if summary_lines:
        data["summary"] = "\n".join(summary_lines)

    return data
