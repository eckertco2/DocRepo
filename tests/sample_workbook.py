"""A made-up project list workbook, for testing the Excel import. Test code makes it; DocRepo itself never writes Excel files.

Run it on its own to make one for trying the import by hand:
``.venv\\Scripts\\python.exe tests\\sample_workbook.py C:\\somewhere\\sample-projects.xlsx``
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

HEADERS = ["Project", "Description", "Status", "Due date", "Start", "Owner", "Team", "Category", "Strategic", "Priority", "Budget code"]
ROWS = [
    ["Boiler feedwater pump overhaul", "Overhaul both feedwater pumps during the spring outage.", "Vendor quote received; waiting on the PO.",
     datetime(2027, 4, 30), datetime(2027, 3, 1), "Priya Shah", "Mike Ortiz, Tom", "Line 1", "Yes", "High", "BC-114"],
    ["Control room HVAC upgrade", "Replace the control room air handler.", "Design review scheduled.", "Q1 2027", None, "Tom Becker",
     "Tyler", "Line 2", None, None, "BC-207"],
    ["Warehouse racking inspection", "Inspect and tag every rack bay.", "Complete. Report filed.", datetime(2026, 9, 30), None,
     "Dana Kim", None, "Safety", "x", None, None],
    ["Reactor impeller upgrade", "Already in the sample data.", "Impeller on site.", datetime(2026, 11, 27), None, "Me", "Tom", "Line 1",
     "Yes", None, None],
    ["Compressed air leak survey", "Find and tag leaks on both lines.", "On hold until the budget is approved.", "TBD", None, "Mike Ortiz",
     "Rob", "Line 1; Line 2", None, "Low", "BC-301"],
    [None, None, None, None, None, None, None, None, None, None, None],
    [None, "Made-up sample rows for testing DocRepo's import.", None, None, None, None, None, None, None, None, None],
]


def make_workbook(path: Path, sheet: str = "PROJECTS") -> Path:
    from openpyxl import Workbook

    book = Workbook()
    ws = book.active
    ws.title = sheet
    ws.append(["Project list (made-up sample)"])
    ws.append([])
    ws.append(HEADERS)
    for row in ROWS:
        ws.append(row)
    book.create_sheet("Notes").append(["Nothing to import here."])
    book.save(path)
    return path


if __name__ == "__main__":
    print(make_workbook(Path(sys.argv[1])))
