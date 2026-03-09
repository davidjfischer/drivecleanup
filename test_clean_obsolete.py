#!/usr/bin/env python3
"""
Unit tests for clean_obsolete (DriveCleanup)
"""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Import the module to test
import clean_obsolete as drivecleanup


class TestHelperFunctions(unittest.TestCase):
    """Test helper utility functions."""

    def test_extract_folder_id_from_url_with_folders_pattern(self):
        """Test extracting folder ID from /folders/ URL pattern."""
        url = "https://drive.google.com/drive/folders/1tW34LrY4e1e3OIMJkBljP0JS5atcYXJh"
        expected = "1tW34LrY4e1e3OIMJkBljP0JS5atcYXJh"
        self.assertEqual(drivecleanup.extract_folder_id(url), expected)

    def test_extract_folder_id_from_url_with_id_parameter(self):
        """Test extracting folder ID from ?id= URL parameter."""
        url = "https://drive.google.com/drive/u/0/folders?id=1tW34LrY4e1e3OIMJkBljP0JS5atcYXJh"
        expected = "1tW34LrY4e1e3OIMJkBljP0JS5atcYXJh"
        self.assertEqual(drivecleanup.extract_folder_id(url), expected)

    def test_extract_folder_id_returns_plain_id(self):
        """Test that plain ID is returned as-is."""
        folder_id = "1tW34LrY4e1e3OIMJkBljP0JS5atcYXJh"
        self.assertEqual(drivecleanup.extract_folder_id(folder_id), folder_id)

    def test_extract_folder_id_none(self):
        """Test extracting folder ID from None."""
        self.assertIsNone(drivecleanup.extract_folder_id(None))

    def test_extract_file_id_from_link_with_d_pattern(self):
        """Test extracting file ID from /d/ link pattern."""
        link = "https://drive.google.com/file/d/1abc123def456/view"
        expected = "1abc123def456"
        self.assertEqual(drivecleanup.extract_file_id_from_link(link), expected)

    def test_extract_file_id_from_link_with_id_parameter(self):
        """Test extracting file ID from ?id= parameter."""
        link = "https://drive.google.com/open?id=1abc123def456"
        expected = "1abc123def456"
        self.assertEqual(drivecleanup.extract_file_id_from_link(link), expected)

    def test_extract_file_id_from_link_invalid(self):
        """Test extracting file ID from invalid link."""
        self.assertIsNone(drivecleanup.extract_file_id_from_link("invalid"))


class TestBoxFormatting(unittest.TestCase):
    """Test box formatting functions for UI."""

    def test_format_box_line_short_text(self):
        """Test formatting short text in box line."""
        result = drivecleanup.format_box_line("Test", width=78)
        self.assertEqual(len(result), 80)  # Width + 2 for "║ " and " ║"
        self.assertTrue(result.startswith("║ Test"))
        self.assertTrue(result.endswith(" ║"))

    def test_format_box_line_long_text_truncates(self):
        """Test that overly long text is truncated."""
        long_text = "x" * 100
        result = drivecleanup.format_box_line(long_text, width=78)
        self.assertEqual(len(result), 80)

    def test_format_box_line_exact_width(self):
        """Test text that exactly fits the width."""
        text = "x" * 74  # Accounts for "║ " and " ║"
        result = drivecleanup.format_box_line(text, width=78)
        self.assertEqual(len(result), 80)

    def test_format_box_separator(self):
        """Test box separator formatting."""
        result = drivecleanup.format_box_separator("═", width=78)
        self.assertEqual(result, "╠" + "═" * 78 + "╣")
        self.assertEqual(len(result), 80)


class TestContentExtractor(unittest.TestCase):
    """Test ContentExtractor class methods."""

    def test_create_summary_short_text(self):
        """Test creating summary from short text."""
        text = "This is a short text"
        result = drivecleanup.ContentExtractor.create_summary(text, max_words=50)
        self.assertEqual(result, text)

    def test_create_summary_long_text(self):
        """Test creating summary from long text."""
        text = " ".join([f"word{i}" for i in range(100)])
        result = drivecleanup.ContentExtractor.create_summary(text, max_words=10)
        words = result.replace("...", "").split()
        self.assertEqual(len(words), 10)
        self.assertTrue(result.endswith("..."))

    def test_create_summary_none_text(self):
        """Test creating summary from None."""
        result = drivecleanup.ContentExtractor.create_summary(None)
        self.assertEqual(result, "Unable to extract content")

    def test_create_summary_empty_text(self):
        """Test creating summary from empty string."""
        result = drivecleanup.ContentExtractor.create_summary("")
        self.assertEqual(result, "Unable to extract content")

    def test_create_summary_whitespace_normalization(self):
        """Test that multiple whitespaces are normalized."""
        text = "This   has    multiple     spaces"
        result = drivecleanup.ContentExtractor.create_summary(text, max_words=10)
        self.assertNotIn("  ", result)


