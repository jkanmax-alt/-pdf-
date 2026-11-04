"""V1.6: find independent electrical drawing frames (including gridded vertical layouts).

The old rectangle detector follows complete ink contours; it tends to return the
A1 sheet border for pages with many tables. Long-line morphology separates
individual cabinet tables without inspecting text.
"""
from __future__ import annotations
import fitz, numpy as np
from PIL import Image
from segmentation_v15 import detect_page as legacy_detect_page, _filter_regions, _cabinet_name_from_header
from concurrent.futures import ThreadPoolExecutor


def _complete_vector_frames(page, regions):
    """Expand truncated inner-table boxes to a matching REAL outer PDF frame.

    Compare top, bottom and left with observed vector paths. A nearby frame in
    another cell cannot be used merely because it is close to the current box.
    """
    vector=[]
    for d in page.get_drawings():
        r=d.get('rect')
        if r and 80<r.width<page.rect.width*.8 and 90<r.height<page.rect.height*.9:
            vector.append(r)
    ans=[]
    for box in regions:
        a=fitz.Rect(box)
        candidates=[]
        for r in vector:
            if abs(r.x0-a.x0)>6 or abs(r.y0-a.y0)>6 or abs(r.y1-a.y1)>6:continue
            # Only accept observed geometry extending the same frame's right
            # border; never extend more than 45% into an unrelated panel.
            if a.x1+5<r.x1<=a.x1+a.width*.45:
                candidates.append(r)
        if candidates:
            b=max(candidates,key=lambda r:r.x1)
            ans.append([round(b.x0,2),round(min(a.y0,b.y0),2),round(b.x1,2),round(max(a.y1,b.y1),2)])
        else:ans.append(box)
    return ans


def detect_page(doc, page_index, scale=1.0):
    p=doc[page_index]; W=p.rect.width; H=p.rect.height
    old=legacy_detect_page(doc,page_index,scale=scale)
    try:
        import cv2
        pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
        arr=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3]
        ink=cv2.threshold(cv2.cvtColor(arr,cv2.COLOR_RGB2GRAY),210,255,cv2.THRESH_BINARY_INV)[1]
        length=max(18,int(min(pix.width,pix.height)*.013))
        horizontals=cv2.morphologyEx(ink,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(length,1)))
        verticals=cv2.morphologyEx(ink,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,length)))
        lines=cv2.bitwise_or(horizontals,verticals)
        contours,_=cv2.findContours(lines,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        candidates=[]
        for c in contours:
            x,y,w,h=cv2.boundingRect(c)
            fw=w/scale;fh=h/scale
            if fw<max(125,W*.095) or fh<max(105,H*.060):continue
            if fw>W*.90 or fh>H*.93 or (fw*fh>W*H*.58):continue
            if not (.24<fw/max(fh,1)<6.2):continue
            candidates.append([x/scale,y/scale,(x+w)/scale,(y+h)/scale])
        grid=_filter_regions(candidates,p.rect)
        # On a dense A1 sheet the legacy routine may only find the sheet's
        # outer border; do not let that shadow multiple individual panels.
        if len(grid)>=2 and (len(old)<=1 or len(grid)>=len(old)*.75):
            return _complete_vector_frames(p,grid)
        if len(grid)==1 and not old:return _complete_vector_frames(p,grid)
        return _complete_vector_frames(p,old)
    except Exception:
        return _complete_vector_frames(p,old)


def detect_document(pdf_path,recognize_names=True):
    doc=fitz.open(pdf_path)
    try:
        result=[];headers=[]
        for idx,p in enumerate(doc):
            for n,b in enumerate(detect_page(doc,idx),1):
                r={'id':f'p{idx+1}_r{n}', 'page':idx+1,'box':[round(v,2) for v in b],
                   'cabinet':'待确认柜号','state':'未识别','count':0,'included':True,
                   'rotation_override':'自动'}
                result.append(r)
                if recognize_names:
                    bb=fitz.Rect(b)
                    clip=fitz.Rect(bb.x0,bb.y0,bb.x0+bb.width*.60,bb.y0+bb.height*.23)&p.rect
                    pix=p.get_pixmap(matrix=fitz.Matrix(2.3,2.3),clip=clip,alpha=False)
                    headers.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
        if headers:
            with ThreadPoolExecutor(max_workers=min(4,len(headers))) as pool:
                for r,name in zip(result,pool.map(_read_header,headers)):
                    if name:r['cabinet']=name
        return result
    finally:
        doc.close()


def _read_header(img):
    """Read both numeric cabinet ids (XinYongLian) and 1ACP1/1KT1 style."""
    import re,pytesseract
    t=pytesseract.image_to_string(img,lang='eng',config='--psm 6').upper().replace('—','-')
    # Prefer names on the PANEL NO or CABLE NO line; OCR may include other
    # upstream cabinet numbers deeper in the drawing.
    patterns=(r'\b\d{1,2}\s*-\s*\d{1,2}\s*-?\s*(?:APZ|VFD|PP|AP|AL|UPS)\s*\d{1,3}\b',
              r'\b\d\s*(?:ACP|KT|AP|AL|PP|VFD|AT|XFP)\s*[-]?\s*\d{1,3}\b')
    for p in patterns:
        m=re.search(p,t)
        if m:return re.sub(r'\s+','',m.group(0))
    # Vertical-branch schematics often put PANEL NO in a very short first row.
    # Cropping the actual value cell avoids OCR interference from the multiline
    # INCOMING SWITCH block directly beneath it.
    short=img.crop((int(img.width*.25),0,int(img.width*.68),int(img.height*.25)))
    title=pytesseract.image_to_string(short,lang='eng',config='--psm 7').upper().replace(' ','')
    m=re.search(r'\b[1I](?:ACP|KT|AP|AL|PP|VFD)[-]?\d+\b',title)
    if m:return re.sub(r'^I','1',m.group(0))
    return ''
