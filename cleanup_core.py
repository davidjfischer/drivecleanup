"""
Shared cleanup module for DriveCleanup tools.
Contains common interactive cleanup logic used by both clean_duplicates.py and clean_obsolete.py.
"""

import os
import re
import sys
import webbrowser
import unicodedata
from datetime import datetime, timezone
from loguru import logger
from googleapiclient.errors import HttpError

# Import configuration
from config import STATE_DIR, BOX_WIDTH, BOX_MAX_TEXT_WIDTH, BOX_CONTENT_MAX_WIDTH

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


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_file_id_from_link(link):
    """Extract file ID from Google Drive link."""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    return None


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
    """Parse cleanup report (JSON format) and extract file information."""
    import json

    if not os.path.exists(report_file):
        logger.error(f"Report file not found: {report_file}")
        return []

    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON report: {e}")
        return []

    entries = []

    # Parse candidates from JSON structure
    candidates = report_data.get('candidates', {})

    for confidence in ['HIGH', 'MEDIUM', 'LOW']:
        for candidate in candidates.get(confidence, []):
            # Try to get file_id directly from JSON first (both scripts use 'id')
            # Fall back to extracting from link for backwards compatibility
            file_id = candidate.get('id')
            if not file_id:
                file_id = extract_file_id_from_link(candidate.get('link', ''))

            # Handle different size formats
            # clean_duplicates.py uses 'size_formatted' (string)
            # clean_obsolete.py uses 'size' (integer bytes)
            size_str = candidate.get('size_formatted')
            if not size_str:
                size_bytes = candidate.get('size', 0)
                if size_bytes < 1024:
                    size_str = f"{size_bytes} bytes"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

            entry = {
                'name': candidate.get('name', 'Unknown'),
                'path': candidate.get('path'),
                'size': size_str,
                'link': candidate.get('link', ''),
                'file_id': file_id,
                'confidence': confidence,
                'reasons': candidate.get('reasons', []),
                'summary': candidate.get('summary')
            }
            entries.append(entry)

    return entries


# ============================================================================
# UI FUNCTIONS
# ============================================================================

def get_display_width(text):
    """Calculate display width accounting for wide characters (emojis)."""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2  # Full-width and Wide characters (like emojis)
        else:
            width += 1
    return width


def format_box_line(text, width=BOX_WIDTH, color_code=''):
    """Format a line for box display with proper padding."""
    reset = '\033[0m' if color_code else ''

    # Truncate if too long
    max_text_width = width - 2
    if len(text) > max_text_width:
        text = text[:max_text_width]

    # Calculate display width for proper padding
    display_width = get_display_width(text)
    padding_needed = width - 2 - display_width

    return f"{color_code}║ {text}{' ' * padding_needed} ║{reset}"


def format_box_separator(char="─", width=BOX_WIDTH, color_code=''):
    """Format a separator line for box display."""
    reset = '\033[0m' if color_code else ''
    return f"{color_code}╠{char * width}╣{reset}"


def print_colored_tip_box(lines, color_code='\033[91m', width=BOX_WIDTH):
    """Print a colored tip box with proper emoji alignment."""
    reset = '\033[0m'

    print(f"{color_code}╔" + "═" * width + "╗" + reset)

    for line in lines:
        # Handle empty lines
        if not line:
            padding = width - 2
            print(f"{color_code}║ {' ' * padding} ║{reset}")
            continue

        # Check if line fits in one line
        display_width = get_display_width(line)
        if display_width <= width - 2:
            padding = width - 2 - display_width
            print(f"{color_code}║ {line}{' ' * padding} ║{reset}")
        else:
            # Word wrap for long lines
            words = line.split()
            current_line = ""
            current_width = 0

            for word in words:
                word_with_space = word + " "
                word_width = get_display_width(word_with_space)

                if current_width + word_width <= width - 2:
                    current_line += word_with_space
                    current_width += word_width
                else:
                    if current_line:
                        line_stripped = current_line.rstrip()
                        line_display_width = get_display_width(line_stripped)
                        padding = width - 2 - line_display_width
                        print(f"{color_code}║ {line_stripped}{' ' * padding} ║{reset}")
                    current_line = word + " "
                    current_width = get_display_width(current_line)

            if current_line:
                line_stripped = current_line.rstrip()
                line_display_width = get_display_width(line_stripped)
                padding = width - 2 - line_display_width
                print(f"{color_code}║ {line_stripped}{' ' * padding} ║{reset}")

    print(f"{color_code}╚" + "═" * width + "╝" + reset)
    print()


