"""V1.7 regression checks (quick by default, --full tests OCR)."""
from __future__ import annotations
import os,sys,fitz
from pathlib import Path
from segmentation_v16 import detect_page
from surge_recognition_v17 import parse_surge_text,surge_pair_warnings

ROOT=Path(__file__).resolve().parent.parent

def check(full=False):
    xin=ROOT/'samples/XinYongLian_full_drawings.pdf'
    anh=ROOT/'samples/Anhui_Fute_vertical_drawings.pdf'
    for pdf,expected in ((xin,[7,9,3,6,7,7,6]),(anh,[6,6,9,6,6])):
        with fitz.open(pdf) as d:
            counts=[len(detect_page(d,i)) for i in range(len(d))]
            assert counts==expected,(pdf.name,counts)
            print('PASS: segmentation',pdf.name,counts,flush=True)
    with fitz.open(xin) as d:
        # 1-2AP4 outer frame must include actual W-label column.
        box=detect_page(d,3)[2]
        assert box[2]>2140,('AP4 is cropped before actual W column',box)
        print('PASS: 1-2AP4 full frame',box,flush=True)
    sample='HKPD-SCB2/80/4P HKPD-B80/420/4P(8/20us) Uc=420V; In=40kA; Imax=80kA; Up=2.0kV; T2'
    e=parse_surge_text(sample)
    assert e['has_spd'] and e['has_scb'] and e['spd_model']=='HKPD-B80/420/4P'
    assert (e['spd_type'],e['imax_ka'],e['in_ka'],e['spd_pole'])==('T2',80.0,40.0,'4P')
    assert not parse_surge_text('HKPD-SCB2/80/4P')['has_spd']
    assert surge_pair_warnings([{'kind':'浪涌保护器','qty':1}])
    print('PASS: independent SPD/SCB model and surge parameter parsing',flush=True)
    if full:
        from worker_v16 import run_one
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            with fitz.open(xin) as d:
                cases=[(1,detect_page(d,0)[0],'1-1PP1',11),(1,detect_page(d,0)[1],'1-1PP3',20),(4,detect_page(d,3)[2],'1-2AP4',21)]
            for page,box,name,n in cases:
                data=run_one((str(xin),{'id':name,'page':page,'box':box,'cabinet':name,'rotation_override':'自动'},temp))
                feeds=[r for r in data['rows'] if r.get('record_role')=='feeder']
                assert len(feeds)==n,(name,len(feeds),n)
                if name=='1-2AP4':
                    assert [r['tag'] for r in feeds]==[f'W{i}' for i in range(1,22)]
                    assert next(r for r in feeds if r['tag']=='W16')['spec']=='RCBO-C20A/2P'
                    surge=[r for r in data['rows'] if r['kind']=='浪涌保护器']
                    assert len(surge)==1 and 'T2' in surge[0]['spec'] and 'Imax80kA' in surge[0]['spec']
                    assert any(r['kind']=='浪涌后备保护器' for r in data['rows'])
                print('PASS: complete OCR',name,n,'feeder records',flush=True)
    print('V1.7 CHECKS PASSED',flush=True)
if __name__=='__main__':check(full='--full' in sys.argv)
