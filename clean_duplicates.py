#!/usr/bin/env python3
"""
Duplicate Cleanup Tool - MD5-based duplicate file detection for Google Drive.

This script scans your Google Drive for duplicate files based on MD5 checksums
and provides an interactive cleanup interface.

Features:
- Detects duplicates in binary files (PDFs, images, etc.) using native MD5 checksums
- Detects duplicates in Google Workspace files (Docs, Sheets, Slides, Drawings)
  by exporting and computing content MD5
- Protects media files (photos, videos, audio) from deletion

Usage:
    # Scan entire Drive and build MD5 checksum cache
    python clean_duplicates.py --checksums

    # Interactive cleanup of ALL duplicates across entire Drive
    python clean_duplicates.py --clean

    # Interactive cleanup in specific folder only
    python clean_duplicates.py --clean FOLDER_ID

    # Refresh cache and clean entire Drive
    python clean_duplicates.py --checksums --clean
"""

import os
import sys
import argparse
import json
import pickle
import re
import hashlib
import io
import tempfile
from datetime import datetime, timezone
from collections import defaultdict
from loguru import logger
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Import shared modules
from config import SCOPES_READONLY, SCOPES_WRITE, STATE_DIR, REPORTS_DIR, LOGS_DIR, CHECKSUMS_CACHE_FILE
from utils import setup_file_logging, extract_folder_id
from cleanup_core import interactive_cleanup

# ============================================================================
# AUTHENTICATION
# ============================================================================

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


# ============================================================================
# DUPLICATE SCANNER
# ============================================================================

