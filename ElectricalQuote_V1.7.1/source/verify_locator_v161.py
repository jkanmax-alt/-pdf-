from pathlib import Path
import fitz
from worker_v16 import run_one
base=Path(__file__).resolve().parent
p=base.parent/'samples'/'1-4AP3_test.pdf'
d=fitz.open(str(p));page=d[0]
r={'id':'verify_ap3','page':1,'box':[page.rect.x0,page.rect.y0,page.rect.x1,page.rect.y1],'cabinet':'1-4AP3','rotation_override':'自动'}
a=run_one((str(p),r,str(base/'cache')))
rows=a['rows']
assert len([x for x in rows if x.get('record_role')=='feeder'])==14,len(rows)
assert all(x.get('location_quality')!='估计' for x in rows)
assert all(not x.get('pdf_boxes') or x.get('location_quality') in ('文字实测','符号实测','人工标定') for x in rows)
print('PASS: 14 feeders; evidence boxes are observed, not guessed; total rows:',len(rows))
