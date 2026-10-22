import argparse
import math
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import ROOT
from .upstox import INDICES

BASE_URL = "http://127.0.0.1:8765"
WORKBOOK_PATH = ROOT / "OptionChain.xlsx"

CHAIN_COLUMNS = [
    ("symbol", "Symbol", "text"),
    ("expiry", "Expiry", "text"),
    ("spot", "Spot", "number"),
    ("ce_oi", "CE OI", "Int64.Type"),
    ("ce_doi", "CE DOI", "Int64.Type"),
    ("ce_vol", "CE Vol", "Int64.Type"),
    ("ce_iv", "CE IV", "number"),
    ("ce_ltp", "CE LTP", "number"),
    ("ce_chg_pct", "CE Chg%", "number"),
    ("ce_bid", "CE Bid", "number"),
    ("ce_ask", "CE Ask", "number"),
    ("strike", "Strike", "Int64.Type"),
    ("pe_bid", "PE Bid", "number"),
    ("pe_ask", "PE Ask", "number"),
    ("pe_chg_pct", "PE Chg%", "number"),
    ("pe_ltp", "PE LTP", "number"),
    ("pe_iv", "PE IV", "number"),
    ("pe_vol", "PE Vol", "Int64.Type"),
    ("pe_doi", "PE DOI", "Int64.Type"),
    ("pe_oi", "PE OI", "Int64.Type"),
    ("lot_size", "Lot", "Int64.Type"),
]

SUMMARY_COLUMNS = [
    ("symbol", "Symbol", "text"),
    ("expiry", "Expiry", "text"),
    ("spot", "Spot", "number"),
    ("atm", "ATM", "Int64.Type"),
    ("pcr_oi", "PCR (OI)", "number"),
    ("pcr_vol", "PCR (Vol)", "number"),
    ("max_pain", "Max Pain", "Int64.Type"),
    ("oi_support", "OI Support", "Int64.Type"),
    ("oi_resistance", "OI Resistance", "Int64.Type"),
    ("atm_ce_iv", "ATM CE IV", "number"),
    ("atm_pe_iv", "ATM PE IV", "number"),
    ("total_ce_oi", "CE OI", "Int64.Type"),
    ("total_pe_oi", "PE OI", "Int64.Type"),
    ("total_ce_doi", "CE DOI", "Int64.Type"),
    ("total_pe_doi", "PE DOI", "Int64.Type"),
    ("strikes", "Strikes", "Int64.Type"),
    ("stale", "Stale", "logical"),
    ("age_seconds", "Age (s)", "Int64.Type"),
]

CHAIN_NUMBER_FORMATS = {
    3: "#,##0.00",
    4: "#,##0",
    5: "+#,##0;-#,##0;0",
    6: "#,##0",
    7: "0.00",
    8: "#,##0.00",
    9: '+0.00"%";-0.00"%";0.00"%"',
    10: "#,##0.00",
    11: "#,##0.00",
    12: "#,##0",
    13: "#,##0.00",
    14: "#,##0.00",
    15: '+0.00"%";-0.00"%";0.00"%"',
    16: "#,##0.00",
    17: "0.00",
    18: "#,##0",
    19: "+#,##0;-#,##0;0",
    20: "#,##0",
    21: "0",
}

SUMMARY_NUMBER_FORMATS = {
    3: "#,##0.00",
    4: "#,##0",
    5: "0.000",
    6: "0.000",
    7: "#,##0",
    8: "#,##0",
    9: "#,##0",
    10: "0.00",
    11: "0.00",
    12: "#,##0",
    13: "#,##0",
    14: "+#,##0;-#,##0;0",
    15: "+#,##0;-#,##0;0",
    16: "#,##0",
    18: "#,##0",
}

FONT_NAME = "Segoe UI"
GREEN = (30, 107, 52)
RED = (139, 30, 30)
SLATE = (51, 65, 85)
LIGHT_GREEN = (226, 239, 218)
LIGHT_RED = (252, 228, 228)
AMBER = (254, 243, 199)
LIGHT_SLATE = (241, 245, 249)


def _m_type(kind: str) -> str:
    if kind == "text":
        return "type text"
    if kind == "number":
        return "type number"
    if kind == "logical":
        return "type logical"
    return "Int64.Type"


