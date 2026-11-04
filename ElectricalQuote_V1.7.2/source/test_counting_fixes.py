"""Quantity/evidence/export/cache regressions; no GUI or network required."""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from core import (aggregate, quantity_value, normalize_recognition_row, recognize_cabinet_image,
                  ct_quantity_from_text, save_csv, save_xlsx)
from worker_v16 import cache_key, run_one


class CountingFixes(unittest.TestCase):
    def test_group_specific_pitch_reaches_ocr_crops_and_evidence(self):
        lines=[100,150,200,250,400,480,560,640]
        geometry={'pitch':80,'groups':[{'lines':lines[:4],'pitch':50},
                                      {'lines':lines[4:],'pitch':80}]}
        crops=[]
        def read(image,**kwargs):
            if image.width==585 and kwargs.get('config')=='--psm 7':crops.append(image.height)
            return 'MCB-C16A/1P'
        with patch('core.locate_tesseract',return_value='tesseract'), \
             patch('feeder_geometry_v152.detect_feeder_lines',return_value=(lines,geometry)), \
             patch('feeder_geometry_v152.read_drawn_tags',return_value=(['']*8,[])), \
             patch('core.ocr_image',return_value='1-1AP1'), \
             patch('pytesseract.image_to_string',side_effect=read), \
             patch('recognition_v14.upgrade_recognition',side_effect=lambda img,rows,diag:(rows,diag)):
            rows,_=recognize_cabinet_image(Image.new('RGB',(1000,1000),'white'))
        self.assertEqual(crops,[99]*4+[156]*4)
        self.assertEqual([r['pdf_rel_pitch'] for r in rows],[.05]*4+[.08]*4)
        self.assertEqual(sum(r['qty'] for r in rows),8)

    def test_candidates_confirmed_and_unknown_are_separate(self):
        rows=[dict(cabinet='A',kind='CT',spec='250/5A',qty=n,status=s)
              for n,s in [(3,'待核对'),(1,'已确认'),(None,'待核对')]]
        total=aggregate(rows)[0]
        self.assertEqual((total['qty'],total['confirmed_qty'],total['pending_qty'],
                          total['unknown_qty_count']),(4,1,3,1))
        self.assertEqual(aggregate(rows,confirmed_only=True)[0]['qty'],1)

    def test_unknown_and_invalid_quantities_never_become_one(self):
        for value in (None,'','nan','inf',-1,1.9,True,'invalid'):
            self.assertIsNone(quantity_value({'qty':value}))
        self.assertEqual(quantity_value({'qty':'0'}),0)
        self.assertEqual(quantity_value({'qty':'3'}),3)

    def test_ct_requires_printed_quantity_and_migrates_old_guess(self):
        self.assertIsNone(ct_quantity_from_text('CT 250/5A','250/5A'))
        self.assertEqual(ct_quantity_from_text('CT QTY=2 250/5A','250/5A'),2)
        self.assertEqual(ct_quantity_from_text('3×250/5A','250/5A'),3)
        r=dict(kind='电流互感器',spec='250/5A',qty=3,status='待核对',
               remark='三相常规3只为推定值，需用图纸符号复核')
        normalize_recognition_row(r)
        self.assertIsNone(r['qty'])
        self.assertEqual(r['legacy_inferred_qty'],3)
        normalize_recognition_row(r)
        self.assertIsNone(r['qty'])
        r.update(qty=2,status='已确认')
        normalize_recognition_row(r)
        self.assertEqual(r['qty'],2)
        r.update(status='待核对',quantity_source='manual',manual_modified=True)
        normalize_recognition_row(r)
        self.assertEqual(r['qty'],2)

    def test_export_round_trip_keeps_unknown_and_confirmation(self):
        from openpyxl import load_workbook
        rows=[dict(cabinet='A',kind='电流互感器',spec='250/5A',qty=None,
                   raw='=1+1',status='待核对',quantity_source='数量待核对'),
              dict(cabinet='A',kind='微型断路器',spec='MCB-C16A/1P',qty=2,status='已确认')]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'out.csv';save_csv(path,rows)
            with path.open(encoding='utf-8-sig',newline='') as f:data=list(csv.DictReader(f))
            self.assertEqual(data[0]['qty'],'')
            self.assertEqual(data[0]['quantity_unknown'],'True')
            self.assertEqual(data[1]['confirmed_qty'],'2')
            path=Path(td)/'out.xlsx';save_xlsx(path,rows)
            wb=load_workbook(path)
            try:
                self.assertIsNone(wb['图纸识别明细']['E2'].value)
                self.assertEqual(wb['图纸识别明细']['I2'].value,'=1+1')
                self.assertEqual(wb['图纸识别明细']['I2'].data_type,'s')
                self.assertEqual(wb['分类汇总']['G2'].value,1)
                self.assertEqual(wb['已确认汇总']['D2'].value,2)
                self.assertEqual(wb['已确认汇总'].max_row,2)
            finally:wb.close()


class CacheFixes(unittest.TestCase):
    def test_cache_rebinds_region_and_cabinet(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'file.pdf';p.write_bytes(b'only cache must be read')
            region=dict(id='new',page=1,box=[0,0,100,100],cabinet='NEW-CAB')
            cache=Path(td)/(cache_key(str(p),region)+'.json')
            cache.write_text(json.dumps(dict(region_id='old',diag={'cabinet':'OLD'},
                rows=[dict(region_id='old',cabinet='OLD',qty=1)])),encoding='utf-8')
            data=run_one((str(p),region,td))
            self.assertTrue(data['cached'])
            self.assertEqual(data['region_id'],'new')
            self.assertEqual(data['rows'][0]['region_id'],'new')
            self.assertEqual(data['rows'][0]['cabinet'],'NEW-CAB')

    def test_same_size_and_timestamp_different_pdf_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'file.pdf';p.write_bytes(b'AAAA')
            region=dict(id='x',page=1,box=[0,0,100,100])
            old=cache_key(str(p),region);stat=p.stat()
            p.write_bytes(b'BBBB');os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            self.assertNotEqual(cache_key(str(p),region),old)


if __name__=='__main__':unittest.main()
