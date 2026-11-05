"""V1.6: find independent electrical drawing frames (including gridded vertical layouts).

The old rectangle detector follows complete ink contours; it tends to return the
A1 sheet border for pages with many tables. Long-line morphology separates
individual cabinet tables without inspecting text.
"""
from __future__ import annotations
import fitz, numpy as np, re
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


def _split_stacked_frames(page, regions):
    """Split a contour containing multiple complete vector panel bodies.

    Body borders are independent from their short title rows. Require separate
    full-width frames, so table cells cannot split a cabinet by themselves.
    """
    bodies=[]
    for path in page.get_drawings():
        r=path['rect']
        if r.width>120 and r.height>100 and any(i[0] in ('qu','re') for i in path['items']):
            bodies.append(r)
    result=[]
    for box in regions:
        outer=fitz.Rect(box)
        matches=[r for r in bodies if abs(r.x0-outer.x0)<8 and abs(r.x1-outer.x1)<8
                 and outer.y0-3<=r.y0 and r.y1<=outer.y1+3 and r.height<outer.height*.92]
        matches.sort(key=lambda r:r.y0)
        separate=[]
        for r in matches:
            if not separate or r.y0>separate[-1].y1+5:separate.append(r)
        if len(separate)<2:
            result.append(box);continue
        title_height=min(40,max(0,separate[0].y0-outer.y0))
        for r in separate:
            result.append([round(r.x0,2),round(max(outer.y0,r.y0-title_height),2),round(r.x1,2),round(r.y1,2)])
    return sorted(result,key=lambda b:(round(b[1]/50),b[0],b[1]))


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
            return _split_stacked_frames(p,_complete_vector_frames(p,grid))
        if len(grid)==1 and not old:return _split_stacked_frames(p,_complete_vector_frames(p,grid))
        return _split_stacked_frames(p,_complete_vector_frames(p,old))
    except Exception:
        return _split_stacked_frames(p,_complete_vector_frames(p,old))


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
    from ocr_runtime import initialize_ocr
    initialize_ocr()
    # Read the title/CABLE NO separately before upstream breaker legends can
    # introduce a different cabinet number. Enlarge fine CAD outline lettering.
    normalized=img.resize((img.width*2,img.height*2))
    patterns=(r'(?<![A-Z0-9])\d{1,2}\s*-\s*\d{1,2}\s*-?\s*(?:APZ|VFD|PP|AP|AL|UPS)\s*\d{1,3}(?![0-9])',
              r'(?<![A-Z0-9])[1I\d]\s*(?:ACP|KT|AP|AL|PP|VFD|AT|XFP)\s*-?\s*\d{1,3}(?![0-9])')
    for fraction,psm in ((.23,6),(.38,6),(.23,11),(1,6)):
        crop=normalized.crop((0,0,normalized.width,max(1,int(normalized.height*fraction))))
        text=pytesseract.image_to_string(crop,lang='eng',config=f'--psm {psm}').upper()
        text=text.replace('—','-').replace('–','-')
        for pattern in patterns:
            match=re.search(pattern,text)
            if match:return re.sub(r'^I(?=ACP|KT|AP|AL|PP|VFD|AT|XFP)','1',re.sub(r'\s+','',match.group(0)))
    return ''