def _m_field_type(kind: str) -> str:
    if kind in ("text", "number", "logical"):
        return kind
    return "Int64.Type"


def _m_type_table(columns: list[tuple[str, str, str]]) -> str:
    parts = [f"{raw}={_m_field_type(kind)}" for raw, _, kind in columns]
    return "type table [" + ", ".join(parts) + "]"


def _m_rename(columns: list[tuple[str, str, str]]) -> str:
    parts = [f'{{"{raw}", "{friendly}"}}' for raw, friendly, _ in columns]
    return "{" + ", ".join(parts) + "}"


def _m_typed(columns: list[tuple[str, str, str]]) -> str:
    parts = [
        f'{{"{raw}", {_m_type(kind)}}}' for raw, _, kind in columns if kind != "text"
    ]
    return "{" + ", ".join(parts) + "}"


def _m_order(columns: list[tuple[str, str, str]]) -> str:
    return "{" + ", ".join(f'"{friendly}"' for _, friendly, _ in columns) + "}"


def _m_raw_order(columns: list[tuple[str, str, str]]) -> str:
    return "{" + ", ".join(f'"{raw}"' for raw, _, _ in columns) + "}"


def chain_query(symbol: str) -> str:
    cols = CHAIN_COLUMNS
    return f"""let
    Url = "{BASE_URL}/chain/{symbol}",
    Empty = #table({_m_type_table(cols)}, {{}}),
    Src = try Json.Document(Web.Contents(Url)) otherwise null,
    Rows = if Src = null or Record.FieldOrDefault(Src, "rows", null) = null or List.IsEmpty(Src[rows]) then Empty else Table.FromRecords(Src[rows], null, MissingField.UseNull),
    Selected = Table.SelectColumns(Rows, {_m_raw_order(cols)}),
    Typed = Table.TransformColumnTypes(Selected, {_m_typed(cols)}),
    Renamed = Table.RenameColumns(Typed, {_m_rename(cols)}),
    Ordered = Table.ReorderColumns(Renamed, {_m_order(cols)})
in
    Ordered"""


def summary_query() -> str:
    cols = SUMMARY_COLUMNS
    return f"""let
    Url = "{BASE_URL}/summaries",
    Empty = #table({_m_type_table(cols)}, {{}}),
    Src = try Json.Document(Web.Contents(Url)) otherwise null,
    Rows = if Src = null or Record.FieldOrDefault(Src, "rows", null) = null or List.IsEmpty(Src[rows]) then Empty else Table.FromRecords(Src[rows], null, MissingField.UseNull),
    Selected = Table.SelectColumns(Rows, {_m_raw_order(cols)}),
    Typed = Table.TransformColumnTypes(Selected, {_m_typed(cols)}),
    Renamed = Table.RenameColumns(Typed, {_m_rename(cols)}),
    Ordered = Table.ReorderColumns(Renamed, {_m_order(cols)})
in
    Ordered"""


