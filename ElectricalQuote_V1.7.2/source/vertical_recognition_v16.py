"""P1: vertical outgoing branches + lower-column schedule on electrical one-lines.

Counts only physically observed breaker / VFD labels. Table power is an
attribute of a branch, not an instruction to manufacture a component.
"""
from __future__ import annotations
import re
import numpy as np
import cv2
from PIL import ImageOps, ImageEnhance

RATING=r'(?:[BCD])?\s*\d{1,4}\s*A'

def _groups(indices,gap):
    ans=[]
    for n in indices:
        n=int(n)
        if not ans or n-ans[-1][-1]>gap:ans.append([n])
        else:ans[-1].append(n)
    return [int(np.median(g)) for g in ans]

def find_vertical_columns(img):
    """Find physical branch columns through table grid, not from guessed ids."""
    gray=np.asarray(ImageOps.grayscale(img));h,w=gray.shape
    ink=gray<166
    band=ink[int(h*.61):int(h*.86)]
    projection=band.mean(axis=0)
    dividers=_groups(np.flatnonzero(projection>.61),max(3,int(w*.005)))
    dividers=[v for v in dividers if 0<=v<w]
    # Horizontal lines in the lower table must span most of the drawing.
    band_rows=ink[int(h*.58):int(h*.90),int(w*.17):int(w*.96)].mean(axis=1)
    line_count=len(_groups(np.flatnonzero(band_rows>.68),max(3,int(h*.003))))
    # The first interval is the row-title column and is not a feeder.
    valid=[]
    for a,b in zip(dividers[1:],dividers[2:]):
        if .025*w<b-a<.25*w:valid.append((a,b))
    if line_count<4 or len(valid)<2:return [],{'reason':'没有可靠的底部参数表/纵向支路列','column_count':0,'table_lines':line_count}
    return valid,{'reason':'底部参数表列与上方纵向支路对齐','column_count':len(valid),'table_lines':line_count}


def _breakers_from_text(text):
    # OCR corrections belong to numeric fields. A global O -> 0 destroys RCBO.
    t=text.upper().replace('—','-').replace('–','-')
    t=re.sub(r'([1-4])P[.,_]+',r'\1P ',t)
    # Keep label class intact; parsed category and PDF model are separate.
    m=re.search(r'\b(MCCB|MCB|RCBO|RCB0)\b\s*(?:[-=:_ ]*TM)?\s*[-=:_ ]*([1-4I])\s*P\s*(\+\s*N)?\s*[-=:_ ]*([BCD]?)\s*([0-9OIL]{1,4})\s*A',t)
    if m:
        typ,pole,neutral,curve,current=m.groups()
        typ=typ.replace('RCB0','RCBO')
        pole=pole.replace('I','1')
        current=current.translate(str.maketrans('OIL','011'))
        return typ,f'{typ}-{curve}{current}A/{pole}P'+('+N' if neutral else '')
    # Some drawings print 630 (no A) followed by 'In=630A' on next line.
    m=re.search(r'\b(MCCB|MCB|RCBO|RCB0)\b\s*([1-4I])\s*P\s*(\+\s*N)?\s*([0-9OIL]{2,4})\b',t)
    if m:
        typ,pole,neutral,observed=m.groups()
        current=observed.translate(str.maketrans('OIL','011'))
        # Confirm an independently printed current, normalizing its digits only.
        ratings=re.findall(r'(?<!\w)([0-9OIL]{2,4})\s*A\b',t)
        if any(n.translate(str.maketrans('OIL','011'))==current for n in ratings):
            typ=typ.replace('RCB0','RCBO')
            return typ,f'{typ}-{current}A/{pole.replace("I","1")}P'+('+N' if neutral else '')
    return None


