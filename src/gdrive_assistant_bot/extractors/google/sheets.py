from typing import Any

from ..base import ExtractedContent, ExtractionContext, FileExtractor


class GoogleSheetsExtractor(FileExtractor):
    """Extract text from Google Sheets spreadsheets."""

    MIME_TYPE = "application/vnd.google-apps.spreadsheet"

    @property
    def mime_types(self) -> list[str]:
        return [self.MIME_TYPE]

    @property
    def file_extensions(self) -> list[str]:
        return []

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") == self.MIME_TYPE

    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        spreadsheet_id = file_meta["id"]
        spreadsheet = context.execute_with_backoff(
            lambda: context.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
        sheet_infos = spreadsheet.get("sheets") or []

        lines: list[str] = []
        for sheet_info in sheet_infos:
            if not sheet_info or not isinstance(sheet_info, dict):
                continue
            title = (sheet_info.get("properties") or {}).get("title") or "Sheet"
            row_limit = context.settings.GOOGLE_MAX_ROWS_PER_SHEET
            rng = f"'{title}'!A1:ZZ{row_limit}"
            resp = context.execute_with_backoff(
                lambda rng=rng: context.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=rng)
                .execute()
            )
            values = resp.get("values") or []
            if not values:
                continue

            lines.append(f"=== SHEET: {title} ===")
            for row in values:
                row_str = "\t".join(str(x).strip() for x in row if str(x).strip())
                if row_str:
                    lines.append(row_str)

        text = "\n".join(lines).strip()
        return ExtractedContent(text=text, file_type="gsheet", metadata={})
