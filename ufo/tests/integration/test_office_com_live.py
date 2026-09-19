"""Live Office COM tests using private, invisible Office instances and temp files.

Nothing is shown on screen and the user's own Office windows are never touched:
each test starts its own instance (DispatchEx), works on a temp document, then
closes it without saving and quits. Skipped where Office isn't installed.
"""
import os
import winreg

import pytest

from ufo.automator.app_apis.excel.excelclient import ExcelWinCOMReceiver
from ufo.automator.app_apis.office_com import OfficeComSession
from ufo.automator.app_apis.powerpoint.powerpointclient import PowerPointWinCOMReceiver
from ufo.automator.app_apis.word.wordclient import WordWinCOMReceiver

# Starts real (invisible) Office processes; opt-in like the live-LLM tests.
pytestmark = pytest.mark.skipif(
    not os.environ.get("UFO_LIVE_OFFICE_TESTS"),
    reason="starts real Office instances; set UFO_LIVE_OFFICE_TESTS=1",
)


def _registered(progid):
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\CLSID").Close()
        return True
    except OSError:
        return False


def _session(progid, receiver, root, path, create):
    def attach(p):
        import win32com.client
        app = win32com.client.DispatchEx(p)
        create(app, path)
        return app
    return OfficeComSession(progid, receiver, root, os.path.basename(path), timeout=60, attach=attach)


def _close(session):
    try:
        session.call(lambda r: r.com_object.Close(0) if hasattr(r.com_object, "Close") else None)
    except Exception:
        pass
    session.close(quit_app=True)


@pytest.mark.skipif(not _registered("Excel.Application"), reason="Excel not installed")
def test_excel_live(tmp_path):
    path = str(tmp_path / "ufo_live_book.xlsx")

    def create(app, p):
        app.Visible = False
        app.DisplayAlerts = False
        app.Workbooks.Add().SaveAs(p, 51)

    s = _session("Excel.Application", ExcelWinCOMReceiver, "EXCEL.EXE", path, create)
    try:
        s.call(lambda r: r.set_cell_values(1, "A1", [["Name", "Score"], ["Ann", 3], ["Bob", 9], ["Cy", 5]]))
        assert "17" in s.call(lambda r: r.set_formula(1, "B5", "SUM(B2:B4)"))
        s.call(lambda r: r.sort_range(1, "A1:B4", 2, ascending=False))
        assert s.call(lambda r: r.get_range_values(1, 2, 1, 4, 1)) == [["Bob"], ["Cy"], ["Ann"]]
        assert "chart" in s.call(lambda r: r.create_chart(1, "A1:B4", "column", "Scores"))
        assert s.call(lambda r: r.com_object.Sheets(1).ChartObjects().Count) == 1
        s.call(lambda r: r.add_sheet("Summary"))
        assert s.call(lambda r: r.com_object.Sheets("Summary").Name) == "Summary"
        assert "| Name" in s.call(lambda r: r.table2markdown(1))
    finally:
        _close(s)


@pytest.mark.skipif(not _registered("Word.Application"), reason="Word not installed")
def test_word_live(tmp_path):
    path = str(tmp_path / "ufo_live_doc.docx")

    def create(app, p):
        app.Visible = False
        app.DisplayAlerts = 0
        app.Documents.Add().SaveAs2(p, 16)

    s = _session("Word.Application", WordWinCOMReceiver, "WINWORD.EXE", path, create)
    try:
        s.call(lambda r: r.insert_text("Quarterly report\nSales went up.\nSales team did well.", "end"))
        assert "Replaced 2" in s.call(lambda r: r.find_replace("Sales", "Revenue"))
        text = s.call(lambda r: r.get_document_text())
        assert "Revenue went up." in text and "Sales" not in text
        s.call(lambda r: r.apply_style("Heading 1", 1, 1))
        assert s.call(lambda r: str(r.com_object.Paragraphs(1).Style.NameLocal)) in ("Heading 1", "Überschrift 1", "Titre 1")
        out = s.call(lambda r: r.save_as(str(tmp_path), "exported", ".pdf"))
        assert os.path.isfile(tmp_path / "exported.pdf"), out
    finally:
        _close(s)


@pytest.mark.skipif(not _registered("PowerPoint.Application"), reason="PowerPoint not installed")
def test_powerpoint_live(tmp_path):
    path = str(tmp_path / "ufo_live_deck.pptx")

    def create(app, p):
        app.Presentations.Add(0).SaveAs(p)  # WithWindow=False: no window is shown

    s = _session("PowerPoint.Application", PowerPointWinCOMReceiver, "POWERPNT.EXE", path, create)
    try:
        s.call(lambda r: r.add_slide("Hello", "First point", "title_and_content"))
        s.call(lambda r: r.add_slide("Second", "", "title_only"))
        s.call(lambda r: r.set_slide_text(2, 1, "Renamed"))
        text = s.call(lambda r: r.get_slides_text())
        assert "Slide 1: Hello | First point" in text and "Slide 2: Renamed" in text
        s.call(lambda r: r.save_as(str(tmp_path), "deck", ".pdf"))
        assert os.path.isfile(tmp_path / "deck.pdf")
    finally:
        _close(s)