def build_read_me(wb: Workbook) -> None:
    ws = wb.create_sheet("Read Me")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 118
    for col in "BCDEFGHIJ":
        ws.column_dimensions[col].width = 2

    blocks: list[tuple[str, str]] = [
        ("title", "Option Chain â€” Read Me"),
        ("sub", "NIFTY Â· BANKNIFTY Â· FINNIFTY Â· MIDCPNIFTY Â· SENSEX"),
        ("gap", ""),
        ("head", "What this is"),
        ("body", "Five live index option chains inside Excel, one sheet per index, plus a Summary sheet with PCR, max pain and OI levels. Data comes from the free Upstox API through a small service running on this PC."),
        ("gap", ""),
        ("head", "Before you refresh"),
        ("body", "1. Start the service: double-click 'Start Option Chain Server.bat' (or run python -m src.server). Leave the window open."),
        ("body", "2. Log in at the start of each trading day: open http://127.0.0.1:8765/login in a browser and approve. The token is saved automatically."),
        ("body", "3. In Excel press Data ▸ Refresh All (Ctrl+Alt+F5). Done."),
        ("body", "The Upstox session expires at 03:30 IST every morning and there is no refresh token, so step 2 is a daily habit. It takes about a minute."),
        ("gap", ""),
        ("head", "Sheets"),
        ("body", "Summary â€” one row per index: spot, ATM, PCR, max pain, OI support and resistance, ATM IV, freshness."),
        ("body", "NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY / SENSEX â€” calls on the left, strike in the middle, puts on the right."),
        ("gap", ""),
        ("head", "Reading a chain sheet"),
        ("body", "Spot is the index level at snapshot time. Strike is the contract. CE = call, PE = put. OI is open interest, DOI is the change in OI versus the previous session, IV is implied volatility, LTP is last traded price, Chg% is the move versus the previous close. Shaded cells are in-the-money."),
        ("body", "Green-shaded rows mean the strike equals max pain for that expiry (see Summary)."),
        ("gap", ""),
        ("head", "Definitions"),
        ("body", "PCR â€” put open interest divided by call open interest. Above 1 suggests more put writing (often read as support); below 0.7 suggests call-heavy positioning."),
        ("body", "Max Pain â€” the strike where option writers would pay out the least if expiry settled there. Computed across every strike in the chain."),
        ("body", "OI Support / Resistance â€” the strike with the highest put OI (support) and highest call OI (resistance)."),
        ("body", "Stale â€” TRUE means the refresh failed and the numbers are the last good snapshot, not current. Check Age (s)."),
        ("gap", ""),
        ("head", "Limits"),
        ("body", "One expiry per sheet: the nearest weekly/monthly, which rolls automatically after expiry."),
        ("body", "Snapshots, not streaming: numbers update when you refresh, and only while the market is open (09:15â€“15:30 IST). Outside hours you see the last published values."),
        ("body", "The service must be running on this machine; the workbook reads from 127.0.0.1:8765."),
        ("body", "Data is licensed to you personally through your Upstox account. Use it for your own analysis; do not redistribute the feed or resell it."),
        ("gap", ""),
        ("head", "If something looks wrong"),
        ("body", "All sheets empty or unchanged â€” is the service window still open? Visit http://127.0.0.1:8765/health."),
        ("body", "Everything says AUTH_REQUIRED â€” the token expired (it does daily at 03:30 IST). Open http://127.0.0.1:8765/login and approve."),
        ("body", "Stale = TRUE with a growing age â€” the broker call failed. Refresh again; if it persists, check /health."),
    ]

    row = 1
    for kind, text in blocks:
        cell = ws.cell(row=row, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if kind == "title":
            cell.font = Font(name=FONT_NAME, size=20, bold=True, color="0F172A")
            ws.row_dimensions[row].height = 30
        elif kind == "sub":
            cell.font = Font(name=FONT_NAME, size=11, color="64748B")
            ws.row_dimensions[row].height = 18
        elif kind == "head":
            cell.font = Font(name=FONT_NAME, size=12, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1E293B")
            ws.row_dimensions[row].height = 22
            row += 1
            continue
        elif kind == "body":
            cell.font = Font(name=FONT_NAME, size=10.5, color="1F2937")
            lines = max(1, math.ceil(len(text) / 112))
            ws.row_dimensions[row].height = 16 * lines
        elif kind == "gap":
            ws.row_dimensions[row].height = 8
        row += 1


def build_shell(path: Path) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)

    build_read_me(wb)

    summary = wb.create_sheet("Summary")
    summary.sheet_properties.tabColor = "334155"
    summary["A1"] = "Summary â€” nearest expiry"
    summary["A1"].font = Font(name=FONT_NAME, size=16, bold=True, color="0F172A")
    summary["A2"] = (
        f"Source: {BASE_URL}/summary  Â·  Refresh with Data â–¸ Refresh All  Â·  "
        "PCR and max pain are computed by the service"
    )
    summary["A2"].font = Font(name=FONT_NAME, size=10, color="64748B")
    summary.row_dimensions[1].height = 24
    summary.row_dimensions[2].height = 16

    for symbol in INDICES:
        ws = wb.create_sheet(symbol)
        ws.sheet_properties.tabColor = "1E6B34" if symbol != "SENSEX" else "8B1E1E"
        ws["A1"] = f"{symbol} â€” nearest expiry"
        ws["A1"].font = Font(name=FONT_NAME, size=16, bold=True, color="0F172A")
        ws["A2"] = (
            f"Source: {BASE_URL}/chain/{symbol}  Â·  Refresh with Data â–¸ Refresh All  Â·  "
            "Calls left, puts right, strike centre"
        )
        ws["A2"].font = Font(name=FONT_NAME, size=10, color="64748B")
        ws.row_dimensions[1].height = 24
        ws.row_dimensions[2].height = 16
        ws.row_dimensions[3].height = 8

    wb.save(path)
    return wb


def _rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


def _format_header(ws, last_col: int, header_row: int, colors: dict[int, tuple]) -> None:
    rng = ws.Range(ws.Cells(header_row, 1), ws.Cells(header_row, last_col))
    rng.Font.Name = FONT_NAME
    rng.Font.Size = 10
    rng.Font.Bold = True
    rng.Font.Color = _rgb(255, 255, 255)
    rng.HorizontalAlignment = -4108
    rng.VerticalAlignment = -4108
    rng.WrapText = True
    ws.Rows(header_row).RowHeight = 34
    for col, color in colors.items():
        ws.Cells(header_row, col).Interior.Color = _rgb(*color)


def _add_list_object(ws, query_name: str, table_name: str, anchor: str):
    source = (
        "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;"
        f'Location={query_name};Extended Properties=""'
    )
    lo = ws.ListObjects.Add(
        SourceType=0,
        Source=source,
        LinkSource=False,
        Destination=ws.Range(anchor),
        TableStyleName="TableStyleLight1",
    )
    lo.Name = table_name
    lo.DisplayName = table_name
    lo.ShowTableStyleRowStripes = True
    query_table = lo.QueryTable
    query_table.CommandType = 2
    query_table.CommandText = f"SELECT * FROM [{query_name}]"
    query_table.BackgroundQuery = False
    return lo


def _refresh(lo, label: str = "") -> bool:
    try:
        lo.QueryTable.Refresh(False)
        return True
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240]
        print(f"  refresh failed for {label or lo.Name}: {detail}")
        return False


