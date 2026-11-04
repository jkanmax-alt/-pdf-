"""V1.7.2 feedback regressions and real screenshot-cabinet acceptance checks."""
import sys
import tempfile
from collections import Counter
from pathlib import Path
from verify_v171 import check as previous_check

def check(full=False):
    previous_check(full=full)
    if full:
        import fitz
        from PIL import Image
        from segmentation_v16 import detect_page,_read_header
        from worker_v16 import run_one
        pdf=Path(__file__).resolve().parent.parent/'samples/XinYongLian_full_drawings.pdf'
        with fitz.open(pdf) as doc:
            boxes=detect_page(doc,3)
            assert len(boxes)==6,'stacked AP3/PP2 must be independent'
            names=[]
            for box in boxes:
                b=fitz.Rect(box);clip=fitz.Rect(b.x0,b.y0,b.x0+b.width*.60,b.y0+b.height*.23)
                pix=doc[3].get_pixmap(matrix=fitz.Matrix(2.3,2.3),clip=clip,alpha=False)
                names.append(_read_header(Image.frombytes('RGB',(pix.width,pix.height),pix.samples)))
            assert names==['1-2AP2','1-2AP3','1-2AP4','1-2AP5','1-2PP2','1-2PP1'],names
        print('PASS: screenshot page cabinet labels and AP3/PP2 separation',flush=True)
        with tempfile.TemporaryDirectory() as cache:
            for index,nc,nt in [(0,10,10),(1,7,6)]:
                result=run_one((str(pdf),dict(id=names[index],page=4,box=boxes[index],cabinet=names[index]),cache))
                rows=result['rows'];counts=Counter(r['kind'] for r in rows)
                assert counts['接触器']==nc and counts['热继电器']==nt,counts
                ct=[r for r in rows if r['kind']=='电流互感器']
                assert len(ct)==1 and ct[0]['qty']==3,ct
                motor=[r for r in rows if r['kind'] in ('接触器','热继电器')]
                assert all(r.get('pdf_boxes') and r['evidence_type']=='verified_symbol' for r in motor)
                if index==0:
                    advised=[r for r in motor if r.get('selection_advice')]
                    assert advised and any(r['selection_advice']['load_kw']==1.5 for r in advised)
                    assert all(r['selection_advice']['contactor_suggested_a']==9 for r in advised)
                print('PASS:',names[index],nc,'contactors,',nt,'thermal relays, 3 CTs; measured symbols',flush=True)
    print('V1.7.2 CHECKS PASSED',flush=True)

if __name__=='__main__':check(full='--full' in sys.argv)
