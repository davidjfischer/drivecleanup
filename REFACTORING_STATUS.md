# Refactoring Status

## Completed ✅

### New Modular Structure

The project has been split into specialized scripts:

#### 1. `clean_duplicates.py` - MD5-based Duplicate Detection
**Purpose:** Find and clean duplicate files based on MD5 checksums

**Usage:**
```bash
# Build MD5 checksum cache by scanning entire Drive
python clean_duplicates.py --checksums

# Interactive cleanup of duplicates in a folder
python clean_duplicates.py --clean FOLDER_ID

# Refresh cache and clean in one step
python clean_duplicates.py --checksums --clean FOLDER_ID
```

**Features:**
- Scans entire Google Drive for MD5 checksums
- Caches results for fast subsequent runs
- Identifies duplicates across entire Drive
- Protects media files (photos, videos, audio) from deletion
- Interactive cleanup with full file paths displayed

#### 2. `clean_obsolete.py` - Content Analysis & Cleanup
**Purpose:** Analyze file content with Claude AI and clean based on analysis

**Usage:**
```bash
# Full workflow: Analyze and clean
python clean_obsolete.py FOLDER_ID

# Analysis only
python clean_obsolete.py FOLDER_ID --analyze

# Cleanup only (uses existing report)
python clean_obsolete.py FOLDER_ID --clean

# Without Claude AI (faster, simpler)
python clean_obsolete.py FOLDER_ID --no-claude
```

**Features:**
- Content extraction from PDFs, Word docs, Google Docs, etc.
- Claude AI intelligent summarization via AWS Bedrock
- Filename pattern analysis (temp, cache, backup, etc.)
- Age-based detection (configurable minimum age)
- Size-based detection (very small, very large files)
- Empty folder detection
- Interactive cleanup

#### 3. `cleanup_core.py` - Shared Cleanup Module
**Purpose:** Common interactive cleanup logic used by both scripts

**Contains:**
- `interactive_cleanup()` - Main interactive dialog
- `parse_cleanup_report()` - JSON report parser
- UI functions: `format_box_line()`, `print_colored_tip_box()`, etc.
- Logging functions: `log_deleted_file()`, `log_skipped_file()`, `load_processed_files()`
- Helper functions: `get_single_key()`, `extract_file_id_from_link()`

### Interactive Cleanup Options

Both scripts use the same interactive cleanup interface:
- `(1) Delete` - Move file to Google Drive trash
- `(2) Browser` - Open file in browser for review
- `(3) Skip` - Mark file as skipped (won't be shown again)
- `(4) Next` - Move to next file without marking as skipped
- `(q) Quit` - Exit cleanup session

### File Protection

Media files are **never** suggested for deletion:
- Photos (JPG, PNG, HEIC, etc.)
- Videos (MP4, MOV, etc.)
- Audio files (MP3, M4A, WAV, etc.)

This protection applies even when duplicates are found.

## Recommended Workflow

### For Duplicate Cleanup:
```bash
# Step 1: Build checksum cache (do this once, or when you've added many files)
python clean_duplicates.py --checksums

# Step 2: Clean duplicates in a specific folder
python clean_duplicates.py --clean "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### For Content-Based Cleanup:
```bash
# Analyze and clean in one session
python clean_obsolete.py "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### Combined Approach:
```bash
# 1. First, clean duplicates (fast, high confidence)
python clean_duplicates.py --checksums --clean FOLDER_ID

# 2. Then, analyze remaining files with content analysis
python clean_obsolete.py FOLDER_ID --analyze --clean
```

## Pending Tasks 🔄

### `clean_obsolete.py` Further Refactoring (Optional)

The current `clean_obsolete.py` still contains some duplicated code that could be cleaned up:
1. Remove `--refresh_checksums` option (now in `clean_duplicates.py`)
2. Remove duplicate UI functions (already in `cleanup_core.py`)
3. Remove duplicate `interactive_cleanup()` function (use import from `cleanup_core`)
4. Remove duplicate helper functions (already in `utils.py` or `cleanup_core.py`)

**Impact:** This would reduce `clean_obsolete.py` from ~2230 lines to ~1200 lines, but is not critical for functionality.

**Note:** The current version works correctly - these are code cleanup improvements only.

## Benefits of New Structure

1. **Separation of Concerns**
   - Duplicate detection is independent of content analysis
   - Each script has a single, clear purpose

2. **Faster Duplicate Detection**
   - MD5-based duplicate detection is very fast
   - No need to run content analysis for obvious duplicates

3. **Reusable Cleanup Logic**
   - `cleanup_core.py` provides shared interactive cleanup
   - Both scripts use the same proven cleanup interface

4. **Independent Operation**
   - Can run duplicate cleanup without AWS Bedrock setup
   - Can run content analysis without building checksum cache

5. **Better Testing**
   - Each module can be tested independently
   - Easier to identify and fix issues

## Migration from Old Version

If you were using the old combined script:

**Old:**
```bash
python clean_obsolete.py FOLDER_ID --refresh_checksums --analyze --clean
```

**New:**
```bash
# Duplicate cleanup (replaces --refresh_checksums)
python clean_duplicates.py --checksums --clean FOLDER_ID

# Content analysis and cleanup (replaces --analyze --clean)
python clean_obsolete.py FOLDER_ID --analyze --clean
```

Or run them separately for better control:
```bash
# Step 1: Duplicates only
python clean_duplicates.py --checksums
python clean_duplicates.py --clean FOLDER_ID

# Step 2: Content analysis
python clean_obsolete.py FOLDER_ID
```

## Testing Recommendations

1. **Test `clean_duplicates.py` first:**
   ```bash
   python clean_duplicates.py --checksums
   python clean_duplicates.py --clean YOUR_TEST_FOLDER_ID
   ```

2. **Then test `clean_obsolete.py`:**
   ```bash
   python clean_obsolete.py YOUR_TEST_FOLDER_ID --no-claude
   ```

3. **Verify report formats:**
   - Check `reports/duplicate_report_*.json`
   - Check `reports/drive_cleanup_report_*.json`

4. **Verify logging:**
   - Check `logs/*_session_*.log`
   - Check `state/*_deleted_files.txt`
   - Check `state/*_skipped_files.txt`