def recognize_vertical(img,page=1,cabinet='待确认柜号'):
    import pytesseract
    from ocr_runtime import initialize_ocr
    initialize_ocr()
    w,h=img.size
    cols,geo=find_vertical_columns(img)
    if not cols:
        return [],{'mode':'vertical-fallback','feeders':0,'reason':geo['reason'],'cabinet':cabinet,'geometry':geo}
    # Read title and incoming once, and each *observed physical* feeder column.
    header=img.crop((int(w*.14),0,int(w*.50),int(h*.062)))
    header_text=pytesseract.image_to_string(header,lang='eng',config='--psm 7')
    title_match=re.search(r'\b\d\s*(?:ACP|KT|AP|AL|PP|VFD)\s*-?\s*\d+\b',header_text.upper())
    if title_match:cabinet=re.sub(r'\s+','',title_match.group(0))
    incoming=img.crop((int(w*.30),int(h*.05),int(w*.76),int(h*.20)))
    inc_text=pytesseract.image_to_string(incoming,lang='eng',config='--psm 6')
    rows=[]
    def add(kind,spec,role,box,raw,remark,tag='',quality='中'):
        x0,y0,x1,y1=box
        rows.append({'cabinet':cabinet,'page':page,'kind':kind,'spec':spec,'qty':1,'tag':tag,
              'source':'V1.6纵向支路/表格关联','raw':raw[:450],'status':'待核对',
              'record_role':role,'remark':remark,'location_quality':quality,
              'location_note':'图形表格列+局部OCR' if role=='feeder' else '识别文字锚点区域',
              'rel_boxes':[[round(x0,5),round(y0,5),round(x1,5),round(y1,5)]]})
    inc=_breakers_from_text(inc_text)
    if inc:
        typ,spec=inc
        add({'MCCB':'塑壳断路器','MCB':'微型断路器','RCBO':'漏电断路器'}[typ],spec,'incoming',(.30,.05,.76,.20),inc_text,'进线主开独立识别；未与支路重复计数')
    # The boxed VFD glyph is horizontal, even though its adjacent breaker
    # legends are rotated 90 degrees. Find those physical symbol boxes first.
    gray=np.asarray(ImageOps.grayscale(img))
    bw=cv2.threshold(gray,165,255,cv2.THRESH_BINARY_INV)[1]
    contours,_=cv2.findContours(bw,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    vfd_by_col={}
    for cc in contours:
        x,y,ww,hh=cv2.boundingRect(cc)
        if not (w*.035<ww<w*.12 and h*.021<hh<h*.085 and .30*h<y<.55*h and 1.2<ww/max(hh,1)<3.5):continue
        inner=img.crop((x+max(3,int(ww*.06)),y+max(2,int(hh*.08)),x+ww-max(3,int(ww*.06)),y+hh-max(2,int(hh*.08))))
        word=pytesseract.image_to_string(inner,lang='eng',config='--psm 7').strip().upper()
        if word!='VFD':continue
        for jj,(a,b) in enumerate(cols):
            if a<x+ww/2<b:vfd_by_col[jj]=(x,y,ww,hh);break
    # Check each physical outgoing column for a breaker. 270° converts
    # upward-written labels into left-to-right text without rotating the PDF.
    for idx,(a,b) in enumerate(cols):
        unit=img.crop((max(0,a+2),int(h*.17),min(w,b-2),int(h*.35)))
        turn=unit.rotate(270,expand=True)
        txt=pytesseract.image_to_string(turn,lang='eng',config='--psm 6')
        parsed=_breakers_from_text(txt)
        if not parsed:
            # A lower top crop sometimes cuts off the breaker descriptor;
            # retry just this branch, not the entire page.
            alt=img.crop((max(0,a+2),int(h*.182),min(w,b-2),int(h*.378))).rotate(270,expand=True)
            alt_txt=pytesseract.image_to_string(alt,lang='eng',config='--psm 6')
            parsed=_breakers_from_text(alt_txt)
            if parsed:txt=alt_txt
        if parsed:
            typ,spec=parsed
            add({'MCCB':'塑壳断路器','MCB':'微型断路器','RCBO':'漏电断路器'}[typ],
                spec,'feeder',(a/w,.182,b/w,.38),txt,'纵向支路中实际印刷的开关文字；不按列号推断设备')
        else:
            # A table column is evidence of a branch to review, not proof that
            # it contains a breaker (it can be an auxiliary or blank column).
            add('其他','支路器件待确认','unresolved_branch',(a/w,.17,b/w,.38),
                txt+'\n[复读]\n'+alt_txt,'已检测到参数表列，未确认器件；此项不计入实物数量',quality='未确认')
            rows[-1].update(qty=None,quantity_source='未确认器件',quantity_verified=False)
        # VFD candidate requires its *observed* framed VFD text glyph.
        if idx in vfd_by_col:
            gx,gy,gw,gh=vfd_by_col[idx];raw='VFD (framed glyph)'
            # Capacity is a separate, lower table cell, same physical column.
            cap=img.crop((a+3,int(h*.765),b-3,int(h*.827)))
            cap=ImageEnhance.Contrast(ImageOps.grayscale(cap.resize((max(1,cap.width*2),max(1,cap.height*2))))).enhance(2)
            capacity=pytesseract.image_to_string(cap,lang='eng',config='--psm 7').upper()
            m=re.search(r'\b(\d{1,4}(?:\.\d+)?)\s*K\s*W\b',capacity.replace(' ','').replace('O','0'))
            spec=f'VFD {m.group(1)}kW' if m else 'VFD（功率待确认）'
            add('变频器',spec,'vfd',(gx/w,gy/h,(gx+gw)/w,(gy+gh)/h),raw+' | 下方容量表:'+capacity,
                'VFD文字与同一列的容量表关联；功率、回路用途需人工确认')
    diag={'mode':'vertical','feeders':len(cols),'cabinet':cabinet,'reason':geo['reason'],
          'geometry':geo,'observed_breakers':sum(r['record_role'] in ('feeder','incoming') for r in rows),
          'observed_vfd':sum(r['record_role']=='vfd' for r in rows),
          'unresolved_branches':sum(r['record_role']=='unresolved_branch' for r in rows),
          'raw':'柜号:'+header_text+'\n进线:'+inc_text}
    return rows,diag