# ============================================================================
# INTERACTIVE CLEANUP
# ============================================================================

def interactive_cleanup(service, report_file, folder_id):
    """Interactive cleanup session based on report.

    Args:
        service: Authenticated Google Drive service
        report_file: Path to JSON report file
        folder_id: Folder ID for logging purposes

    Returns:
        Tuple of (deleted_count, skipped_count, already_processed_count)
    """
    logger.info("=" * 80)
    logger.info("INTERACTIVE CLEANUP MODE")
    logger.info("=" * 80)
    logger.info(f"Loading report: {report_file}")

    entries = parse_cleanup_report(report_file)

    if not entries:
        logger.error("No entries found in report or report format is invalid")
        return (0, 0, 0)

    logger.info(f"Found {len(entries)} delete candidates")

    # Load already processed files
    deleted_files, skipped_files = load_processed_files(folder_id)

    if deleted_files:
        logger.info(f"Found {len(deleted_files)} already deleted files - will skip those")
    if skipped_files:
        logger.info(f"Found {len(skipped_files)} already skipped files - will skip those")

    logger.info("")

    # Log files
    deleted_log = os.path.join(STATE_DIR, f"{folder_id}_deleted_files.txt")
    skipped_log = os.path.join(STATE_DIR, f"{folder_id}_skipped_files.txt")

    logger.info(f"Deleted files will be logged to: {deleted_log}")
    logger.info(f"Skipped files will be logged to: {skipped_log}")
    logger.info("")

    deleted_count = 0
    skipped_count = 0
    already_processed_count = 0
    auto_decision = None  # Track "delete all" or "skip all" choice

    for i, entry in enumerate(entries):
        # Skip if already deleted or skipped
        if entry['file_id'] in deleted_files:
            logger.debug(f"Skipping already deleted file: {entry['name']}")
            already_processed_count += 1
            continue

        if entry['file_id'] in skipped_files:
            logger.debug(f"Skipping already skipped file: {entry['name']}")
            already_processed_count += 1
            continue

        # Handle auto-decision from "delete all" or "skip all"
        if auto_decision == 'delete':
            logger.info(f"[AUTO-DELETE] Processing file {i + 1}/{len(entries)}: {entry['name']}")
            try:
                service.files().update(
                    fileId=entry['file_id'],
                    body={'trashed': True}
                ).execute()
                logger.info(f"✅ Moved to trash (auto): {entry['name']}")
                log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                deleted_files.add(entry['file_id'])
                deleted_count += 1
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning(f"⚠️  File not found (404) - treating as deleted: {entry['name']}")
                    log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                    deleted_files.add(entry['file_id'])
                    deleted_count += 1
                else:
                    logger.error(f"❌ Failed to delete (auto): HTTP {e.resp.status} - {entry['name']}")
            except Exception as e:
                logger.error(f"❌ Failed to delete (auto): {type(e).__name__} - {entry['name']}")
            continue

        if auto_decision == 'skip':
            logger.info(f"[AUTO-SKIP] Skipping file {i + 1}/{len(entries)}: {entry['name']}")
            log_skipped_file(folder_id, entry['name'], entry['link'], entry['size'])
            skipped_files.add(entry['file_id'])
            skipped_count += 1
            continue

        # Log file description BEFORE showing dialog
        logger.info("=" * 80)
        logger.info(f"Presenting file {i + 1}/{len(entries)} to user: {entry['name']}")
        logger.info(f"  Size: {entry['size']}")
        logger.info(f"  Confidence: {entry['confidence']}")
        logger.info(f"  Link: {entry['link']}")
        logger.info(f"  Reasons:")
        for reason in entry['reasons']:
            logger.info(f"    - {reason}")
        if entry.get('summary'):
            logger.info(f"  Content Summary: {entry['summary'][:200]}")
        logger.info("=" * 80)

        # Print beautiful dialog box (NOT logged, only to stdout)
        # Use red color for all boxes
        RED = '\033[91m'
        RESET = '\033[0m'

        print("\n")
        print(f"{RED}╔" + "═" * 78 + "╗" + RESET)
        print(format_box_line(f"File {i + 1}/{len(entries)} - {entry['confidence']} CONFIDENCE", color_code=RED))
        print(format_box_separator("═", color_code=RED))

        # For duplicates, show full path instead of just name
        if entry.get('path'):
            # Show full path for duplicates
            path = entry['path']
            if len(path) <= 68:
                print(format_box_line(f"Path: {path}", color_code=RED))
            else:
                # Wrap long paths
                print(format_box_line(f"Path: {path[:68]}", color_code=RED))
                remaining = path[68:]
                while remaining:
                    print(format_box_line(f"      {remaining[:68]}", color_code=RED))
                    remaining = remaining[68:]
        else:
            # Show just name for non-duplicates
            print(format_box_line(f"Name: {entry['name'][:68]}", color_code=RED))

        print(format_box_line(f"Size: {entry['size']}", color_code=RED))
        print(format_box_separator("─", color_code=RED))

        # Print reasons
        print(format_box_line("Reasons:", color_code=RED))
        for reason in entry['reasons']:
            # Wrap long reasons
            reason_lines = []
            reason_text = f"  • {reason}"
            if len(reason_text) <= BOX_MAX_TEXT_WIDTH:
                reason_lines.append(reason_text)
            else:
                # Word wrap
                words = reason.split()
                current_line = "  • "
                for word in words:
                    if len(current_line + word + " ") <= BOX_MAX_TEXT_WIDTH:
                        current_line += word + " "
                    else:
                        reason_lines.append(current_line.rstrip())
                        current_line = "    " + word + " "
                if current_line.strip():
                    reason_lines.append(current_line.rstrip())

            for line in reason_lines:
                print(format_box_line(line, color_code=RED))

        # Print summary if available
        if entry.get('summary'):
            print(format_box_separator("─", color_code=RED))
            print(format_box_line("Content Summary:", color_code=RED))
            summary_lines = entry['summary'].split('\n')
            for line in summary_lines:
                # Wrap long lines
                if len(line) <= BOX_CONTENT_MAX_WIDTH:
                    print(format_box_line(f"  {line}", color_code=RED))
                else:
                    # Word wrap
                    words = line.split()
                    current_line = "  "
                    for word in words:
                        if len(current_line + word + " ") <= BOX_MAX_TEXT_WIDTH:
                            current_line += word + " "
                        else:
                            print(format_box_line(current_line.rstrip(), color_code=RED))
                            current_line = "  " + word + " "
                    if current_line.strip():
                        print(format_box_line(current_line.rstrip(), color_code=RED))

        # Print options
        print(format_box_separator("═", color_code=RED))
        print(format_box_line("Choose action:", color_code=RED))
        print(format_box_line("  (1) Delete  │  (2) Browser  │  (3) Skip  │  (4) Next", color_code=RED))
        print(format_box_line("  (5) Delete all  │  (6) Skip all  │  (q) Quit", color_code=RED))
        print(f"{RED}╚" + "═" * 78 + "╝" + RESET)
        print("Your choice: ", end='', flush=True)

        choice = get_single_key().lower()
        print(choice)  # Echo the choice

        # Log user choice
        logger.info(f"User choice: {choice}")

        # Process the choice
        action_complete = False
        while not action_complete:
            if choice == '1':
                # Delete file
                if not entry['file_id']:
                    logger.error("Cannot delete: File ID not found")
                    logger.error("This should not happen - please report as bug")
                    break

                logger.debug(f"Attempting to move file to trash: {entry['file_id']}")
                try:
                    # Move to trash instead of permanent delete
                    service.files().update(
                        fileId=entry['file_id'],
                        body={'trashed': True}
                    ).execute()
                    logger.info(f"✅ Moved to trash: {entry['name']}")
                    print(f"✅ Moved to trash successfully!")
                    logger.debug(f"Freed up {entry['size']}")
                    log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                    deleted_files.add(entry['file_id'])
                    deleted_count += 1
                    action_complete = True
                except HttpError as e:
                    if e.resp.status == 404:
                        # File already deleted or doesn't exist
                        logger.warning(f"⚠️  File not found (404) - treating as deleted: {entry['name']}")
                        print(f"⚠️  File not found (404) - treating as deleted")
                        logger.debug("File may have been deleted by another process or user")
                        log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                        deleted_files.add(entry['file_id'])
                        deleted_count += 1
                        action_complete = True
                    else:
                        logger.error(f"❌ Failed to delete: HTTP {e.resp.status}")
                        logger.error(f"Error details: {e}")
                        print(f"❌ Failed to delete: {e}")
                        logger.warning("Skipping this file - check permissions or try again later")
                        action_complete = True
                except Exception as e:
                    logger.error(f"❌ Failed to delete: {type(e).__name__}")
                    logger.error(f"Error details: {e}")
                    print(f"❌ Failed to delete: {e}")
                    logger.warning("Unexpected error - skipping this file")
                    action_complete = True

            elif choice == '2':
                # Open in browser
                logger.info(f"🌐 Opening in browser: {entry['link']}")
                print(f"\n🌐 Opening in browser...")
                try:
                    webbrowser.open(entry['link'])
                    print("File opened in browser. Please review and choose an action.")
                    print("\nYour choice: ", end='', flush=True)
                    choice = get_single_key().lower()
                    print(choice)
                    logger.info(f"After browser review, user choice: {choice}")
                    # Continue loop with new choice
                except Exception as e:
                    logger.error(f"Failed to open browser: {e}")
                    print(f"❌ Failed to open browser: {e}")
                    action_complete = True

            elif choice == '3':
                # Skip
                logger.info(f"⏭️  Skipped: {entry['name']}")
                print(f"⏭️  Skipped")
                log_skipped_file(folder_id, entry['name'], entry['link'], entry['size'])
                skipped_files.add(entry['file_id'])
                skipped_count += 1
                action_complete = True

            elif choice == '4':
                # Next - just move to next file without logging
                logger.info(f"➡️  Next: {entry['name']}")
                print(f"➡️  Moving to next file")
                action_complete = True

            elif choice == '5':
                # Delete all - delete current file and all remaining files
                logger.info(f"🗑️  Delete all selected - deleting current and all remaining files")
                print(f"🗑️  Delete all - processing current file and auto-deleting remaining files...")

                # Delete current file first
                if not entry['file_id']:
                    logger.error("Cannot delete: File ID not found")
                    logger.error("This should not happen - please report as bug")
                    break

                logger.debug(f"Attempting to move file to trash: {entry['file_id']}")
                try:
                    service.files().update(
                        fileId=entry['file_id'],
                        body={'trashed': True}
                    ).execute()
                    logger.info(f"✅ Moved to trash: {entry['name']}")
                    print(f"✅ Moved to trash successfully!")
                    log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                    deleted_files.add(entry['file_id'])
                    deleted_count += 1
                except HttpError as e:
                    if e.resp.status == 404:
                        logger.warning(f"⚠️  File not found (404) - treating as deleted: {entry['name']}")
                        print(f"⚠️  File not found (404) - treating as deleted")
                        log_deleted_file(folder_id, entry['name'], entry['link'], entry['size'])
                        deleted_files.add(entry['file_id'])
                        deleted_count += 1
                    else:
                        logger.error(f"❌ Failed to delete: HTTP {e.resp.status}")
                        print(f"❌ Failed to delete: {e}")
                except Exception as e:
                    logger.error(f"❌ Failed to delete: {type(e).__name__}")
                    print(f"❌ Failed to delete: {e}")

                # Set auto-decision for remaining files
                auto_decision = 'delete'
                logger.info("Auto-delete enabled for remaining files")
                action_complete = True

            elif choice == '6':
                # Skip all - skip current file and all remaining files
                logger.info(f"⏭️  Skip all selected - skipping current and all remaining files")
                print(f"⏭️  Skip all - processing current file and auto-skipping remaining files...")

                # Skip current file
                logger.info(f"⏭️  Skipped: {entry['name']}")
                print(f"⏭️  Skipped")
                log_skipped_file(folder_id, entry['name'], entry['link'], entry['size'])
                skipped_files.add(entry['file_id'])
                skipped_count += 1

                # Set auto-decision for remaining files
                auto_decision = 'skip'
                logger.info("Auto-skip enabled for remaining files")
                action_complete = True

            elif choice == 'q':
                print("\n" + "═" * 80)
                print("CLEANUP SESSION SUMMARY")
                print("═" * 80)
                logger.info("")
                logger.info("=" * 80)
                logger.info("CLEANUP SESSION SUMMARY")
                logger.info("=" * 80)
                logger.info(f"Files deleted: {deleted_count}")
                logger.info(f"Files skipped: {skipped_count}")
                logger.info(f"Files already processed: {already_processed_count}")
                logger.info(f"Files remaining: {len(entries) - i - 1}")
                print(f"Files deleted: {deleted_count}")
                print(f"Files skipped: {skipped_count}")
                print(f"Files already processed: {already_processed_count}")
                print(f"Files remaining: {len(entries) - i - 1}")
                logger.info("")
                logger.info(f"Logs saved:")
                logger.info(f"  Deleted: {deleted_log}")
                logger.info(f"  Skipped: {skipped_log}")
                print(f"\nLogs saved:")
                print(f"  Deleted: {deleted_log}")
                print(f"  Skipped: {skipped_log}")

                # Colored tip box advising to rerun for empty folder detection
                print_colored_tip_box([
                    "💡 TIP: Rerun the script to detect newly empty folders!",
                    "",
                    "Deleting files may have created empty folders that can now",
                    "be removed. Run the script again to detect them."
                ])

                print("═" * 80)
                return (deleted_count, skipped_count, already_processed_count)

            else:
                logger.warning(f"Invalid choice: {choice}. Please press 1, 2, 3, 4, 5, 6, or q")
                print(f"❌ Invalid choice '{choice}'. Please press 1, 2, 3, 4, 5, 6, or q")
                print("Your choice: ", end='', flush=True)
                choice = get_single_key().lower()
                print(choice)
                logger.info(f"Retrying with choice: {choice}")

        print("")  # Add spacing after action

    print("\n" + "═" * 80)
    print("CLEANUP SESSION COMPLETE")
    print("═" * 80)
    logger.info("=" * 80)
    logger.info("CLEANUP SESSION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Files deleted: {deleted_count}")
    logger.info(f"Files skipped: {skipped_count}")
    logger.info(f"Files already processed: {already_processed_count}")
    print(f"Files deleted: {deleted_count}")
    print(f"Files skipped: {skipped_count}")
    print(f"Files already processed: {already_processed_count}")
    logger.info("")
    logger.info(f"Logs saved:")
    logger.info(f"  Deleted: {deleted_log}")
    logger.info(f"  Skipped: {skipped_log}")
    print(f"\nLogs saved:")
    print(f"  Deleted: {deleted_log}")
    print(f"  Skipped: {skipped_log}")

    # Colored tip box advising to rerun for empty folder detection
    print_colored_tip_box([
        "💡 TIP: Rerun the script to detect newly empty folders!",
        "",
        "Deleting files may have created empty folders that can now",
        "be removed. Run the script again to detect them."
    ])

    print("═" * 80)

    return (deleted_count, skipped_count, already_processed_count)
