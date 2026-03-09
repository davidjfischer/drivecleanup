"""
Configuration constants for DriveCleanup
"""

# OAuth Scopes
SCOPES_READONLY = ['https://www.googleapis.com/auth/drive.readonly']
SCOPES_WRITE = ['https://www.googleapis.com/auth/drive']  # For deletion

# Directories
STATE_DIR = 'state'
REPORTS_DIR = 'reports'
LOGS_DIR = 'logs'
PROMPTS_DIR = 'prompts'

# Cache files
import os
CHECKSUMS_CACHE_FILE = os.path.join(STATE_DIR, 'drive_checksums_cache.json')

# UI Box formatting constants
BOX_WIDTH = 78
BOX_TOTAL_WIDTH = 80  # BOX_WIDTH + 2 for borders
BOX_MAX_TEXT_WIDTH = 74  # For content with bullet points
BOX_CONTENT_MAX_WIDTH = 72  # For indented content

# Content extraction limits
MAX_PDF_PAGES = 3
MAX_WORD_PARAGRAPHS = 20
MAX_EXCEL_ROWS = 10
MAX_TEXT_CHARS = 5000
MAX_CLAUDE_CHARS = 15000

# Content analysis limits
MAX_FILES_WITH_CLAUDE = 50
MAX_FILES_WITHOUT_CLAUDE = 100
MAX_SUMMARY_WORDS = 50

# Report display limits
MAX_CANDIDATES_IN_REPORT = 50

# File patterns that are typically safe to delete
TEMP_PATTERNS = [
    'tmp', 'temp', 'cache', '.cache', '.tmp',
    'untitled', 'copy of', 'kopie von', '(1)', '(2)', '(3)',
    'screenshot', 'bildschirmfoto', 'screen shot',
    'download', 'downloads'
]

# File extensions that are often temporary or unnecessary
TEMP_EXTENSIONS = [
    '.tmp', '.temp', '.bak', '.old', '.cache',
    '.crdownload', '.part', '.download'
]

# Archive/backup patterns
BACKUP_PATTERNS = [
    'backup', 'archive', 'archiv', 'old', 'alt',
    'sicherung', '.zip', '.tar', '.gz', '.7z', '.rar'
]

# Age thresholds (in days)
VERY_OLD_DAYS = 730  # 2 years
OLD_DAYS = 365  # 1 year
SOMEWHAT_OLD_DAYS = 180  # 6 months

# Size thresholds (in bytes)
LARGE_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
VERY_LARGE_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
