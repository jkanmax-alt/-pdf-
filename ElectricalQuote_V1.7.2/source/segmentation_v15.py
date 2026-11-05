"""Detect independent boxed single-line drawings on a multi-panel PDF page.
Regions are PDF-point coordinates; no OCR guesses are required to segment.
"""
from __future__ import annotations
import fitz
import numpy as np
import re
import os
os.environ.setdefault('OMP_THREAD_LIMIT','1')
from concurrent.futures import ThreadPoolExecutor
from PIL import Image


def _iou(a,b):
    x0=max(a[0],b[0]); y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
    inter=max(0,x1-x0)*max(0,y1-y0)
    aa=max(0,a[2]-a[0])*max(0,a[3]-a[1]);bb=max(0,b[2]-b[0])*max(0,b[3]-b[1]);
    return inter / max(.01,aa+bb-inter)


def _filter_regions(regions,page_rect):
    W,H=page_rect.width,page_rect.height
    good=[]
    for b in regions:
        x0,y0,x1,y1=b;w=x1-x0;h=y1-y0
        if w < max(125,W*.12) or h < max(105,H*.065):continue
        if w>W*.90 or h>H*.93:continue
        if w/h>5.5 or h/w>6.0:continue
        if x0 < 0 or y0 < 0 or x1>W+3 or y1>H+3:continue
        good.append([round(float(v),2) for v in b])
    # Outer complete frame should win over inset table frame with large overlap.
    good.sort(key=lambda b:(b[2]-b[0])*(b[3]-b[1]),reverse=True)
    kept=[]
    for b in good:
        if any(_iou(b,k)>.63 or (b[0]>=k[0]-3 and b[1]>=k[1]-3 and b[2]<=k[2]+3 and b[3]<=k[3]+3) for k in kept):continue
        kept.append(b)
    return sorted(kept,key=lambda b:(round(b[1]/50),b[0],b[1]))


def detect_page(doc,page_index:int,scale=1.5):
    page=doc[page_index];W,H=page.rect.width,page.rect.height
    candidates=[]
    try:
        import cv2
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
        rgb=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        ink=cv2.threshold(gray,205,255,cv2.THRESH_BINARY_INV)[1]
        cont,_=cv2.findContours(ink,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in cont:
            x,y,w,h=cv2.boundingRect(c)
            if w<.12*pix.width or h<.11*pix.height:continue
            peri=cv2.arcLength(c,True)
            if peri<=0:continue
            poly=cv2.approxPolyDP(c,.018*peri,True)
            if 4<=len(poly)<=9:
                candidates.append([x/scale,y/scale,(x+w)/scale,(y+h)/scale])
    except ImportError:
        pass
    # Vector-path fallback for PDFs without cv2, as well as thin rectangular lines.
    # Always include actual PDF rectangle paths: small two-row cabinets can be
    # missed by raster contour approximation even when other regions are found.
    if True:
        for path in page.get_drawings():
            r=path['rect']
            if r.width>W*.12 and r.height>max(105,H*.065) and r.width<W*.90 and r.height<H*.93:
                if any(cmd[0]=='re' for cmd in path.get('items',[])):
                    candidates.append([r.x0,r.y0,r.x1,r.y1])
    found=_filter_regions(candidates,page.rect)
    # Single schematic sheets may contain a narrow inner table rectangle.
    # Do not mistake that internal table for the entire panel.
    if len(found)==1 and ((found[0][2]-found[0][0])*(found[0][3]-found[0][1]) < W*H*.50):
        found=[]
    if not found:
        # Single panel page fallback: user can edit crop before recognizing.
        found=[[round(W*.015,2),round(H*.015,2),round(W*.985,2),round(H*.985,2)]]
    return found


def _cabinet_name_from_header(image):
    """OCR only the drawing's header, not its cable legends or power entries.

    No purchasing substitutions. An unclear/absent cabinet number stays unknown.
    """
    try:
        import pytesseract
        from ocr_runtime import initialize_ocr
        initialize_ocr()
        text=pytesseract.image_to_string(image,lang='eng',config='--psm 6')
        text=text.upper().replace('—','-').replace('–','-').replace('~','-')
        # Prefer the actual CABLE NO. The feeder's upstream source may have
        # another cabinet number and must never win over the title's label.
        candidates=[]
        for m in re.finditer(r'(?:\d{1,2}\s*-\s*\d{1,2}\s*[-]?\s*)(?:APZ|VFD|PP|AP|AL|UPS)\s*\d{1,3}',text):
            value=re.sub(r'\s+','',m.group(0)).replace('--','-')
            prefix=text[max(0,m.start()-32):m.start()]
            score=10 if re.search(r'CABL[E3]?\s*N[O0][^\n]{0,20}$',prefix) else 0
            # Title lines and CABLE NO are ahead of any upstream legends.
            score-=m.start()/1000
            candidates.append((score,value))
        if candidates:return max(candidates)[1]
        # Some diagrams have Chinese-only titles without a standard CABINET NO.
        # Only attempt this if the Chinese trained data is installed.
        try:
            langs=pytesseract.get_languages(config='')
            if 'chi_sim' in langs:
                cn=pytesseract.image_to_string(image,lang='chi_sim+eng',config='--psm 6')
                for line in cn.splitlines():
                    line=line.strip()
                    if re.search(r'[\u4e00-\u9fff]{3,}',line) and 3<=len(line)<=36:
                        if not any(k in line for k in ('馈线编号','电缆编号','防护等级','回路编号','备注','图纸编号','负荷名称','负荷容量')):
                            return line
        except Exception:pass
    except Exception:
        pass
    return ''


def detect_document(pdf_path, recognize_names=True):
    doc=fitz.open(pdf_path)
    try:
        result=[]
        headers=[]
        for page_index in range(len(doc)):
            page=doc[page_index]
            for j,rect in enumerate(detect_page(doc,page_index),1):
                row={'id':f'p{page_index+1}_r{j}', 'page':page_index+1,
                     'box':rect,'cabinet':'待确认柜号','state':'未识别','count':0}
                result.append(row)
                if recognize_names:
                    b=fitz.Rect(rect)
                    header=fitz.Rect(b.x0,b.y0,b.x0+b.width*.57,b.y0+b.height*.22) & page.rect
                    pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),clip=header,alpha=False)
                    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    headers.append(image)
        if recognize_names and headers:
            # pytesseract starts an external Tesseract process. A small thread
            # pool can overlap independent panels without sharing MuPDF objects.
            with ThreadPoolExecutor(max_workers=min(4,len(headers))) as pool:
                for row,name in zip(result,pool.map(_cabinet_name_from_header,headers)):
                    if name:row['cabinet']=name
        return result
    finally:doc.close()