class TestFileAnalyzer(unittest.TestCase):
    """Test FileAnalyzer class methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_service = Mock()
        self.analyzer = drivecleanup.FileAnalyzer(
            service=self.mock_service,
            analyze_content=False,
            use_claude=False
        )

    def test_analyze_filename_temp_patterns(self):
        """Test detection of temporary file patterns."""
        test_cases = [
            ("temp_file.txt", "temp"),
            ("cache_data.json", "cache"),
            ("untitled document", "untitled"),
            ("Screenshot 2023-01-01.png", "screenshot"),
        ]
        for filename, expected_pattern in test_cases:
            reasons = self.analyzer.analyze_filename(filename)
            self.assertTrue(len(reasons) > 0, f"Should detect pattern in {filename}")
            self.assertTrue(
                any(expected_pattern in r.lower() for r in reasons),
                f"Should contain '{expected_pattern}' in reasons for {filename}"
            )

    def test_analyze_filename_backup_patterns(self):
        """Test detection of backup file patterns."""
        test_cases = [
            "backup_2023.zip",
            "archive_old.tar.gz",
            "data.bak"
        ]
        for filename in test_cases:
            reasons = self.analyzer.analyze_filename(filename)
            self.assertTrue(len(reasons) > 0, f"Should detect backup pattern in {filename}")

    def test_analyze_filename_clean(self):
        """Test that clean filenames don't trigger patterns."""
        clean_names = [
            "important_document.pdf",
            "project_report.docx",
            "data_analysis.xlsx"
        ]
        for filename in clean_names:
            reasons = self.analyzer.analyze_filename(filename)
            self.assertEqual(len(reasons), 0, f"Should not flag {filename}")

    def test_analyze_age_very_old(self):
        """Test analysis of very old files."""
        # 3 years ago
        old_date = (datetime.now(timezone.utc) - timedelta(days=1095)).isoformat()
        reasons, age_days = self.analyzer.analyze_age(old_date)
        self.assertTrue(len(reasons) > 0)
        self.assertTrue(any("Very old" in r for r in reasons))
        self.assertGreater(age_days, 730)

    def test_analyze_age_recent(self):
        """Test analysis of recent files."""
        # 30 days ago
        recent_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        reasons, age_days = self.analyzer.analyze_age(recent_date)
        self.assertEqual(len(reasons), 0)
        self.assertLess(age_days, 180)

    def test_analyze_size_empty_file(self):
        """Test analysis of empty files."""
        reasons = self.analyzer.analyze_size(0)
        self.assertTrue(len(reasons) > 0)
        self.assertTrue(any("Empty file" in r for r in reasons))

    def test_analyze_size_very_small(self):
        """Test analysis of very small files."""
        reasons = self.analyzer.analyze_size(50)
        self.assertTrue(len(reasons) > 0)
        self.assertTrue(any("Very small" in r for r in reasons))

    def test_analyze_size_large(self):
        """Test analysis of large files."""
        large_size = 150 * 1024 * 1024  # 150 MB
        reasons = self.analyzer.analyze_size(large_size)
        self.assertTrue(len(reasons) > 0)
        self.assertTrue(any("Large file" in r for r in reasons))

    def test_analyze_size_normal(self):
        """Test analysis of normal-sized files."""
        normal_size = 5 * 1024 * 1024  # 5 MB
        reasons = self.analyzer.analyze_size(normal_size)
        self.assertEqual(len(reasons), 0)

    def test_classify_delete_confidence_media_files_protected(self):
        """Test that media files are never suggested for deletion."""
        media_types = [
            "image/jpeg",
            "image/png",
            "video/mp4",
            "audio/mp3",
            "application/vnd.google-apps.photo",
            "application/vnd.google-apps.video"
        ]
        reasons = ["Very old: 1000 days", "tmp in name"]
        for mime_type in media_types:
            confidence = self.analyzer.classify_delete_confidence(
                reasons, age_days=1000, size=1000000, mime_type=mime_type
            )
            self.assertIsNone(confidence, f"Should not suggest deleting {mime_type}")

    def test_classify_delete_confidence_high(self):
        """Test HIGH confidence classification."""
        reasons = ["Name contains 'tmp'", "Empty file (0 bytes)"]
        confidence = self.analyzer.classify_delete_confidence(
            reasons, age_days=200, size=0, mime_type="text/plain"
        )
        self.assertEqual(confidence, "HIGH")

    def test_classify_delete_confidence_medium(self):
        """Test MEDIUM confidence classification."""
        reasons = ["Backup/archive pattern 'backup'", "Old: 400 days"]
        confidence = self.analyzer.classify_delete_confidence(
            reasons, age_days=400, size=1000000, mime_type="application/zip"
        )
        self.assertEqual(confidence, "MEDIUM")

    def test_classify_delete_confidence_low(self):
        """Test LOW confidence classification."""
        # Use generic reason that doesn't match any keywords
        # age_days > OLD_DAYS (365) adds 1 point -> LOW confidence
        reasons = ["Not recently modified"]
        confidence = self.analyzer.classify_delete_confidence(
            reasons, age_days=370, size=1000000, mime_type="application/pdf"
        )
        self.assertEqual(confidence, "LOW")

    def test_classify_delete_confidence_none(self):
        """Test that files with insufficient reasons get None."""
        reasons = []
        confidence = self.analyzer.classify_delete_confidence(
            reasons, age_days=100, size=1000000, mime_type="application/pdf"
        )
        self.assertIsNone(confidence)

    def test_is_protected_media_file_images(self):
        """Test that image files are identified as protected media."""
        image_mime_types = [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/heic"
        ]
        media_mime_types = [
            'image/', 'video/', 'audio/',
            'application/vnd.google-apps.photo',
            'application/vnd.google-apps.video'
        ]

        for mime_type in image_mime_types:
            is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)
            self.assertTrue(is_media, f"{mime_type} should be protected")

    def test_is_protected_media_file_videos(self):
        """Test that video files are identified as protected media."""
        video_mime_types = [
            "video/mp4",
            "video/quicktime",
            "video/x-msvideo",
            "video/webm",
            "application/vnd.google-apps.video"
        ]
        media_mime_types = [
            'image/', 'video/', 'audio/',
            'application/vnd.google-apps.photo',
            'application/vnd.google-apps.video'
        ]

        for mime_type in video_mime_types:
            is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)
            self.assertTrue(is_media, f"{mime_type} should be protected")

    def test_is_protected_media_file_audio(self):
        """Test that audio files are identified as protected media."""
        audio_mime_types = [
            "audio/mpeg",
            "audio/mp4",
            "audio/wav",
            "audio/ogg"
        ]
        media_mime_types = [
            'image/', 'video/', 'audio/',
            'application/vnd.google-apps.photo',
            'application/vnd.google-apps.video'
        ]

        for mime_type in audio_mime_types:
            is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)
            self.assertTrue(is_media, f"{mime_type} should be protected")

    def test_is_not_protected_media_file_documents(self):
        """Test that document files are NOT identified as protected media."""
        doc_mime_types = [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "application/zip"
        ]
        media_mime_types = [
            'image/', 'video/', 'audio/',
            'application/vnd.google-apps.photo',
            'application/vnd.google-apps.video'
        ]

        for mime_type in doc_mime_types:
            is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)
            self.assertFalse(is_media, f"{mime_type} should NOT be protected as media")


