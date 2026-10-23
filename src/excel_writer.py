import os
import time

import pythoncom
import pywintypes
import win32com.client as win32

CALL_REJECTED = -2147418111
CHAIN_HEIGHT = 21
SUMMARY_HEIGHT = 5
GREEN = 0xD7E2EF
AMBER = 0xC7F3FE
RED = 0xE4E4FC
WHITE = 0xFFFFFF


class ExcelWriter:
    def __init__(self, path, open_if_missing: bool = True, visible: bool = True):
        self.path = os.path.abspath(str(path))
        self.open_if_missing = open_if_missing
        self.visible = visible
        self.app = None
        self.wb = None
        self._state = ""
        self._ever_ready = False
        self.last_write = 0.0

    def attach(self) -> bool:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            self.app = win32.GetActiveObject("Excel.Application")
        except Exception:
            self.app = None
        if self.app is not None:
            book = self._find_book()
            if book is not None:
                self.wb = book
                self._ever_ready = True
                return True
        if not self.open_if_missing or self._ever_ready:
            return False
        try:
            if self.app is None:
                self.app = win32.DispatchEx("Excel.Application")
                self.app.Visible = self.visible
                self.app.DisplayAlerts = False
            self.app.Workbooks.Open(self.path)
            self.wb = self._find_book()
            self.app.Visible = self.visible
            self._ever_ready = self.wb is not None
            return self.wb is not None
        except Exception:
            self.wb = None
            return False

    def _find_book(self):
        if self.app is None:
            return None
        target = os.path.normcase(self.path)
        try:
            for index in range(1, self.app.Workbooks.Count + 1):
                book = self.app.Workbooks(index)
                if os.path.normcase(os.path.abspath(str(book.FullName))) == target:
                    return book
        except Exception:
            return None
        return None

    @property
    def ready(self) -> bool:
        return self.wb is not None

    def _call(self, function, *args):
        for attempt in range(4):
            try:
                return function(*args)
            except pywintypes.com_error as exc:
                code = exc.args[0] if exc.args else 0
                if code == CALL_REJECTED and attempt < 3:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise
        return None

    def _block(self, sheet_name, anchor_row, rows, width, height):
        sheet = self.wb.Worksheets(sheet_name)
        padded = list(rows[:height])
        blank = [""] * width
        while len(padded) < height:
            padded.append(blank)
        values = tuple(tuple(cell if cell is not None else "" for cell in row) for row in padded)
        target = sheet.Range(sheet.Cells(anchor_row, 1), sheet.Cells(anchor_row + height - 1, width))
        self._call(setattr, target, "Value2", values)
        return sheet

    def write_chain(self, sheet_name, rows, status: str, state: str = "ok"):
        if not self.ready and not self.attach():
            return False
        try:
            sheet = self._block(sheet_name, 5, rows, 21, CHAIN_HEIGHT)
            self._status(sheet, status, state)
            self.last_write = time.monotonic()
            return True
        except Exception:
            self.wb = None
            return False

    def write_summary(self, rows, status: str, state: str = "ok"):
        if not self.ready and not self.attach():
            return False
        try:
            sheet = self._block("Summary", 5, rows, 18, SUMMARY_HEIGHT)
            self._status(sheet, status, state)
            self.last_write = time.monotonic()
            return True
        except Exception:
            self.wb = None
            return False

    def _status(self, sheet, text: str, state: str) -> None:
        cell = sheet.Range("A2")
        self._call(setattr, cell, "Value", text)
        if state != self._state:
            fill = {"ok": GREEN, "stale": AMBER, "error": RED}.get(state, WHITE)
            interior = cell.Interior
            self._call(setattr, interior, "Color", fill)
            self._state = state

    def save(self) -> None:
        if self.wb is not None:
            try:
                self.wb.Save()
            except Exception:
                pass
