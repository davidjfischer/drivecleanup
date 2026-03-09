#!/usr/bin/env python3
"""
Duplicate Cleanup Tool - MD5-based duplicate file detection for Google Drive.

This script scans your Google Drive for duplicate files based on MD5 checksums
and provides an interactive cleanup interface.

Usage:
    # Scan Drive and build MD5 checksum cache
    python duplicate_cleanup.py --checksums

    # Interactive cleanup based on duplicates
    python duplicate_cleanup.py --clean FOLDER_ID

    # Refresh cache and clean
    python duplicate_cleanup.py --checksums --clean FOLDER_ID
"""

import os
import sys
import argparse
import json
import pickle
import re
from datetime import datetime, timezone
from collections import defaultdict
from loguru import logger
from googleapiclient.discovery import build
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

                total_files = sum(len(files) for files in self.md5_to_files.values())
                logger.info(f"Loaded {total_files} files with MD5 checksums from cache")
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

        # Save to cache (checksums and folder structure)
        try:
            logger.debug(f"Saving MD5 checksum cache to {CHECKSUMS_CACHE_FILE}")
            cache_data = {
                'checksums': dict(self.md5_to_files),
                'folders': self.folder_id_to_name,
                'folder_parents': self.folder_id_to_parents
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

        # Get all files in the folder (recursively)
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
                folder_files.extend([item for item in items if 'md5Checksum' in item])

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"Error scanning folder: {e}")
                break

        logger.info(f"Found {len(folder_files)} files with MD5 in folder")

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

                            candidate = {
                                'id': duplicate_file['id'],
                                'name': duplicate_file['name'],
                                'path': duplicate_path,
                                'size': size,
                                'size_formatted': size_formatted,
                                'modified': duplicate_file.get('modifiedTime'),
                                'reasons': [f"Duplicate file - original at: {original_path}"],
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

                            candidate = {
                                'id': duplicate_file['id'],
                                'name': duplicate_file['name'],
                                'path': duplicate_path,
                                'size': size,
                                'size_formatted': size_formatted,
                                'modified': duplicate_file.get('modifiedTime'),
                                'reasons': [f"Duplicate file (in same folder) - keep oldest at: {original_path}"],
                                'link': duplicate_file.get('webViewLink', 'N/A'),
                                'mime_type': mime_type,
                                'summary': None
                            }

                            duplicates.append(candidate)
                        else:
                            logger.debug(f"Skipping duplicate media file (protected): {duplicate_file.get('name', 'Unknown')}")

        logger.info(f"Found {duplicates_found} duplicate files to remove")
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
  # Scan Drive and build MD5 checksum cache
  python duplicate_cleanup.py --checksums

  # Clean duplicates in a specific folder
  python duplicate_cleanup.py --clean FOLDER_ID

  # Refresh cache and clean
  python duplicate_cleanup.py --checksums --clean FOLDER_ID
        """
    )

    parser.add_argument(
        'folder_id',
        nargs='?',
        help='Google Drive folder ID or URL (required for --clean)'
    )

    parser.add_argument(
        '--checksums',
        action='store_true',
        help='Scan Drive and build/refresh MD5 checksum cache'
    )

    parser.add_argument(
        '--clean',
        action='store_true',
        help='Interactive cleanup of duplicates in specified folder'
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

    if args.clean and not folder_id:
        logger.error("Folder ID is required for --clean operation")
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

        # Find duplicates in folder
        duplicates = scanner.find_duplicates_in_folder(folder_id)

        if not duplicates:
            logger.info("No duplicates found in folder")
            sys.exit(0)

        # Generate report
        report_file = scanner.generate_report(duplicates, folder_id)

        logger.info(f"Found {len(duplicates)} duplicate files")
        logger.info("")

        # Interactive cleanup
        interactive_cleanup(service, report_file, folder_id)


if __name__ == '__main__':
    main()
