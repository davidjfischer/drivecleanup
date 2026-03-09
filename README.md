# DriveCleanup

Intelligent Google Drive cleanup tool with Claude AI analysis via AWS Bedrock.

## Features

- 🤖 **Claude AI Analysis**: Intelligent content summarization using AWS Bedrock
- 🔍 **Smart Detection**: Identifies obsolete files while protecting photos, videos, and music
- 🔗 **Duplicate Detection**: Automatically finds duplicate files by MD5 checksum and marks them for deletion with HIGH confidence
- 📄 **Content Extraction**: Reads PDFs, Word docs, Excel files, and Google Docs
- ⚡ **Single-Key Controls**: Fast interactive cleanup with no Enter key needed
- 📊 **Comprehensive Logging**: Full session logs and file tracking
- 🔄 **Resume Support**: Automatically skips already processed files
- 🛡️ **Safe Deletion**: Handles 404 errors gracefully

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS account with Bedrock access
- Google Cloud project with Drive API enabled

### Setup

1. Clone the repository:
```bash
git clone https://github.com/davidjfischer/drivecleanup.git
cd drivecleanup
```

2. Install dependencies:
```bash
uv sync
```

3. Add your Google OAuth credentials:
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/)
   - Enable Google Drive API
   - Create OAuth 2.0 credentials
   - Download and save as `credentials.json` in the project directory

4. Configure AWS Bedrock:
   - Ensure you have AWS credentials configured (`~/.aws/credentials`)
   - Enable Claude model access in your AWS Bedrock console

## Usage

### Full Workflow (Refresh + Analyze + Interactive Cleanup)

```bash
uv run python clean_obsolete.py "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### Workflow Steps (Flexible Combinations)

The tool supports three independent workflow steps that can be combined:

```bash
# Refresh checksum cache only
uv run python clean_obsolete.py FOLDER_ID --refresh_checksums

# Analysis only
uv run python clean_obsolete.py FOLDER_ID --analyze

# Cleanup only (uses existing report)
uv run python clean_obsolete.py FOLDER_ID --clean

# Refresh + Analyze (skip cleanup)
uv run python clean_obsolete.py FOLDER_ID --refresh_checksums --analyze

# Analyze + Cleanup (skip refresh)
uv run python clean_obsolete.py FOLDER_ID --analyze --clean
```

Steps always execute in order: **Refresh → Analyze → Clean**

### Without Claude AI (faster, simpler)

```bash
uv run python clean_obsolete.py FOLDER_ID --no-claude
```

### Custom AWS Profile

```bash
uv run python clean_obsolete.py FOLDER_ID --aws-profile prod --aws-region eu-central-1
```

## Interactive Controls

During cleanup, press:
- `1` - Move file to trash (no confirmation)
- `2` - Open in browser (stays in dialog)
- `3` - Skip file (marked as skipped, won't be shown again)
- `4` - Next (move to next file without marking as skipped)
- `q` - Quit session

## Generated Files

The tool organizes generated files into subdirectories:

### `state/` - File tracking
- `{FOLDER_ID}_deleted_files.txt` - Log of all deleted files
- `{FOLDER_ID}_skipped_files.txt` - Log of all skipped files

### `reports/` - Analysis reports
- `drive_cleanup_report_{FOLDER_ID}_{TIMESTAMP}.json` - JSON analysis report with deletion candidates

### `logs/` - Session logs
- `{FOLDER_ID}_session_{TIMESTAMP}.log` - Complete session log with DEBUG-level information

All directories are created automatically when the script runs.

## File Protection

The following file types are **never** suggested for deletion (even if duplicates are found):
- Photos (JPG, PNG, etc.)
- Videos (MP4, MOV, etc.)
- Audio files (MP3, M4A, etc.)

**Important:** Files are moved to Google Drive trash, not permanently deleted. You can recover them from trash if needed.

**Shared files/folders** are automatically excluded:
- Files and folders shared with you (but not owned by you) are excluded from all scans
- Only files you own are analyzed and considered for deletion
- This prevents suggesting deletion of files in someone else's Drive

## Configuration

### AWS Bedrock Settings

Default: `dev` profile in `us-east-1` region

Customize with:
```bash
--aws-profile YOUR_PROFILE --aws-region YOUR_REGION
```

### Analysis Depth

Default: Up to 10,000 files

Customize with:
```bash
--max-files 5000
```

### Minimum Age Threshold

Default: Files older than 90 days are considered for deletion

Customize the minimum age threshold:
```bash
# Flag files older than 30 days
--min-age-days 30

# Flag files older than 180 days (6 months)
--min-age-days 180
```

**How it works:**
- Files younger than the threshold are never flagged for deletion
- Files older than the threshold receive at least LOW confidence
- Very old files (> 1 year) get higher confidence scores
- Combine with other criteria (filename patterns, size) for better accuracy

### Checksum Cache

For faster duplicate detection, the tool caches MD5 checksums of all files in your Drive.

**Default behavior:**
- First run: Scans entire Drive to build cache (stored in `state/drive_checksums_cache.json`)
- Subsequent runs: Loads checksums from cache (much faster)

**Force refresh the cache:**
```bash
# Rescan entire Drive to update checksum cache
uv run python clean_obsolete.py FOLDER_ID --refresh_checksums
```

**When to refresh:**
- After adding/modifying many files in your Drive
- If duplicate detection seems outdated
- Cache file is automatically created/updated as needed

## Logging

The tool provides comprehensive logging:

- **Console output**: INFO level messages (colored, user-friendly)
- **Log files**: DEBUG level messages in `logs/` directory
  - Includes detailed API calls, authentication steps, and error traces
  - Useful for troubleshooting and audit trails
  - One log file per session with timestamp

Log files include:
- Full authentication process
- Every file scanned with metadata
- All deletion operations with results
- Detailed error messages with stack traces
- Performance metrics

## Development

### Running from source

```bash
uv run python clean_obsolete.py --help
```

### Running tests

```bash
uv run pytest
```

## License

MIT

## Author

Created with assistance from Claude Opus 4.6
