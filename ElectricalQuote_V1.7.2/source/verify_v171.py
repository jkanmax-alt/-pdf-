"""V1.7.1 deterministic regressions, segmentation, and optional real OCR checks."""
from pathlib import Path
import sys
import unittest

BASE=Path(__file__).resolve().parent

def check(full=False):
    suite=unittest.defaultTestLoader.discover(str(BASE),pattern='test_*fixes.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    from verify_v170 import check as check_v170
    check_v170(full=full)
    if full:
        from verify_v160 import check as check_v160
        check_v160()
        import tempfile,fitz
        from worker_v16 import run_one
        from segmentation_v16 import detect_page
        pdf=BASE.parent/'samples'/'1-4AP3_test.pdf'
        with fitz.open(pdf) as doc:box=detect_page(doc,0)[0]
        with tempfile.TemporaryDirectory() as cache:
            data=run_one((str(pdf),dict(id='1-4AP3',page=1,box=box,cabinet='1-4AP3'),cache))
            assert len([r for r in data['rows'] if r.get('record_role')=='feeder'])==14
            ct=[r for r in data['rows'] if r.get('kind')=='电流互感器']
            assert ct and all(r.get('qty') is None or r.get('quantity_source')=='图纸数量标注' or r.get('quantity_verified') or (r.get('qty')==3 and r.get('quantity_source','').startswith('用户规则：主进线3P')) for r in ct)
            print('PASS: 1-4AP3 14 feeders; CT quantity has symbol evidence or explicit user three-phase rule',flush=True)
    print('V1.7.1 CHECKS PASSED'+(' (including real PDF OCR)' if full else ' (quick mode)'),flush=True)

if __name__=='__main__':check(full='--full' in sys.argv)
