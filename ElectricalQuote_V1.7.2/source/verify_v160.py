"""Non-GUI regression checks with physical evidence in the included test PDFs."""
from collections import Counter
from pathlib import Path
import tempfile
import fitz
from PIL import Image
from segmentation_v16 import detect_page
from worker_v16 import run_one
from orientation_v16 import detect_rotation, rotate, unrotate_box
from vertical_recognition_v16 import recognize_vertical

ROOT=Path(__file__).resolve().parent.parent

def check():
    anh=ROOT/'samples/Anhui_Fute_vertical_drawings.pdf'
    xin=ROOT/'samples/XinYongLian_full_drawings.pdf'
    single=ROOT/'samples/1-4AP3_test.pdf'
    for path,expected in [(anh,[6,6,9,6,6]),(xin,[7,9,3,6,7,7,6])]:
        doc=fitz.open(path)
        got=[len(detect_page(doc,i)) for i in range(len(doc))]
        assert got==expected,(path,got,expected)
        print(path.name, 'segmentation',got)
        doc.close()
    with tempfile.TemporaryDirectory() as td:
        doc=fitz.open(anh);box=detect_page(doc,0)[0]
        pix=doc[0].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(box),alpha=False)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        doc.close()
        for k in range(4):
            rotated=rotate(image,k)
            correction,meta=detect_rotation(rotated)
            assert (k+correction)%4==0,(k,correction)
            rows,d=recognize_vertical(rotate(rotated,correction),1)
            count=Counter((r['kind'],r['spec']) for r in rows)
            assert count[('塑壳断路器','MCCB-200A/3P')]==4,(k,count)
            assert count[('变频器','VFD 90kW')]==4,(k,count)
            assert count[('塑壳断路器','MCCB-630A/3P')]==1,(k,count)
            assert all(0<=v<=1 for v in unrotate_box([.2,.2,.3,.35],correction))
        print('Orientation 0/90/180/270 PASS: 4x MCCB 200A and 4x VFD 90kW')
        # Real worker includes PDF bbox mapping and original horizontal recognizer.
        z=run_one((str(xin),{'id':'reg_pp1','page':1,'box':detect_first(xin),'cabinet':'待确认柜号'},td))
        assert z['diag']['feeders']==11,z['diag']
        assert len([r for r in z['rows'] if r.get('pdf_boxes')])>10
        print('XinYongLian PP1: 11 feeders,',len(z['rows']),'records')
        # The full Excel writer is unchanged from V1.5.3; keep this
        # regression test fast and validate the structured CSV export.
        from core import save_csv
        save_csv(Path(td)/'tmp.csv',z['rows'])
        assert (Path(td)/'tmp.csv').stat().st_size>100
        print('CSV export PASS; existing Excel writer retained')
    print('V1.6.0 basic regression PASS')

def detect_first(p):
    doc=fitz.open(p)
    try:return detect_page(doc,0)[0]
    finally:doc.close()

if __name__=='__main__':check()
