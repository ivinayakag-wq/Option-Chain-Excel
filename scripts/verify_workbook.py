import sys
from pathlib import Path

import win32com.client as win32

from src.config import ROOT
from src.upstox import INDICES

PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "OptionChain.xlsx"


def main() -> int:
    app = win32.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    wb = app.Workbooks.Open(str(PATH), ReadOnly=True)
    try:
        print(f"Workbook  : {PATH}")
        print(f"Sheets    : {', '.join(ws.Name for ws in wb.Worksheets)}")
        print(f"Queries   : {wb.Queries.Count}")
        for query in wb.Queries:
            print(f"  - {query.Name}")

        for symbol in INDICES:
            ws = wb.Worksheets(symbol)
            print(f"\n[{symbol}]")
            if ws.ListObjects.Count == 0:
                print("  no table")
                continue
            lo = ws.ListObjects(1)
            print(f"  table     : {lo.Name}  ref={lo.Range.Address}")
            print(f"  rows      : {lo.ListRows.Count}")
            headers = [lo.ListColumns(i + 1).Name for i in range(lo.ListColumns.Count)]
            print(f"  headers   : {headers}")
            ws.Activate()
            print(f"  freeze    : {app.ActiveWindow.FreezePanes}")
            print(f"  H5 fmt    : {ws.Range('H5').NumberFormat}")
            print(f"  H5 value  : {ws.Range('H5').Value}")
            print(f"  cond fmts : {ws.Range('A5:U200').FormatConditions.Count}")

        ws = wb.Worksheets("Summary")
        lo = ws.ListObjects(1)
        headers = [lo.ListColumns(i + 1).Name for i in range(lo.ListColumns.Count)]
        print(f"\n[Summary] rows={lo.ListRows.Count} ref={lo.Range.Address}")
        print(f"  headers   : {headers}")
        ws.Activate()
        print(f"  freeze    : {app.ActiveWindow.FreezePanes}")
        for row in range(5, 5 + lo.ListRows.Count):
            values = [ws.Cells(row, col).Value for col in (1, 3, 5, 7, 8, 9, 17)]
            print(f"  {values}")
    finally:
        wb.Close(SaveChanges=False)
        app.Quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


