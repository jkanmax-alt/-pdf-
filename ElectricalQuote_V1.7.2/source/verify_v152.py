"""Live regression from supplied drawings; never require purchased model to match drawing."""
import os
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import fitz
from segmentation_v15 import detect_page
from worker_v15 import run_one
from core import locate_tesseract, normalize_recognition_row

BASE=Path(__file__).resolve().parent.parent
assert locate_tesseract(), 'Tesseract OCR missing'

def scan(pdf,idx):
    with fitz.open(str(pdf)) as doc:
        regions=detect_page(doc,0)
    r={'id':f'verify_{idx}','page':1,'box':regions[idx],'cabinet':'待确认柜号'}
    return run_one((str(pdf),r,CACHE))['rows']

def feeder(rows):return sorted((r for r in rows if r.get('record_role')=='feeder'),key=lambda r:r['physical_row_index'])

def verify_model_rows(rows):
    for r in rows:
        assert 'MCB ' not in r['kind'] and 'MCCB ' not in r['kind'] and 'RCBO ' not in r['kind'],r
        if r['kind'] in ('微型断路器','塑壳断路器','漏电断路器'):
            assert r['spec'].startswith({'微型断路器':'MCB-', '塑壳断路器':'MCCB-', '漏电断路器':'RCBO-'}[r['kind']]),r

with TemporaryDirectory(prefix='eqv152test_') as CACHE:
    full=BASE/'samples'/'XinYongLian_full_drawings.pdf'
    single=BASE/'samples'/'1-4AP3_test.pdf'
    pp1=scan(full,0);f1=feeder(pp1);verify_model_rows(pp1)
    assert len(f1)==11,('PP1 feed count',len(f1))
    assert Counter(r['spec'] for r in f1)==Counter({'MCCB-TM-80A/3P':3,'MCCB-TM-100A/3P':1,'MCB-D16A/3P':5,'RCBO-C20A/2P':2}),[r['spec'] for r in f1]
    assert any(r['kind']=='电流互感器' and r['spec']=='200/5A' and r['qty'] is None for r in pp1)
    print('PASS 1-1PP1: 11 independent rows, breaker classifications and quantities')

    pp3=scan(full,1);f3=feeder(pp3);verify_model_rows(pp3)
    assert len(f3)==20,('PP3 feed count',len(f3))
    want=Counter({'MCB-D40A/3P':7,'MCB-D63A/3P':8,'RCBO-C20A/2P':1,'RCBO-C16A/2P':1,'RCBO-C16A/4P':1,'MCCB-TM-100A/3P':1,'MCCB-TM-63A/3P':1})
    assert Counter(r['spec'] for r in f3)==want,[(r['physical_row_index'],r['spec']) for r in f3]
    assert len([r for r in f3 if not r['tag']])>0,'OCR uncertainty should remain visible'
    assert len({r['tag'] for r in f3 if r['tag']})==len([r for r in f3 if r['tag']]),'No duplicate/conflicted tags should be emitted'
    print(f'PASS 1-1PP3: 20 physical rows, 7x D40, 8x D63, 3x RCBO, 2x MCCB; {sum(not r["tag"] for r in f3)} printed tags need review')

    ap3=scan(single,0);f=feeder(ap3);verify_model_rows(ap3)
    assert len(f)==14,len(f)
    assert [r['spec'] for r in f][3]=='MCB-C10A/1P+N'
    assert [r['spec'] for r in f][7]=='RCBO-C16A/2P'
    assert [r['spec'] for r in f][-2:]==['MCCB-TM-63A/3P']*2
    print('PASS 1-4AP3: 14 physical rows; W4/W8/W13/W14 ratings; no category/model mixing')

    # Backward-compatibility: an old project row still gets a clean display.
    old={'kind':'MCB 微型断路器','spec':'D16A/3P','raw':'MCB-D16A/3P'}
    normalize_recognition_row(old)
    assert old['kind']=='微型断路器' and old['spec']=='MCB-D16A/3P'
    print('PASS legacy project category/model migration')
print('All V1.5.2 tests passed')