def _apply_chain_formats(ws, app, summary_row: int) -> None:
    last_row = 2000
    _format_header(
        ws,
        21,
        4,
        {
            **{c: SLATE for c in (1, 2, 3)},
            **{c: GREEN for c in range(4, 12)},
            **{12: (15, 23, 42)},
            **{c: RED for c in range(13, 21)},
            **{21: SLATE},
        },
    )
    for col in range(1, 22):
        letter = get_column_letter(col)
        rng = ws.Range(f"{letter}5:{letter}{last_row}")
        rng.Font.Name = FONT_NAME
        rng.Font.Size = 10
        if col in CHAIN_NUMBER_FORMATS:
            rng.NumberFormat = CHAIN_NUMBER_FORMATS[col]
    ws.Range(f"A5:C{last_row}").Font.Color = _rgb(100, 116, 139)
    ws.Range(f"L5:L{last_row}").Font.Bold = True
    ws.Range(f"L5:L{last_row}").HorizontalAlignment = -4108
    ws.Range(f"L5:L{last_row}").Interior.Color = _rgb(248, 250, 252)

    widths = {
        "A": 9, "B": 11, "C": 10, "D": 12, "E": 11, "F": 11, "G": 8, "H": 10,
        "I": 9, "J": 10, "K": 10, "L": 10, "M": 10, "N": 10, "O": 9, "P": 10,
        "Q": 8, "R": 11, "S": 11, "T": 12, "U": 6,
    }
    for letter, width in widths.items():
        ws.Columns(letter).ColumnWidth = width

    ce_itm = ws.Range(f"D5:K{last_row}")
    cond = ce_itm.FormatConditions.Add(2, 1, "=$C5>$L5")
    cond.Interior.Color = _rgb(*LIGHT_GREEN)

    pe_itm = ws.Range(f"M5:T{last_row}")
    cond = pe_itm.FormatConditions.Add(2, 1, "=$C5<$L5")
    cond.Interior.Color = _rgb(*LIGHT_RED)

    pain = ws.Range(f"A5:U{last_row}")
    cond = pain.FormatConditions.Add(2, 1, f"=$L5=Summary!$G${summary_row}")
    cond.Interior.Color = _rgb(*AMBER)

    for col in ("D", "T"):
        try:
            bar = ws.Range(f"{col}5:{col}{last_row}").FormatConditions.AddDatabar()
            bar.BarColor.Color = _rgb(46, 125, 50) if col == "D" else _rgb(139, 30, 30)
            bar.ShowValue = True
        except Exception:
            pass

    ws.Activate()
    ws.Range("D5").Select()
    app.ActiveWindow.FreezePanes = True


