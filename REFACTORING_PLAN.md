# Code Refactoring Plan

## Goal
Split the monolithic 1868-line `drivecleanup.py` file into modular components for better maintainability.

## Completed ✅

### 1. prompts/claude_file_analysis.txt
- Extracted Claude prompt template to separate text file
- Template uses `{file_name}` and `{text}` placeholders
- Loaded dynamically in `content_extractor.py`

### 2. config.py
- All configuration constants
- OAuth scopes
- Directory paths
- UI box formatting constants
- Content extraction limits
- Analysis limits
- File patterns and thresholds

### 3. utils.py
- `setup_file_logging()` - Session logging setup
- `authenticate()` - Google Drive API authentication
- `extract_folder_id()` - URL/ID extraction
- `extract_file_id_from_link()` - File ID extraction
- `find_latest_report()` - Report file lookup
- `get_single_key()` - Single-key input (cross-platform)
- `log_deleted_file()` - Deletion logging
- `log_skipped_file()` - Skip logging
- `load_processed_files()` - Load processed file IDs
- `parse_cleanup_report()` - Parse report files

### 4. content_extractor.py
- `ContentExtractor` class - Text extraction from files
- Methods for Google Docs, Sheets, Slides
- PDF, Word, Excel extraction
- Claude summary generation (loads prompt from file)
- Fallback summary generation

## Remaining Tasks 🔄

### 5. file_analyzer.py
- `FileAnalyzer` class
- File scanning methods (`scan_folder`, `scan_drive`)
- Analysis methods (`analyze_files`, `analyze_filename`, `analyze_age`, `analyze_size`)
- Confidence classification
- Duplicate detection
- Empty folder detection
- Report generation

### 6. ui.py
- `format_box_line()` - Box line formatting
- `format_box_separator()` - Separator formatting
- `print_colored_tip_box()` - Colored tip boxes
- `interactive_cleanup()` - Interactive cleanup UI

### 7. drivecleanup.py (refactored)
- Import all modules
- `main()` function only
- Command-line argument parsing
- Workflow orchestration

### 8. test_drivecleanup.py (update)
- Update imports to use new modules
- Ensure all tests still pass

## Module Dependencies

```
drivecleanup.py (main)
├── config.py
├── utils.py
│   └── config.py
├── content_extractor.py
│   ├── config.py
│   └── prompts/claude_file_analysis.txt
├── file_analyzer.py
│   ├── config.py
│   ├── content_extractor.py
│   └── utils.py (for get_file_path)
└── ui.py
    ├── config.py
    └── utils.py
```

## Benefits

1. **Better Organization** - Each module has a single responsibility
2. **Easier Testing** - Can test modules independently
3. **Improved Maintainability** - Changes isolated to specific modules
4. **Clearer Dependencies** - Explicit imports show relationships
5. **Reusability** - Modules can be used independently
6. **Easier Onboarding** - Smaller files are easier to understand

## File Sizes (Target)

- `config.py`: ~70 lines
- `utils.py`: ~300 lines
- `content_extractor.py`: ~320 lines
- `file_analyzer.py`: ~600 lines
- `ui.py`: ~350 lines
- `drivecleanup.py`: ~200 lines (main only)

Total: ~1840 lines (vs 1868 lines monolithic)

## Next Steps

1. Create `ui.py` with UI functions
2. Create `file_analyzer.py` with FileAnalyzer class
3. Refactor `drivecleanup.py` to import and orchestrate
4. Update `test_drivecleanup.py` imports
5. Run all tests to verify refactoring
6. Update documentation
7. Commit and push
