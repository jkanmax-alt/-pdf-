"""Live regression tests from supplied XinYongLian PDF. Does not use quotation guesses."""
import os,tempfile
import fitz
from segmentation_v15 import detect_page
from worker_v15 import run_one

P=os.path.abspath(os.path.join(os.path.dirname(__file__),'../samples/XinYongLian_full_drawings.pdf'))
with fitz.open(P) as doc:
    counts=[len(detect_page(doc,i)) for i in range(len(doc))]
    assert counts==[7,9,3,5,7,7,6],counts
    six=detect_page(doc,5)
    two=detect_page(doc,1)
print('PASS segmentation: 7-page drawing, 44 independent candidate panels; page 6 has 7')
with tempfile.TemporaryDirectory(prefix='electrical_v153_test_') as cache:
    def scan(page,idx,rect):
        return run_one((P,{'id':f'test_{page}_{idx}','page':page,'box':rect,'cabinet':('1-1VFD1' if page==2 else '待确认柜号')},cache))
    main=scan(6,4,six[3]);rows=main['rows']
    assert sum(r['kind']=='塑壳断路器' and r['spec']=='MCCB-TM-80A/3P' and r.get('record_role')=='incoming' for r in rows)==1,rows
    assert sum(r.get('record_role')=='feeder' for r in rows)==4
    print('PASS 1-2AL0: 4 outgoing feeders + 80A/3P incoming MCCB')
    tiny=scan(6,7,six[6]);r=tiny['rows']
    for kind,spec in [('微型断路器','MCB-C25A/3P'),('漏电断路器','RCBO-C16A/2P'),('漏电断路器','RCBO-C16A/4P')]:
        assert sum(x['kind']==kind and x['spec']==spec for x in r)==1,[(x['kind'],x['spec']) for x in r]
    print('PASS two-row IP67 drawing: 1 main MCB and 2 distinct RCBO feeders')
    vfd=scan(2,1,two[0]);vfd_rows=vfd['rows'];c=sum(x['kind']=='变频器' for x in vfd_rows)
    assert c==2,[(x['kind'],x['spec']) for x in vfd_rows]
    print('PASS VFD branch candidates: 2 visible VFD symbols (power still needs human review)')
print('All V1.5.3 specific checks passed.')
