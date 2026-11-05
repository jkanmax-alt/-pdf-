"""Exercise the shipped EXE, real OCR, Tk, spawned workers and Excel export.

The drawing is synthetic. No customer drawings or historical prices are used.
Run from the EXE with --portable-smoke-test --report <absolute JSON path>.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch


def make_test_pdf(path):
    import fitz
    doc=fitz.open();page=doc.new_page(width=700,height=900)
    page.draw_rect(fitz.Rect(20,20,680,880),color=(0,0,0),width=1)
    page.insert_text((35,45),'PANEL NO: 1-1AP1',fontsize=12)
    page.insert_text((35,65),'CABLE NO: 1-1AP1',fontsize=10)
    page.insert_text((35,85),'PORTABLE OCR ACCEPTANCE TEST',fontsize=9)
    page.draw_line((200,120),(200,690),width=1)
    for x in (510,560,635):page.draw_line((x,100),(x,720),width=1)
    for i in range(11):
        y=150+i*45
        page.draw_line((200,y),(680,y),width=.8)
        page.draw_line((245,y+6),(262,y-3),width=.8)
        page.insert_text((205,y-9),'MCB-C16A/1P',fontsize=10)
        page.insert_text((520,y-9),'W'+str(i+1),fontsize=10)
        page.insert_text((575,y-9),'MOTOR',fontsize=8)
        page.insert_text((645,y-9),'1kW',fontsize=8)
    doc.save(path);doc.close()


def main(report_path):
    from ocr_runtime import self_check
    report_path=Path(report_path).resolve();report_path.parent.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'frozen':bool(getattr(sys,'frozen',False)),
            'executable':sys.executable,'cwd':str(Path.cwd()),'stages':{},
            'test_scope':'synthetic PDF; actual Tk GUI, OCR, spawned worker and Excel export'}
    root=None;app=None
    try:
        report['ocr']=self_check()
        if not report['ocr']['ok']:raise RuntimeError('OCR startup self-check failed')
        if report['frozen'] and not report['ocr'].get('bundled'):
            raise RuntimeError('Frozen EXE used an external OCR engine')
        base=Path(getattr(sys,'_MEIPASS',Path(sys.executable).parent)).resolve()
        deps={}
        for name in ('fitz','pytesseract','PIL','cv2','numpy','openpyxl','tkinter'):
            module=importlib.import_module(name)
            location=Path(module.__file__).resolve();deps[name]=str(location)
            if report['frozen'] and not location.is_relative_to(base):
                raise RuntimeError('Dependency was imported outside the bundle: '+name)
        report['dependencies']=deps;report['stages']['imports']=True
        import tkinter as tk
        from app_v16 import Main
        # Capture dialogs without dismissing genuine errors as successful tests.
        errors=[]
        with patch('tkinter.messagebox.showerror',side_effect=lambda *a,**kw:errors.append(str(a))), \
             patch('tkinter.messagebox.showwarning',side_effect=lambda *a,**kw:errors.append(str(a))), \
             patch('tkinter.messagebox.showinfo',return_value='ok'), \
             patch('tkinter.messagebox.askyesno',return_value=True):
            root=tk.Tk();app=Main(root);root.update()
            report['stages']['gui_startup']=True
            with tempfile.TemporaryDirectory(prefix='ElectricalQuote-smoke-') as td:
                drawing=Path(td)/'synthetic.pdf';make_test_pdf(drawing)
                if not app.load_pdf(drawing):raise RuntimeError('GUI could not import generated PDF')
                report['stages']['pdf_import']=True
                app.detect_regions();root.update()
                if not app.regions:raise RuntimeError('Automatic panel segmentation returned no regions')
                report['region_count']=len(app.regions);report['stages']['segmentation']=True
                app.start_batch();deadline=time.monotonic()+240
                while app.busy and time.monotonic()<deadline:
                    root.update();time.sleep(.05)
                root.update()
                if app.busy:raise TimeoutError('Frozen spawned OCR worker did not finish within 240 seconds')
                if errors:raise RuntimeError('GUI errors: '+repr(errors))
                if any(r.get('state')=='失败' for r in app.regions):raise RuntimeError('OCR worker failed')
                breakers=[r for r in app.rows if r.get('kind')=='微型断路器' and '16A/1P' in r.get('spec','')]
                if len(breakers)!=11:
                    raise RuntimeError(f'Expected 11 independent 16A/1P breakers from the synthetic PDF, got {len(breakers)}')
                report['recognized_expected_breakers']=len(breakers)
                report['stages']['spawned_ocr_recognition']=True
                output=Path(td)/'export.xlsx'
                with patch('tkinter.filedialog.asksaveasfilename',return_value=str(output)):
                    app.export_xlsx()
                if errors:raise RuntimeError('Excel export GUI errors: '+repr(errors))
                from openpyxl import load_workbook
                wb=load_workbook(output,read_only=True)
                try:
                    if wb['图纸识别明细'].max_row<2:raise RuntimeError('Exported workbook has no recognized data')
                    report['exported_sheets']=wb.sheetnames
                finally:wb.close()
                report['stages']['excel_export']=True
            report['ok']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        if app and app.doc:
            app.doc.close();app.doc=None
        if root:
            try:root.destroy()
            except Exception:pass
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