def _apply_summary_formats(ws) -> None:
    last_row = 40
    _format_header(ws, 18, 4, {c: SLATE for c in range(1, 19)})
    for col in range(1, 19):
        letter = get_column_letter(col)
        rng = ws.Range(f"{letter}5:{letter}{last_row}")
        rng.Font.Name = FONT_NAME
        rng.Font.Size = 10
        if col in SUMMARY_NUMBER_FORMATS:
            rng.NumberFormat = SUMMARY_NUMBER_FORMATS[col]
    ws.Range(f"E5:F{last_row}").Font.Bold = True
    ws.Range(f"G5:I{last_row}").Font.Bold = True
    ws.Range(f"G5:G{last_row}").Font.Color = _rgb(*RED)

    widths = {
        "A": 12, "B": 11, "C": 11, "D": 10, "E": 10, "F": 10, "G": 10, "H": 11,
        "I": 13, "J": 11, "K": 11, "L": 13, "M": 13, "N": 11, "O": 11, "P": 8,
        "Q": 7, "R": 8,
    }
    for letter, width in widths.items():
        ws.Columns(letter).ColumnWidth = width

    stale = ws.Range(f"A5:R{last_row}")
    cond = stale.FormatConditions.Add(2, 1, "=$Q5=TRUE")
    cond.Interior.Color = _rgb(*AMBER)

    for col in ("L", "M"):
        try:
            bar = ws.Range(f"{col}5:{col}{last_row}").FormatConditions.AddDatabar()
            bar.BarColor.Color = _rgb(46, 125, 50) if col == "L" else _rgb(139, 30, 30)
            bar.ShowValue = True
        except Exception:
            pass

    ws.Activate()
    ws.Range("C6").Select()


def build_via_excel(path: Path, refresh: bool = True) -> dict:
    import win32com.client as win32

    app = win32.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    app.AskToUpdateLinks = False
    results: dict[str, bool] = {}
    wb = None
    try:
        wb = app.Workbooks.Open(str(path))
        for symbol in INDICES:
            name = f"{symbol}_chain"
            wb.Queries.Add(name, chain_query(symbol))
        wb.Queries.Add("Summary_rows", summary_query())

        for index, symbol in enumerate(INDICES, start=1):
            sheet = wb.Worksheets(symbol)
            lo = _add_list_object(sheet, f"{symbol}_chain", f"tbl_{symbol}", "A4")
            results[symbol] = _refresh(lo) if refresh else False
            _apply_chain_formats(sheet, app, summary_row=4 + index)

        summary = wb.Worksheets("Summary")
        lo = _add_list_object(summary, "Summary_rows", "tbl_Summary", "A4")
        results["Summary"] = _refresh(lo) if refresh else False
        _apply_summary_formats(summary)

        wb.Worksheets("Read Me").Activate()
        wb.Save()
        return results
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        app.Quit()


def verify(path: Path) -> list[str]:
    from openpyxl import load_workbook

    wb = load_workbook(path)
    lines = []
    for ws in wb.worksheets:
        tables = ", ".join(ws.tables.keys()) or "-"
        lines.append(f"{ws.title:<14} tables: {tables}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the OptionChain workbook shell")
    parser.add_argument("--path", default=str(WORKBOOK_PATH))
    parser.add_argument("--no-refresh", action="store_true", help="Skip the initial query refresh")
    args = parser.parse_args(argv)

    path = Path(args.path)
    build_shell(path)
    print(f"Shell written: {path}")
    results = build_via_excel(path, refresh=not args.no_refresh)
    for name, ok in results.items():
        print(f"  {name:<12} refresh: {'ok' if ok else 'deferred (no data yet)'}")
    print(f"Saved: {path}")
    for line in verify(path):
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())


