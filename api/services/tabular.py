"""Reading a measurement file, whatever shape it arrives in.

Ported from `legacy/web/js/parse.js`, whose French comments are translated
here. That code was written against real files from real labs and its
heuristics are earned, not invented — this is a translation, not a rewrite.

What it absorbs, because researchers actually send all of it:

  * semicolon separators and decimal commas from European Excel exports;
  * title rows above the real header;
  * Greek letters and units in column names — "γ (°)", "rβ (µm)";
  * thousands separators, including non-breaking spaces.

The original refused .xlsx because unzipping and parsing XML in a browser was
out of scope. Server-side that constraint is gone, and it matters: a
spreadsheet is what most people have.
"""

from __future__ import annotations

import csv as _csv
import io
import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

MAX_HEADER_SCAN = 8
SEPARATORS = [";", ",", "\t", "|"]
DECIMALS = [".", ","]

# Excel writes thousands separators as ordinary, narrow or non-breaking spaces.
_SPACES = re.compile(r"[\s  ]")


@dataclass
class ParsedTable:
    columns: list[str]
    #: One dict per row. Values are floats where the cell parsed as a number,
    #: the original string where it did not, and None where the cell was empty.
    rows: list[dict[str, Any]]
    source: Literal["csv", "xlsx"]
    separator: str | None = None
    decimal: str = "."
    header_row: int = 0
    sheet: str | None = None
    #: Rows above the header that were skipped as title lines.
    skipped_rows: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    def report(self) -> dict[str, Any]:
        """Kept with the dataset, so a puzzling fit can be traced back to how
        the file was read rather than guessed at months later."""
        return {
            "source": self.source,
            "separator": self.separator,
            "decimal": self.decimal,
            "header_row": self.header_row,
            "sheet": self.sheet,
            "skipped_rows": self.skipped_rows,
            "n_rows": self.n_rows,
            "n_columns": len(self.columns),
            "notes": self.notes,
        }


class ParseError(ValueError):
    """Raised with a message meant for the person who uploaded the file."""


# --------------------------------------------------------------------------- #
# Cell values
# --------------------------------------------------------------------------- #
def to_number(text: Any, decimal: str) -> float:
    """Read a cell as a number, or return NaN.

    With `decimal=","` the dots are thousands separators and are stripped
    before the comma becomes the decimal point — the shape a French Excel
    export produces.
    """
    if text is None:
        return math.nan
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        value = float(text)
        return value if math.isfinite(value) else math.nan

    s = str(text).strip()
    if not s:
        return math.nan
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    s = _SPACES.sub("", s)
    try:
        value = float(s)
    except ValueError:
        return math.nan
    return value if math.isfinite(value) else math.nan


def _looks_numeric(name: Any) -> bool:
    s = str(name if name is not None else "").strip().replace(",", ".")
    if not s:
        return False
    try:
        float(s)
    except ValueError:
        return False
    return True


def _is_placeholder(name: Any) -> bool:
    s = str(name if name is not None else "").strip()
    return s == "" or s.lower() in {"nan", "none", "null"}


# --------------------------------------------------------------------------- #
# Choosing how to read the file
# --------------------------------------------------------------------------- #
def _score_attempt(rows: list[list[Any]], header_row: int, decimal: str) -> float:
    """How plausible is this (header row, decimal mark) reading?

    Taking the first reading that does not raise is not enough. A French Excel
    export parses cleanly with "." as the decimal mark — no error — but every
    measurement column arrives as text and then vanishes from the variables on
    offer. Hence a score rather than a yes/no.
    """
    if len(rows) <= header_row + 1:
        return -math.inf
    header = rows[header_row]
    body = rows[header_row + 1 :]
    if len(header) < 2:
        return -math.inf

    numeric_cols = 0
    for j in range(len(header)):
        seen = ok = 0
        for row in body:
            if j >= len(row):
                continue
            seen += 1
            if not math.isnan(to_number(row[j], decimal)):
                ok += 1
        if seen and ok / seen > 0.7:
            numeric_cols += 1

    named = sum(
        1 for c in header if not _is_placeholder(c) and not _looks_numeric(c)
    )
    numeric_names = sum(1 for c in header if _looks_numeric(c))
    placeholders = sum(1 for c in header if _is_placeholder(c))

    # A column name that reads as a number is punished hard: it is the
    # signature of a data row mistaken for the header.
    return (
        numeric_cols * 100
        + named * 2
        + len(header)
        - placeholders * 6
        - numeric_names * 20
    )


def _build(rows: list[list[Any]], header_row: int, decimal: str) -> tuple[list[str], list[dict]]:
    header = rows[header_row]
    columns = [
        f"column {j + 1}" if _is_placeholder(name) else str(name).strip()
        for j, name in enumerate(header)
    ]
    # Duplicate headings would silently collapse into one key and lose a
    # column; suffix them instead so the user can see and map both.
    seen: dict[str, int] = {}
    for j, name in enumerate(columns):
        if name in seen:
            seen[name] += 1
            columns[j] = f"{name} ({seen[name]})"
        else:
            seen[name] = 1

    body = [
        row for row in rows[header_row + 1 :]
        if any(str(cell).strip() not in ("", "None") for cell in row if cell is not None)
    ]

    out: list[dict[str, Any]] = []
    for row in body:
        record: dict[str, Any] = {}
        for j, name in enumerate(columns):
            raw = row[j] if j < len(row) else None
            value = to_number(raw, decimal)
            if not math.isnan(value):
                record[name] = value
            elif raw is None or str(raw).strip() == "":
                record[name] = None
            else:
                record[name] = str(raw).strip()
        out.append(record)
    return columns, out


