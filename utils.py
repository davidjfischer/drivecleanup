"""
Utility functions for DriveCleanup
"""

import os
import pickle
import sys
import re
import glob
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from loguru import logger

from config import (
    SCOPES_READONLY, SCOPES_WRITE,
    STATE_DIR, REPORTS_DIR, LOGS_DIR
)

# For single-key input
try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False


def setup_file_logging(folder_id, start_time):
    """Set up file logging for the session."""
    timestamp = start_time.strftime('%Y%m%d_%H%M%S')
    log_filename = os.path.join(LOGS_DIR, f"{folder_id}_session_{timestamp}.log")

    logger.debug(f"Setting up file logging to {log_filename}")

    # Add file handler
    logger.add(
        log_filename,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS UTC} | {level: <8} | {message}",
        level="DEBUG",  # Log everything to file
        backtrace=True,
        diagnose=True
    )

    logger.info(f"Session log file: {log_filename}")
    return log_filename


def authenticate(write_access=False):
    """Authenticate with Google Drive API."""
    access_type = "write" if write_access else "read-only"
    logger.debug(f"Authenticating with Google Drive API ({access_type} access)")

    creds = None
    scopes = SCOPES_WRITE if write_access else SCOPES_READONLY
    token_file = 'token_write.pickle' if write_access else 'token.pickle'

    logger.debug(f"Using token file: {token_file}")

    if os.path.exists(token_file):
        logger.debug(f"Loading existing credentials from {token_file}")
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials")
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                logger.error("credentials.json not found!")
                logger.error("Please download OAuth credentials from Google Cloud Console")
                sys.exit(1)

            logger.info("Starting OAuth flow - your browser will open")
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', scopes)
            creds = flow.run_local_server(port=0)

        logger.debug(f"Saving credentials to {token_file}")
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)

    logger.debug("Building Google Drive service")
    return build('drive', 'v3', credentials=creds)


def extract_folder_id(url_or_id):
    """Extract folder ID from URL or return ID if already provided."""
    if not url_or_id:
        return None

    # If it's already just an ID (no slashes or special chars)
    if '/' not in url_or_id and 'drive.google.com' not in url_or_id:
        return url_or_id

    # Extract from URL patterns
    # Pattern 1: /folders/FOLDER_ID
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', url_or_id)
    if match:
        return match.group(1)

    # Pattern 2: id=FOLDER_ID
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url_or_id)
    if match:
        return match.group(1)

    return url_or_id


def extract_file_id_from_link(link):
    """Extract file ID from Google Drive link."""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    return None


def find_latest_report(folder_id):
    """Find the most recent cleanup report for a given folder ID."""
    logger.debug(f"Searching for reports in {REPORTS_DIR} directory")

    # Pattern for report files
    pattern = os.path.join(REPORTS_DIR, f"drive_cleanup_report_{folder_id}_*.txt")
    reports = glob.glob(pattern)

    logger.debug(f"Found {len(reports)} report(s) matching pattern")

    if not reports:
        logger.warning(f"No reports found for folder {folder_id}")
        return None

    # Sort by modification time (newest first)
    reports.sort(key=os.path.getmtime, reverse=True)
    latest = reports[0]
    logger.info(f"Using latest report: {os.path.basename(latest)}")
    return latest


def get_single_key():
    """Get a single key press without requiring Enter."""
    if HAS_TERMIOS:
        # Unix/Linux/macOS
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
    elif HAS_MSVCRT:
        # Windows
        ch = msvcrt.getch()
        return ch.decode('utf-8')
    else:
        # Fallback to standard input
        return input().strip().lower()


def log_deleted_file(folder_id, file_name, file_link, file_size):
    """Log a deleted file to the deleted files list."""
    log_file = os.path.join(STATE_DIR, f"{folder_id}_deleted_files.txt")
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    logger.debug(f"Logging deleted file to {log_file}: {file_name}")

    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | {file_name} | {file_size} | {file_link}\n")


def log_skipped_file(folder_id, file_name, file_link, file_size):
    """Log a skipped file to the skipped files list."""
    log_file = os.path.join(STATE_DIR, f"{folder_id}_skipped_files.txt")
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    logger.debug(f"Logging skipped file to {log_file}: {file_name}")

    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | {file_name} | {file_size} | {file_link}\n")


def load_processed_files(folder_id):
    """Load already deleted and skipped files."""
    logger.debug(f"Loading processed files for folder {folder_id}")

    deleted_files = set()
    skipped_files = set()

    # Load deleted files
    deleted_log = os.path.join(STATE_DIR, f"{folder_id}_deleted_files.txt")
    if os.path.exists(deleted_log):
        logger.debug(f"Loading deleted files from {deleted_log}")
        with open(deleted_log, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(' | ')
                if len(parts) >= 3:
                    file_link = parts[3] if len(parts) > 3 else parts[2]
                    file_id = extract_file_id_from_link(file_link)
                    if file_id:
                        deleted_files.add(file_id)
        logger.debug(f"Loaded {len(deleted_files)} deleted file IDs")
    else:
        logger.debug(f"No deleted files log found at {deleted_log}")

    # Load skipped files
    skipped_log = os.path.join(STATE_DIR, f"{folder_id}_skipped_files.txt")
    if os.path.exists(skipped_log):
        logger.debug(f"Loading skipped files from {skipped_log}")
        with open(skipped_log, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(' | ')
                if len(parts) >= 3:
                    file_link = parts[3] if len(parts) > 3 else parts[2]
                    file_id = extract_file_id_from_link(file_link)
                    if file_id:
                        skipped_files.add(file_id)
        logger.debug(f"Loaded {len(skipped_files)} skipped file IDs")
    else:
        logger.debug(f"No skipped files log found at {skipped_log}")

    return deleted_files, skipped_files


def parse_cleanup_report(report_file):
    """Parse cleanup report and extract file information."""
    if not os.path.exists(report_file):
        logger.error(f"Report file not found: {report_file}")
        return []

    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse entries
    entries = []

    # Split by confidence sections
    sections = re.split(r'={80}\n([A-Z]+) CONFIDENCE DELETE CANDIDATES\n={80}', content)

    for i in range(1, len(sections), 2):
        confidence = sections[i]
        section_content = sections[i + 1]

        # Parse individual entries
        entry_pattern = r'\[(\d+)\] (.+?)\n    Size: (.+?)\n    Link: (.+?)\n    Reasons:\n((?:      - .+\n)+)'

        for match in re.finditer(entry_pattern, section_content):
            index, name, size, link, reasons_block = match.groups()

            reasons = [r.strip('- ').strip() for r in reasons_block.strip().split('\n')]

            # Extract file ID from link
            file_id = extract_file_id_from_link(link)

            # Check if there's a content summary
            summary_pattern = r'    Content Summary:\n      (.+?)(?:\n\n|\n\[|$)'
            summary_match = re.search(summary_pattern, section_content[match.end():])
            summary = summary_match.group(1) if summary_match else None

            entry = {
                'index': int(index),
                'name': name,
                'size': size,
                'link': link,
                'file_id': file_id,
                'confidence': confidence,
                'reasons': reasons,
                'summary': summary
            }
            entries.append(entry)

    return entries
