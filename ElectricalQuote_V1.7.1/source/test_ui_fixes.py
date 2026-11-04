"""Headless regression checks for reviewed records and project/PDF association."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
from app_v16 import Main
from core import aggregate


class Var:
    def __init__(self, value=None): self.value = value
    def set(self, value): self.value = value
    def get(self): return self.value


class UiFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.messages = patch('app_v16.messagebox').start()
        self.addCleanup(patch.stopall)
        self.messages.askyesno.return_value = True

    def model(self):
        app = Main.__new__(Main)
        app.root = Mock()
        app.busy = False
        app.doc = None
        app.pdf_path = ''
        app.missing_pdf_path = ''
        app.project_pdf_sha256 = ''
        app.page = 0
        app.rows = []
        app.regions = [dict(id='r1', page=2, box=[10, 10, 100, 150],
                            cabinet='AP1', state='已识别', count=0)]
        app.active_region = 'r1'
        app.selected_region = lambda: app.regions[0] if app.regions else None
        app.canvas = Mock()
        app.page_label = Mock()
        app.tree = Mock()
        app.tree.get_children.return_value = ()
        app.keys = ['cabinet', 'page', 'kind', 'spec', 'qty', 'tag', 'status']
        app.render_regions = Mock()
        app.paint_regions = Mock()
        app.refresh = Mock()
        app.show_pdf = Mock()
        app.preview = Mock()
        app.note = Mock()
        for name, value in [('type', '柜'), ('direct', 0), ('vfd', 0),
                            ('fire', False), ('dual', False), ('lamp', True)]:
            setattr(app, name, Var(value))
        return app

    def row(self, **values):
        row = dict(region_id='r1', cabinet='AP1', page=2, kind='微型断路器',
                   spec='MCB-C16A/1P', qty=7, status='已确认', source='OCR')
        row.update(values)
        return row

    def result(self):
        return dict(region_id='r1', rows=[self.row(qty=1, status='待核对')],
                    diag=dict(cabinet='AP1'))

    def pdf(self, name='drawing.pdf', pages=2):
        path = self.directory / name
        doc = fitz.open()
        for _ in range(pages): doc.new_page(width=300, height=400)
        doc.save(path)
        doc.close()
        return path

    def test_repeat_recognition_never_overwrites_confirmed_rows(self):
        app = self.model()
        app.rows = [self.row()]
        original = copy.deepcopy(app.rows)
        for state in ['已识别', '需人工核对', '失败', '未识别']:
            with self.subTest(state=state):
                app.regions[0]['state'] = state
                app.receive_result(self.result())
                app.receive_result(self.result())
                self.assertEqual(app.rows, original)
                self.assertEqual(app.regions[0]['pending_ocr_result']['rows'][0]['qty'], 1)

    def test_manual_pending_changes_are_also_preserved(self):
        app = self.model()
        app.rows = [self.row(status='待核对', manual_modified=True)]
        app.receive_result(self.result())
        self.assertEqual(app.rows[0]['qty'], 7)

    def test_unreviewed_recognition_can_still_refresh(self):
        app = self.model()
        app.rows = [self.row(status='待核对')]
        app.receive_result(self.result())
        self.assertEqual(app.rows[0]['qty'], 1)

    def test_manual_add_is_bound_and_visible_in_current_cabinet(self):
        app = self.model()
        app.page = 8  # Browsing another page does not change the selected owner.
        app.dialog = lambda record: dict(record, qty=3, spec='MCB-C16A/1P')
        app.add()
        row = app.rows[0]
        self.assertEqual((row['region_id'], row['cabinet'], row['page']), ('r1', 'AP1', 2))
        self.assertEqual(row['status'], '待核对')
        self.assertEqual(row['quantity_source'], 'manual')
        Main.refresh(app)
        self.assertEqual(app.tree.insert.call_count, 1)
        visible = [r for r in app.rows if r.get('region_id') == app.active_region]
        self.assertEqual(aggregate(visible)[0]['qty'], 3)
        self.assertEqual(aggregate(app.rows)[0]['qty'], 3)

    def test_mutating_actions_are_blocked_while_busy(self):
        app = self.model()
        app.busy = True
        app.rows = [self.row()]
        original = copy.deepcopy(app.rows)
        with patch('app_v16.filedialog.askopenfilename') as picker:
            for name in ['add', 'edit', 'delete', 'add_region', 'replace_region',
                         'delete_region', 'rename_region', 'set_rotation',
                         'toggle_included', 'open_project', 'open_pdf', 'reattach_pdf']:
                getattr(app, name)()
            picker.assert_not_called()
        self.assertEqual(app.rows, original)

    def test_missing_project_pdf_detaches_old_document(self):
        app = self.model()
        old_document = Mock()
        app.doc = old_document
        app.pdf_path = '/old/A.pdf'
        project = self.directory / 'project.json'
        project.write_text(json.dumps(dict(pdf_path=str(self.directory / 'missing.pdf'),
                            rows=[self.row()], regions=app.regions)), encoding='utf8')
        with patch('app_v16.filedialog.askopenfilename', return_value=str(project)):
            app.open_project()
        old_document.close.assert_called_once()
        self.assertIsNone(app.doc)
        self.assertEqual(app.pdf_path, '')
        self.assertEqual(app.rows[0]['qty'], 7)
        self.assertEqual(len(app.regions), 1)
        self.assertTrue(app.missing_pdf_path)
        # Recognition cannot run against the previously opened A.pdf.
        with patch('app_v16.threading.Thread') as thread:
            app.start_tasks(app.regions)
            thread.assert_not_called()

    def test_reattach_preserves_records_and_region_coordinates(self):
        app = self.model()
        app.rows = [self.row()]
        app.missing_pdf_path = '/moved/original.pdf'
        rows = copy.deepcopy(app.rows)
        regions = copy.deepcopy(app.regions)
        pdf = self.pdf()
        with patch('app_v16.filedialog.askopenfilename', return_value=str(pdf)):
            app.reattach_pdf()
        self.addCleanup(app.doc.close)
        self.assertEqual(app.rows, rows)
        self.assertEqual(app.regions, regions)
        self.assertEqual(app.pdf_path, str(pdf))
        self.assertEqual(app.missing_pdf_path, '')
        self.assertEqual(app.project_pdf_sha256, Main.pdf_digest(pdf))

    def test_reattach_rejects_different_pdf_when_fingerprint_exists(self):
        app = self.model()
        app.rows = [self.row()]
        app.project_pdf_sha256 = Main.pdf_digest(self.pdf('original.pdf'))
        wrong = self.pdf('different.pdf')
        self.assertFalse(app.load_pdf(wrong, preserve_project=True))
        self.assertIsNone(app.doc)
        self.assertEqual(app.rows[0]['qty'], 7)
        self.messages.showerror.assert_called_once()

    def test_reattach_rejects_missing_project_pages(self):
        app = self.model()
        app.rows = [self.row()]
        self.assertFalse(app.load_pdf(self.pdf(pages=1), preserve_project=True))
        self.assertEqual(app.rows[0]['qty'], 7)
        self.assertIsNone(app.doc)

    def test_failed_new_pdf_does_not_close_current_document(self):
        app = self.model()
        old_document = Mock()
        app.doc = old_document
        app.pdf_path = '/old/A.pdf'
        self.assertFalse(app.load_pdf(self.directory / 'missing.pdf'))
        self.assertIs(app.doc, old_document)
        self.assertEqual(app.pdf_path, '/old/A.pdf')
        old_document.close.assert_not_called()

    def test_edit_marks_manual_quantity_without_auto_confirming(self):
        app = self.model()
        app.rows = [self.row(status='待核对')]
        app.selected = lambda: 0
        app.dialog = lambda row: dict(row, qty=4)
        app.edit()
        self.assertEqual(app.rows[0]['status'], '待核对')
        self.assertEqual(app.rows[0]['quantity_source'], 'manual')
        app.receive_result(self.result())
        self.assertEqual(app.rows[0]['qty'], 4)

    def test_summary_separates_confirmed_pending_and_unknown_quantities(self):
        app = self.model()
        app.rows = [self.row(qty=3), self.row(qty=2, status='待核对'),
                    self.row(qty=None, status='待核对')]
        win, text = Mock(), Mock()
        with patch('app_v16.tk.Toplevel', return_value=win), patch('app_v16.tk.Text', return_value=text):
            app.show_summary()
        displayed = ''.join(call.args[1] for call in text.insert.call_args_list)
        self.assertIn('候选已知：5', displayed)
        self.assertIn('已确认：3', displayed)
        self.assertIn('待核对已知：2', displayed)
        self.assertIn('未知数量记录：1', displayed)

    def test_quality_exposes_geometry_and_unresolved_branch_diagnostics(self):
        app = self.model()
        app.rows = [self.row(qty=None, status='待核对')]
        app.regions[0]['last_diag'] = dict(layout='vertical', feeders=8,
            unresolved_branches=2, geometry_warnings=['两组不等间距支路'],
            unreadable_tags=['W位号不清'], geometry=dict(unassigned_lines=[12, 80]))
        win, text = Mock(), Mock()
        with patch('app_v16.tk.Toplevel', return_value=win), patch('app_v16.tk.Text', return_value=text):
            app.show_quality()
        displayed = ''.join(call.args[1] for call in text.insert.call_args_list)
        for expected in ['未知数量记录：1', '未确认支路：2', '两组不等间距支路', 'W位号不清', '2条孤立线']:
            self.assertIn(expected, displayed)

    def test_unlinked_project_cannot_mark_symbols_or_move_on_stale_image(self):
        app = self.model()
        app.image = None
        app.mark_selected_device()
        app.move_to_box([10, 10, 100, 150])
        app.canvas.create_rectangle.assert_not_called()
        self.messages.showinfo.assert_called_once()

    def test_manual_symbol_marking_is_protected_without_confirming_quantity(self):
        app = self.model()
        app.rows = [self.row(status='待核对')]
        app.frame_edit = Var(False)
        app.mark_row_idx = 0
        app.ocr_rect = (20, 30, 80, 90)
        app.zoom = Var(1)
        app.doc = fitz.open(self.pdf())
        self.addCleanup(app.doc.close)
        app.page = 1
        app.focus_selected = Mock()
        with patch('app_v16.PreviousMain.up'):
            app.up(Mock())
        self.assertTrue(app.rows[0]['manual_modified'])
        self.assertEqual(app.rows[0]['status'], '待核对')
        self.assertEqual(app.rows[0]['qty'], 7)
        original = copy.deepcopy(app.rows)
        app.receive_result(self.result())
        self.assertEqual(app.rows, original)

    def test_legacy_manual_symbol_coordinates_are_protected(self):
        app = self.model()
        app.rows = [self.row(status='待核对', location_quality='人工标定',
                             evidence_type='verified_symbol', pdf_boxes=[[20, 30, 80, 90]])]
        original = copy.deepcopy(app.rows)
        app.receive_result(self.result())
        self.assertEqual(app.rows, original)


if __name__ == '__main__': unittest.main(verbosity=2)