# --------------------------------------------------------------------------- #
# CSV and text
# --------------------------------------------------------------------------- #
def parse_delimited(text: str) -> ParsedTable:
    clean = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in clean.split("\n") if line.strip()]
    if len(lines) < 2:
        raise ParseError(
            "This file does not have enough lines to form a table: a header row "
            "and at least one row of measurements are needed."
        )

    best: tuple[float, str, str, int, list[list[str]]] | None = None
    for separator in SEPARATORS:
        rows = [
            next(_csv.reader([line], delimiter=separator, quotechar='"'), [])
            for line in lines
        ]
        rows = [[cell.strip() for cell in row] for row in rows]
        for decimal in DECIMALS:
            # A comma cannot be the column separator and the decimal mark at
            # the same time.
            if separator == "," and decimal == ",":
                continue
            for header_row in range(min(MAX_HEADER_SCAN, len(lines) - 1)):
                score = _score_attempt(rows, header_row, decimal)
                if best is None or score > best[0]:
                    best = (score, separator, decimal, header_row, rows)

    if best is None or best[0] == -math.inf:
        raise ParseError(
            "This file could not be read as a table. Check that it has a row of "
            "column names and that columns are separated by commas, semicolons "
            "or tabs."
        )

    _, separator, decimal, header_row, rows = best
    columns, records = _build(rows, header_row, decimal)
    table = ParsedTable(
        columns=columns,
        rows=records,
        source="csv",
        separator=separator,
        decimal=decimal,
        header_row=header_row,
        skipped_rows=header_row,
    )
    if header_row:
        table.notes.append(
            f"{header_row} line(s) above the header were treated as title rows."
        )
    if decimal == ",":
        table.notes.append("Numbers were read with a comma as the decimal mark.")
    return table


# --------------------------------------------------------------------------- #
# Spreadsheets
# --------------------------------------------------------------------------- #
def parse_spreadsheet(data: bytes, sheet_name: str | None = None) -> ParsedTable:
    """Read the first (or named) sheet of an .xlsx workbook.

    `read_only` keeps a large workbook from being materialised in full, and
    `data_only` returns the cached result of a formula rather than the formula
    text — someone's residual stress may well be computed in the sheet.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as error:  # pragma: no cover - dependency is pinned
        raise ParseError("Spreadsheet support is unavailable on this server.") from error

    try:
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=True, keep_links=False
        )
    except Exception as error:
        raise ParseError(
            "This file could not be opened as an Excel workbook. If it is an "
            "older .xls file, re-save it as .xlsx or as CSV."
        ) from error

    try:
        worksheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
        if worksheet is None:
            raise ParseError("That sheet does not exist in the workbook.")

        rows: list[list[Any]] = []
        for raw in worksheet.iter_rows(values_only=True):
            if raw is None:
                continue
            rows.append(["" if cell is None else cell for cell in raw])
    finally:
        workbook.close()

    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise ParseError(
            "That sheet does not have enough rows to form a table: a header row "
            "and at least one row of measurements are needed."
        )

    # Cells already carry their type, so only the header row is in question.
    best_header, best_score = 0, -math.inf
    for header_row in range(min(MAX_HEADER_SCAN, len(rows) - 1)):
        score = _score_attempt(rows, header_row, ".")
        if score > best_score:
            best_header, best_score = header_row, score

    columns, records = _build(rows, best_header, ".")
    table = ParsedTable(
        columns=columns,
        rows=records,
        source="xlsx",
        separator=None,
        decimal=".",
        header_row=best_header,
        sheet=worksheet.title,
        skipped_rows=best_header,
    )
    if len(workbook.sheetnames) > 1:
        table.notes.append(
            f"The workbook has {len(workbook.sheetnames)} sheets; "
            f"'{worksheet.title}' was read."
        )
    if best_header:
        table.notes.append(
            f"{best_header} row(s) above the header were treated as title rows."
        )
    return table


def parse_upload(filename: str, data: bytes) -> ParsedTable:
    """Dispatch on the file's extension, then on its content."""
    lowered = (filename or "").lower()
    if lowered.endswith((".xlsx", ".xlsm")):
        return parse_spreadsheet(data)
    if lowered.endswith(".xls"):
        raise ParseError(
            "The old .xls format is not supported. Open the file and save it as "
            ".xlsx, or export it as CSV."
        )

    # Decode leniently: a file saved from Windows Excel is often cp1252, and
    # refusing it over one accented character would be unhelpful.
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes any byte string
        raise ParseError("The character encoding of this file could not be read.")

    # A .xlsx renamed to .csv is a real mistake people make; the message is
    # more useful than a wall of binary parse failures.
    if data[:2] == b"PK":
        raise ParseError(
            "This looks like a spreadsheet rather than a text file. Rename it "
            "with a .xlsx extension, or export it as CSV."
        )
    return parse_delimited(text)


def numeric_columns(table: ParsedTable, threshold: float = 0.7) -> list[str]:
    """Columns where most values parsed as numbers.

    The ones worth offering as inputs or targets; a column of tool names is
    not a candidate for a continuous variable.
    """
    out = []
    for column in table.columns:
        values = [row.get(column) for row in table.rows]
        if not values:
            continue
        ok = sum(1 for v in values if isinstance(v, float) and math.isfinite(v))
        if ok / len(values) > threshold:
            out.append(column)
    return out
