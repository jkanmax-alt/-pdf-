"""Regressions for panel merging, actual motor symbols and user sizing rules."""
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fitz
from electrical_symbols import vector_motor_symbols, load_selection, apply_ct_evidence, recognize_motor_symbols
from segmentation_v16 import _split_stacked_frames, _read_header
from core import save_xlsx

class FeedbackTests(unittest.TestCase):
    def test_vertical_header_keeps_legacy_i_to_one_correction(self):
        from PIL import Image
        with patch('pytesseract.image_to_string',return_value='IACP1'):
            self.assertEqual(_read_header(Image.new('RGB',(400,120),'white')),'1ACP1')

    def test_two_complete_frames_split_but_table_cells_do_not(self):
        class Page:
            def get_drawings(self):
                return [dict(rect=fitz.Rect(10,30,600,500),items=[('qu',)]),
                        dict(rect=fitz.Rect(10,560,600,900),items=[('qu',)]),
                        dict(rect=fitz.Rect(400,100,600,300),items=[('re',)])]
        boxes=_split_stacked_frames(Page(),[[10,10,600,900]])
        self.assertEqual(len(boxes),2)
        self.assertEqual(boxes[0],[10,10,600,500])
        self.assertEqual(boxes[1],[10,540,600,900])

    def test_symbols_are_detected_without_component_names(self):
        doc=fitz.open();page=doc.new_page(width=600,height=600)
        shape=page.new_shape()
        shape.draw_bezier((105,100),(105,101.4),(104,102.5),(102.5,102.5))
        shape.draw_bezier((102.5,102.5),(101,102.5),(100,101.4),(100,100))
        shape.finish(closePath=False);shape.commit()
        page.draw_line((102.5,109),(122,100))
        page.draw_rect(fitz.Rect(145,95,155,110))
        shape=page.new_shape();shape.draw_polyline([(145,100),(148,100),(148,105),(152,105),(152,100),(155,100)])
        shape.finish(closePath=False);shape.commit()
        page.draw_rect(fitz.Rect(200,95,210,110))  # Plain box is NOT a thermal relay.
        self.assertCountEqual([k for k,b in vector_motor_symbols(page,page.rect)],['接触器','热继电器'])
        with patch('electrical_symbols._ocr',return_value=''):
            rows=recognize_motor_symbols(page,page.rect,[],'A',1)
        self.assertEqual(sum(r['qty'] for r in rows),2)
        self.assertTrue(all(r['evidence_type']=='verified_symbol' for r in rows))
        # Two OCR renderings disagree on the decimal point: no load-based
        # advice may be generated from 15 versus 1.5 kW.
        for x in (450,480,550):page.draw_line((x,10),(x,590))
        def read(page,box,psm=7,scale=5):
            if psm==6:return '15' if scale==5 else '1.5'
            return ''
        with patch('electrical_symbols._ocr',side_effect=read):
            uncertain=recognize_motor_symbols(page,page.rect,[],'A',1)
        self.assertTrue(all(not r.get('selection_advice') for r in uncertain))
        doc.close()

    def test_ct_three_rings_are_one_three_piece_set(self):
        doc=fitz.open();page=doc.new_page(width=600,height=600)
        for cy in (100,114,128):
            points=[fitz.Point(100+4*math.cos(a*math.pi/10),cy+4*math.sin(a*math.pi/10)) for a in range(21)]
            shape=page.new_shape();shape.draw_polyline(points);shape.finish(closePath=False);shape.commit()
        row=dict(kind='电流互感器',qty=None,spec='400/5A')
        apply_ct_evidence(page,page.rect,[row])
        self.assertEqual(row['qty'],3)
        self.assertEqual(len(row['pdf_boxes']),3)
        self.assertTrue(row['quantity_verified'])
        # Symbol counting must not depend on the legacy feeder OCR having
        # already emitted a CT row.
        with patch('electrical_symbols._ocr',return_value='400/5A'):
            recovered=apply_ct_evidence(page,page.rect,[dict(kind='多功能仪表')])
        self.assertEqual([r['qty'] for r in recovered if r['kind']=='电流互感器'],[3])
        doc.close()

    def test_user_ct_convention_requires_main_three_phase_metering(self):
        doc=fitz.open();page=doc.new_page()
        row=dict(kind='电流互感器',qty=None)
        apply_ct_evidence(page,page.rect,[row,dict(kind='隔离开关',record_role='incoming',spec='DSL-250A/3P'),dict(kind='多功能仪表')])
        self.assertEqual(row['qty'],3)
        other=dict(kind='电流互感器',qty=None)
        apply_ct_evidence(page,page.rect,[other,dict(kind='微型断路器',record_role='feeder',spec='MCB-16A/3P')])
        self.assertIsNone(other['qty'])
        doc.close()

    def test_sizing_preserves_strict_margin_and_minimum(self):
        self.assertEqual(load_selection(2.2)['estimated_current_a'],4.4)
        self.assertEqual(load_selection(2.2)['contactor_suggested_a'],9)
        self.assertEqual(load_selection(5.5)['contactor_suggested_a'],18)
        self.assertEqual(load_selection(9/2/1.3)['contactor_suggested_a'],12)
        for value in (None,0,-1,float('nan')):self.assertIsNone(load_selection(value))

    def test_load_advice_is_exported_separately_from_drawing_rating(self):
        from openpyxl import load_workbook
        row=dict(cabinet='A',kind='接触器',spec='16A',qty=1,tag='W17',selection_advice=load_selection(5.5))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'export.xlsx';save_xlsx(path,[row]);w=load_workbook(path)
            self.assertEqual(w['图纸识别明细']['D2'].value,'16A')
            self.assertEqual(w['负载选型建议']['H2'].value,18)
            w.close()

if __name__=='__main__':unittest.main()