class DuplicateScanner:
    """Scanner for duplicate files based on MD5 checksums."""

    def __init__(self, service):
        self.service = service
        self.md5_to_files = defaultdict(list)
        self.folder_id_to_name = {}
        self.folder_id_to_parents = {}
        # Map for Google Workspace files: file_id -> content_md5
        self.workspace_content_md5 = {}

    def _compute_content_md5(self, file_id, mime_type, file_name=None):
        """Compute MD5 checksum of Google Workspace file by exporting it.

        Args:
            file_id: Google Drive file ID
            mime_type: MIME type of the file
            file_name: Optional file name for logging

        Returns:
            MD5 checksum string or None if export fails
        """
        # Map Google Workspace MIME types to export formats
        export_formats = {
            'application/vnd.google-apps.document': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'Word (.docx)'),
            'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'Excel (.xlsx)'),
            'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', 'PowerPoint (.pptx)'),
            'application/vnd.google-apps.drawing': ('application/pdf', 'PDF'),
        }

        export_info = export_formats.get(mime_type)
        if not export_info:
            return None

        export_mime, format_name = export_info

        try:
            # Log the conversion
            if file_name:
                logger.debug(f"Converting Google Workspace file to {format_name}: {file_name}")
            else:
                logger.debug(f"Converting Google Workspace file ({file_id}) to {format_name}")

            # Export file
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType=export_mime
            )

            # Download to memory
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()

            # Compute MD5
            fh.seek(0)
            md5_hash = hashlib.md5()
            md5_hash.update(fh.read())

            checksum = md5_hash.hexdigest()
            if file_name:
                logger.debug(f"Successfully computed MD5 for {file_name}: {checksum[:8]}...")
            return checksum

        except Exception as e:
            if file_name:
                logger.warning(f"Failed to compute content MD5 for {file_name}: {e}")
            else:
                logger.debug(f"Failed to compute content MD5 for {file_id}: {e}")
            return None

    def scan_drive_for_checksums(self, refresh_cache=False):
        """Scan entire Drive to build MD5 checksum cache.

        Args:
            refresh_cache: If True, ignore cache and rescan entire Drive

        Returns:
            True if successful, False otherwise
        """
        # Try to load from cache if not refreshing
        if not refresh_cache and os.path.exists(CHECKSUMS_CACHE_FILE):
            logger.info("Loading MD5 checksums and folder structure from cache...")
            try:
                with open(CHECKSUMS_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)

                # Reconstruct md5_to_files from cache
                for md5, files_list in cache_data.get('checksums', {}).items():
                    self.md5_to_files[md5] = files_list

                # Reconstruct folder_id_to_name and folder_id_to_parents from cache
                self.folder_id_to_name.update(cache_data.get('folders', {}))
                self.folder_id_to_parents.update(cache_data.get('folder_parents', {}))

                # Reconstruct workspace_content_md5 from cache
                self.workspace_content_md5.update(cache_data.get('workspace_md5', {}))

                total_files = sum(len(files) for files in self.md5_to_files.values())
                workspace_files = len(self.workspace_content_md5)
                logger.info(f"Loaded {total_files} files with MD5 checksums from cache")
                logger.info(f"Loaded {workspace_files} workspace files with content MD5 from cache")
                logger.info(f"Loaded {len(self.folder_id_to_name)} folder mappings from cache")
                logger.info(f"Found {len(self.md5_to_files)} unique checksums")

                # If cache is empty, rescan instead of using it
                if total_files == 0:
                    logger.warning("Cache is empty, will rescan entire Drive")
                else:
                    return True  # Cache loaded successfully with data
            except Exception as e:
                logger.warning(f"Failed to load cache, will rescan: {e}")

        # Scan entire Drive for checksums and folder structure
        if refresh_cache:
            logger.info("Refreshing MD5 checksum cache (scanning entire Drive)...")
        else:
            logger.info("Building MD5 checksum cache (scanning entire Drive)...")

        page_token = None
        scanned_files = 0
        scanned_folders = 0

        # First, scan all folders to build folder hierarchy
        logger.info("  Scanning folder structure...")
        page_token = None
        while True:
            try:
                results = self.service.files().list(
                    pageSize=1000,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, parents, trashed)",
                    q="mimeType = 'application/vnd.google-apps.folder' and trashed=false and 'me' in owners"
                ).execute()

                items = results.get('files', [])

                for item in items:
                    scanned_folders += 1
                    self.folder_id_to_name[item['id']] = item['name']

                    if 'parents' in item:
                        self.folder_id_to_parents[item['id']] = item['parents']

                    if scanned_folders % 500 == 0:
                        logger.info(f"    Scanned {scanned_folders} folders...")

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"Error scanning folders: {e}")
                break

        logger.info(f"  Scanned {scanned_folders} folders")

        # Now scan all files with MD5 checksums
        logger.info("  Scanning files for checksums...")
        page_token = None
        while True:
            try:
                results = self.service.files().list(
                    pageSize=1000,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, parents, md5Checksum, size, modifiedTime, webViewLink)",
                    q="trashed=false and mimeType != 'application/vnd.google-apps.folder' and 'me' in owners"
                ).execute()

                items = results.get('files', [])

                for item in items:
                    scanned_files += 1

                    if scanned_files % 500 == 0:
                        logger.info(f"    Scanned {scanned_files} files...")

                    # Track files by MD5 for duplicate detection (if available)
                    if 'md5Checksum' in item:
                        self.md5_to_files[item['md5Checksum']].append(item)

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"Error scanning files: {e}")
                break

        logger.info(f"Scan complete: {scanned_files} files and {scanned_folders} folders")

        # Now scan Google Workspace files (Docs, Sheets, Slides) and compute content MD5
        logger.info("  Scanning Google Workspace files (Docs, Sheets, Slides)...")
        workspace_mimetypes = [
            'application/vnd.google-apps.document',
            'application/vnd.google-apps.spreadsheet',
            'application/vnd.google-apps.presentation',
            'application/vnd.google-apps.drawing'
        ]

        workspace_scanned = 0
        workspace_with_md5 = 0

        for mime_type in workspace_mimetypes:
            page_token = None
            while True:
                try:
                    results = self.service.files().list(
                        pageSize=100,  # Smaller batches for workspace files (export is expensive)
                        pageToken=page_token,
                        fields="nextPageToken, files(id, name, mimeType, parents, size, modifiedTime, webViewLink)",
                        q=f"trashed=false and mimeType = '{mime_type}' and 'me' in owners"
                    ).execute()

                    items = results.get('files', [])

                    for item in items:
                        workspace_scanned += 1

                        if workspace_scanned % 50 == 0:
                            logger.info(f"    Processing {workspace_scanned} workspace files...")

                        # Compute content MD5 by exporting
                        logger.info(f"    Exporting workspace file: {item['name']}")
                        content_md5 = self._compute_content_md5(item['id'], item['mimeType'], item['name'])

                        if content_md5:
                            workspace_with_md5 += 1
                            # Store in workspace map
                            self.workspace_content_md5[item['id']] = content_md5
                            # Add to md5_to_files with a special marker
                            item['md5Checksum'] = content_md5  # Add MD5 to item for consistency
                            item['is_workspace'] = True  # Mark as workspace file
                            self.md5_to_files[content_md5].append(item)

                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break

                except Exception as e:
                    logger.error(f"Error scanning workspace files: {e}")
                    break

        logger.info(f"Scanned {workspace_scanned} workspace files, computed {workspace_with_md5} content MD5s")

        # Save to cache (checksums and folder structure)
        try:
            logger.debug(f"Saving MD5 checksum cache to {CHECKSUMS_CACHE_FILE}")
            cache_data = {
                'checksums': dict(self.md5_to_files),
                'folders': self.folder_id_to_name,
                'folder_parents': self.folder_id_to_parents,
                'workspace_md5': self.workspace_content_md5
            }
            with open(CHECKSUMS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            logger.info("MD5 checksum and folder structure cache saved successfully")
        except Exception as e:
            logger.warning(f"Failed to save checksum cache: {e}")
            return False

        return True

    def get_file_path(self, file_item):
        """Build the full path to a file from its parent folders."""
        path_parts = [file_item['name']]
        parents = file_item.get('parents', [])

        # Walk up the parent chain
        visited = set()
        while parents and len(parents) > 0:
            parent_id = parents[0]

            # Avoid infinite loops
            if parent_id in visited:
                break
            visited.add(parent_id)

            # Get parent folder name
            if parent_id in self.folder_id_to_name:
                path_parts.insert(0, self.folder_id_to_name[parent_id])

            # Find parent's parents using cached mapping
            if parent_id in self.folder_id_to_parents:
                parents = self.folder_id_to_parents[parent_id]
            else:
                parents = []

        return '/'.join(path_parts)

    def find_duplicates_in_folder(self, folder_id):
        """Find duplicate files within a specific folder.

        Args:
            folder_id: The folder ID to search for duplicates

        Returns:
            List of duplicate candidates for deletion
        """
        logger.info(f"Finding duplicates in folder: {folder_id}")

        # Get all files in the folder (including Google Workspace files)
        folder_files = []
        page_token = None

        while True:
            try:
                results = self.service.files().list(
                    pageSize=1000,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents, md5Checksum, webViewLink)",
                    q=f"'{folder_id}' in parents and trashed=false and 'me' in owners"
                ).execute()

                items = results.get('files', [])

                for item in items:
                    # Include files with native MD5
                    if 'md5Checksum' in item:
                        folder_files.append(item)
                    # Include Google Workspace files if we have content MD5 for them
                    elif item['id'] in self.workspace_content_md5:
                        logger.debug(f"Using cached content MD5 for workspace file: {item['name']}")
                        item['md5Checksum'] = self.workspace_content_md5[item['id']]
                        item['is_workspace'] = True
                        folder_files.append(item)

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"Error scanning folder: {e}")
                break

        workspace_count = sum(1 for f in folder_files if f.get('is_workspace'))
        logger.info(f"Found {len(folder_files)} files with MD5 in folder ({workspace_count} workspace files)")

        # Create set of file IDs in this folder
        folder_file_ids = {f['id'] for f in folder_files}

        # Find duplicates
        duplicates = []
        duplicates_found = 0

        for md5, files_with_hash in self.md5_to_files.items():
            if len(files_with_hash) > 1:
                # Check if any of these duplicates are in our folder
                duplicates_in_folder = [f for f in files_with_hash if f['id'] in folder_file_ids]

                if not duplicates_in_folder:
                    # None of these duplicates are in our folder, skip
                    continue

                # Find files OUTSIDE the folder to use as "original" reference
                files_outside_folder = [f for f in files_with_hash if f['id'] not in folder_file_ids]

                if files_outside_folder:
                    # Use oldest file outside folder as reference
                    sorted_outside = sorted(files_outside_folder, key=lambda f: f.get('modifiedTime', ''), reverse=False)
                    original_file = sorted_outside[0]
                    original_path = self.get_file_path(original_file)

                    # Mark ALL files in folder as duplicates
                    for duplicate_file in duplicates_in_folder:
                        mime_type = duplicate_file.get('mimeType', '')

                        # Check if this is a protected media file
                        media_mime_types = [
                            'image/', 'video/', 'audio/',
                            'application/vnd.google-apps.photo',
                            'application/vnd.google-apps.video'
                        ]
                        is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)

                        # Only mark duplicate if it's NOT a media file (photos/videos are protected)
                        if not is_media:
                            duplicates_found += 1
                            duplicate_path = self.get_file_path(duplicate_file)

                            size = int(duplicate_file.get('size', 0)) if 'size' in duplicate_file else 0
                            size_mb = size / (1024 * 1024)
                            if size_mb < 1:
                                size_formatted = f"{size / 1024:.1f} KB"
                            else:
                                size_formatted = f"{size_mb:.1f} MB"

                            # Add indicator if this is a workspace file content duplicate
                            reason_text = "Duplicate file"
                            if duplicate_file.get('is_workspace') or original_file.get('is_workspace'):
                                reason_text = "Duplicate content (workspace file)"
                            reason_text += f" - original at: {original_path}"

                            candidate = {
                                'id': duplicate_file['id'],
                                'name': duplicate_file['name'],
                                'path': duplicate_path,
                                'size': size,
                                'size_formatted': size_formatted,
                                'modified': duplicate_file.get('modifiedTime'),
                                'reasons': [reason_text],
                                'link': duplicate_file.get('webViewLink', 'N/A'),
                                'mime_type': mime_type,
                                'summary': None
                            }

                            duplicates.append(candidate)
                        else:
                            logger.debug(f"Skipping duplicate media file (protected): {duplicate_file.get('name', 'Unknown')}")
                else:
                    # All duplicates are in folder - keep oldest, mark rest as duplicates
                    sorted_in_folder = sorted(duplicates_in_folder, key=lambda f: f.get('modifiedTime', ''), reverse=False)
                    original_file = sorted_in_folder[0]
                    original_path = self.get_file_path(original_file)

                    # Mark all except the oldest as duplicates
                    for duplicate_file in sorted_in_folder[1:]:
                        mime_type = duplicate_file.get('mimeType', '')

                        # Check if this is a protected media file
                        media_mime_types = [
                            'image/', 'video/', 'audio/',
                            'application/vnd.google-apps.photo',
                            'application/vnd.google-apps.video'
                        ]
                        is_media = any(mime_type.startswith(prefix) for prefix in media_mime_types)

                        # Only mark duplicate if it's NOT a media file
                        if not is_media:
                            duplicates_found += 1
                            duplicate_path = self.get_file_path(duplicate_file)

                            size = int(duplicate_file.get('size', 0)) if 'size' in duplicate_file else 0
                            size_mb = size / (1024 * 1024)
                            if size_mb < 1:
                                size_formatted = f"{size / 1024:.1f} KB"
                            else:
                                size_formatted = f"{size_mb:.1f} MB"

                            # Add indicator if this is a workspace file content duplicate
                            reason_text = "Duplicate file (in same folder)"
                            if duplicate_file.get('is_workspace') or original_file.get('is_workspace'):
                                reason_text = "Duplicate content (workspace file, in same folder)"
                            reason_text += f" - keep oldest at: {original_path}"

                            candidate = {
                                'id': duplicate_file['id'],
                                'name': duplicate_file['name'],
                                'path': duplicate_path,
                                'size': size,
                                'size_formatted': size_formatted,
                                'modified': duplicate_file.get('modifiedTime'),
                                'reasons': [reason_text],
                                'link': duplicate_file.get('webViewLink', 'N/A'),
                                'mime_type': mime_type,
                                'summary': None
                            }

                            duplicates.append(candidate)
                        else:
                            logger.debug(f"Skipping duplicate media file (protected): {duplicate_file.get('name', 'Unknown')}")

        logger.info(f"Found {duplicates_found} duplicate files to remove")
        return duplicates

    def find_duplicates_in_drive(self):
        """Find ALL duplicate files across entire Drive.

        Returns:
            List of duplicate candidates for deletion
        """
        logger.info("Finding duplicates across entire Drive...")

        # Find all files with duplicates (where MD5 appears more than once)
        duplicates = []
        duplicates_found = 0

        for md5, files_with_hash in self.md5_to_files.items():
            if len(files_with_hash) > 1:
                # Sort by modification time (oldest first)
                sorted_files = sorted(files_with_hash, key=lambda f: f.get('modifiedTime', ''), reverse=False)
                original_file = sorted_files[0]
                original_path = self.get_file_path(original_file)

                # Mark all except the oldest as duplicates
                for duplicate_file in sorted_files[1:]:
                    mime_type = duplicate_file.get('mimeType', '')

                    # Check if this is a protected media file
                    media_mime_types = [
                        'image/', 'video/', 'audio/',
                        'application/vnd.google-apps.photo',
                        'application/vnd.google-apps.video'
                    ]

                    # Also check file extensions
                    media_extensions = [
                        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.heic', '.heif',
                        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v',
                        '.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.wma'
                    ]

                    file_name_lower = duplicate_file.get('name', '').lower()
                    is_media = (
                        any(mime_type.startswith(prefix) for prefix in media_mime_types) or
                        any(file_name_lower.endswith(ext) for ext in media_extensions)
                    )

                    # Only mark duplicate if it's NOT a media file (photos/videos are protected)
                    if not is_media:
                        duplicates_found += 1
                        duplicate_path = self.get_file_path(duplicate_file)

                        # Determine if it's a workspace file
                        reason_text = "Duplicate file"
                        if duplicate_file.get('is_workspace') or original_file.get('is_workspace'):
                            reason_text = "Duplicate content (workspace file)"
                        reason_text += f" - original at: {original_path}"

                        candidate = {
                            'id': duplicate_file['id'],
                            'name': duplicate_file['name'],
                            'path': duplicate_path,
                            'size': int(duplicate_file.get('size', 0)) if 'size' in duplicate_file else 0,
                            'modified': duplicate_file.get('modifiedTime'),
                            'link': duplicate_file.get('webViewLink', 'N/A'),
                            'reasons': [reason_text]
                        }
                        duplicates.append(candidate)
                    else:
                        logger.debug(f"Skipping duplicate media file (protected): {duplicate_file.get('name', 'Unknown')}")

        logger.info(f"Found {duplicates_found} duplicate files to remove across entire Drive")
        return duplicates

    def generate_report(self, duplicates, folder_id):
        """Generate JSON report for duplicate files.

        Args:
            duplicates: List of duplicate file candidates
            folder_id: Folder ID for report naming

        Returns:
            Path to generated report file
        """
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(REPORTS_DIR, f"duplicate_report_{folder_id}_{timestamp}.json")

        total_size = sum(d['size'] for d in duplicates)

        report_data = {
            "report_type": "Google Drive Duplicate Cleanup",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "folder_id": folder_id,
            "summary": {
                "total_duplicates": len(duplicates),
                "potential_savings_bytes": total_size,
                "potential_savings_gb": round(total_size / (1024**3), 2)
            },
            "candidates": {
                "HIGH": duplicates  # All duplicates are HIGH confidence
            }
        }

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Report generated: {report_file}")
        return report_file


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Google Drive Duplicate Cleanup - MD5-based duplicate detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan entire Drive and build MD5 checksum cache
  python duplicate_cleanup.py --checksums

  # Clean ALL duplicates across entire Drive (default)
  python duplicate_cleanup.py --clean

  # Clean duplicates in a specific folder only
  python duplicate_cleanup.py --clean FOLDER_ID

  # Refresh cache and clean entire Drive
  python duplicate_cleanup.py --checksums --clean
        """
    )

    parser.add_argument(
        'folder_id',
        nargs='?',
        help='Google Drive folder ID or URL (optional - if omitted, scans entire Drive)'
    )

    parser.add_argument(
        '--checksums',
        action='store_true',
        help='Scan entire Drive and build/refresh MD5 checksum cache'
    )

    parser.add_argument(
        '--clean',
        action='store_true',
        help='Interactive cleanup of duplicates (entire Drive if no folder specified, or specific folder)'
    )

    args = parser.parse_args()

    # Record start time for logging
    start_time = datetime.now(timezone.utc)

    # Extract folder ID if provided
    folder_id = extract_folder_id(args.folder_id) if args.folder_id else None

    # Set up logging
    if folder_id:
        setup_file_logging(folder_id, start_time)
    else:
        # Use 'drive' as identifier if no folder specified
        setup_file_logging('drive', start_time)

    logger.info("=" * 80)
    logger.info("GOOGLE DRIVE DUPLICATE CLEANUP")
    logger.info("=" * 80)

    # Determine which operations to run
    if not args.checksums and not args.clean:
        logger.error("Please specify at least one operation: --checksums or --clean")
        parser.print_help()
        sys.exit(1)

    # Checksum scan phase
    if args.checksums:
        logger.info("PHASE: SCAN CHECKSUMS")
        logger.info("=" * 80)

        # Authenticate (read-only)
        logger.info("Authenticating with Google Drive API...")
        service = authenticate(write_access=False)
        logger.info("Authentication successful!")

        # Scan Drive for checksums
        scanner = DuplicateScanner(service)
        success = scanner.scan_drive_for_checksums(refresh_cache=True)

        if not success:
            logger.error("Failed to scan Drive for checksums")
            sys.exit(1)

        logger.info("")
        logger.info("✅ Checksum scan complete")
        logger.info("")

    # Cleanup phase
    if args.clean:
        logger.info("PHASE: DUPLICATE CLEANUP")
        logger.info("=" * 80)

        # Authenticate
        logger.info("Authenticating with Google Drive API...")
        service = authenticate(write_access=True)
        logger.info("Authentication successful!")

        # Load checksums (if not already loaded)
        scanner = DuplicateScanner(service)
        scanner.scan_drive_for_checksums(refresh_cache=False)

        # Find duplicates (entire Drive or specific folder)
        if folder_id:
            logger.info(f"Searching for duplicates in specific folder: {folder_id}")
            duplicates = scanner.find_duplicates_in_folder(folder_id)
            scope_name = folder_id
        else:
            logger.info("Searching for duplicates across entire Drive...")
            duplicates = scanner.find_duplicates_in_drive()
            scope_name = "drive"

        if not duplicates:
            scope_desc = f"folder {folder_id}" if folder_id else "entire Drive"
            logger.info(f"No duplicates found in {scope_desc}")
            sys.exit(0)

        # Generate report
        report_file = scanner.generate_report(duplicates, scope_name)

        logger.info(f"Found {len(duplicates)} duplicate files")
        logger.info("")

        # Interactive cleanup
        interactive_cleanup(service, report_file, scope_name)


if __name__ == '__main__':
    main()