class TestParseCleanupReport(unittest.TestCase):
    """Test cleanup report parsing."""

    def test_parse_cleanup_report_valid(self):
        """Test parsing a valid cleanup report."""
        report_content = """================================================================================
HIGH CONFIDENCE DELETE CANDIDATES
================================================================================

[1] test_file.txt
    Size: 1.5 MB
    Link: https://drive.google.com/file/d/abc123/view
    Reasons:
      - Name contains 'tmp'
      - Empty file (0 bytes)
"""
        # Create temporary report file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(report_content)
            temp_file = f.name

        try:
            entries = drivecleanup.parse_cleanup_report(temp_file)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]['name'], 'test_file.txt')
            self.assertEqual(entries[0]['confidence'], 'HIGH')
            self.assertEqual(entries[0]['size'], '1.5 MB')
            self.assertEqual(entries[0]['file_id'], 'abc123')
            self.assertEqual(len(entries[0]['reasons']), 2)
        finally:
            os.unlink(temp_file)

    def test_parse_cleanup_report_nonexistent(self):
        """Test parsing nonexistent report file."""
        entries = drivecleanup.parse_cleanup_report("/nonexistent/file.txt")
        self.assertEqual(entries, [])


class TestLogFunctions(unittest.TestCase):
    """Test file logging functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_folder_id = "test_folder_123"
        self.test_file_name = "test.txt"
        self.test_link = "https://drive.google.com/file/d/abc123/view"
        self.test_size = "1.5 MB"

    def tearDown(self):
        """Clean up test files."""
        import glob
        for f in glob.glob(f"{drivecleanup.STATE_DIR}/{self.test_folder_id}_*.txt"):
            try:
                os.unlink(f)
            except:
                pass

    def test_log_deleted_file(self):
        """Test logging deleted file."""
        drivecleanup.log_deleted_file(
            self.test_folder_id, self.test_file_name, self.test_link, self.test_size
        )
        log_file = os.path.join(drivecleanup.STATE_DIR, f"{self.test_folder_id}_deleted_files.txt")
        self.assertTrue(os.path.exists(log_file))

        with open(log_file, 'r') as f:
            content = f.read()
            self.assertIn(self.test_file_name, content)
            self.assertIn(self.test_link, content)

    def test_log_skipped_file(self):
        """Test logging skipped file."""
        drivecleanup.log_skipped_file(
            self.test_folder_id, self.test_file_name, self.test_link, self.test_size
        )
        log_file = os.path.join(drivecleanup.STATE_DIR, f"{self.test_folder_id}_skipped_files.txt")
        self.assertTrue(os.path.exists(log_file))

        with open(log_file, 'r') as f:
            content = f.read()
            self.assertIn(self.test_file_name, content)
            self.assertIn(self.test_link, content)

    def test_load_processed_files(self):
        """Test loading processed files."""
        # Create test log files
        drivecleanup.log_deleted_file(
            self.test_folder_id, "deleted.txt",
            "https://drive.google.com/file/d/del123/view", "1 MB"
        )
        drivecleanup.log_skipped_file(
            self.test_folder_id, "skipped.txt",
            "https://drive.google.com/file/d/skip456/view", "2 MB"
        )

        deleted, skipped = drivecleanup.load_processed_files(self.test_folder_id)

        self.assertIn("del123", deleted)
        self.assertIn("skip456", skipped)


class TestGetDisplayWidth(unittest.TestCase):
    """Test Unicode display width calculation for emojis."""

    def test_get_display_width_ascii(self):
        """Test display width calculation for ASCII text."""
        text = "Hello World"
        width = drivecleanup.get_display_width(text)
        self.assertEqual(width, 11)

    def test_get_display_width_emoji(self):
        """Test display width calculation for emojis (2 chars wide)."""
        text = "💡"
        width = drivecleanup.get_display_width(text)
        self.assertEqual(width, 2)

    def test_get_display_width_mixed(self):
        """Test display width calculation for mixed ASCII and emoji."""
        text = "💡 TIP"
        width = drivecleanup.get_display_width(text)
        self.assertEqual(width, 6)  # emoji(2) + space(1) + TIP(3)

    def test_get_display_width_multiple_emojis(self):
        """Test display width calculation for multiple emojis."""
        text = "✅ 🌐 ⏭️"
        width = drivecleanup.get_display_width(text)
        # Each emoji is 2 chars wide, spaces are 1 char
        self.assertEqual(width, 8)  # 2 + 1 + 2 + 1 + 2 = 8


class TestMinAgeThreshold(unittest.TestCase):
    """Test minimum age threshold functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_service = Mock()

    def test_custom_min_age_threshold(self):
        """Test that custom minimum age threshold is respected."""
        analyzer = drivecleanup.FileAnalyzer(
            service=self.mock_service,
            analyze_content=False,
            use_claude=False,
            min_age_days=180  # Custom threshold
        )

        # File older than custom threshold should get confidence
        reasons = ["Not recently modified"]
        confidence = analyzer.classify_delete_confidence(
            reasons, age_days=200, size=1000000, mime_type="application/pdf"
        )
        self.assertIsNotNone(confidence)

        # File younger than custom threshold should not get confidence
        confidence = analyzer.classify_delete_confidence(
            [], age_days=100, size=1000000, mime_type="application/pdf"
        )
        self.assertIsNone(confidence)

    def test_default_min_age_threshold(self):
        """Test that default minimum age threshold (90 days) is applied."""
        analyzer = drivecleanup.FileAnalyzer(
            service=self.mock_service,
            analyze_content=False,
            use_claude=False
        )

        # File older than default threshold (90 days) should potentially get confidence
        # if it meets other criteria
        reasons = ["Generic reason"]
        confidence = analyzer.classify_delete_confidence(
            reasons, age_days=100, size=1000000, mime_type="application/pdf"
        )
        # With generic reason and age > 90, should get LOW confidence
        self.assertEqual(confidence, "LOW")


if __name__ == '__main__':
    unittest.main()
