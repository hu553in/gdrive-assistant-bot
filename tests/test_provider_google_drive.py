from __future__ import annotations

from gdrive_assistant_bot.providers.base import FileTypeFilter
from gdrive_assistant_bot.providers.google_drive.provider import GoogleDriveProvider


def test_matches_filter_by_mime_and_prefix_and_extension() -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(
        mime_types=["application/test"], mime_prefixes=["text/"], extensions=["md"]
    )

    assert provider._matches_filter({"mimeType": "application/test"}, file_filter) is True
    assert provider._matches_filter({"mimeType": "text/plain"}, file_filter) is True
    assert (
        provider._matches_filter(
            {"mimeType": "application/other", "fileExtension": "MD"}, file_filter
        )
        is True
    )
    assert provider._matches_filter({"mimeType": "application/other"}, file_filter) is False


def test_build_drive_query_terms_orders_prefixes_and_extensions() -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(
        mime_types=["application/test"],
        mime_prefixes=["text/", "application/"],
        extensions=["b", "a"],
    )

    terms = provider._build_drive_query_terms(file_filter)
    assert terms == [
        "mimeType='application/test'",
        "mimeType contains 'application/'",
        "mimeType contains 'text/'",
        "fileExtension='a'",
        "fileExtension='b'",
    ]


def test_to_storage_meta_normalizes_size_and_extension() -> None:
    provider = GoogleDriveProvider()
    expected_size = 42
    meta = provider._to_storage_meta(
        {
            "id": "1",
            "name": "file",
            "mimeType": "text/plain",
            "modifiedTime": "2024-01-01",
            "size": str(expected_size),
            "fileExtension": "TXT",
        }
    )

    assert meta.size == expected_size
    assert meta.extension == "TXT"
    as_meta = meta.as_extractor_meta()
    assert as_meta["id"] == "1"
    assert as_meta["fileExtension"] == "TXT"
