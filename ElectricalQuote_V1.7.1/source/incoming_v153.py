"""Independent upstream/main-device recognition from actual OCR evidence.

Only matches labels physically LEFT of the feeder device column. This prevents
adding W1 as an extra 'main' when a diagram has no upstream main switch.
"""
import re
from PIL import ImageEnhance, ImageOps

RATING = re.compile(r'(MCCB|MCB|RCBO|DSL)[-_\s]*(?:TM[-_\s]*)?([BCD])?[-_\s]*(\d{1,4})\s*A\s*[/\\-]\s*([1-4])\s*P(\s*\+\s*N)?', re.I)

def recognize_incoming(img, page=1, cabinet='待确认柜号', source='进线独立识别'):
    import pytesseract
    w,h=img.size
    # The inlet branch in this drawing family is generally placed left of the feeder column.
    # Text labels on outgoing breakers start near 0.27-0.35 W.
    crop=img.crop((int(w*.015), int(h*.12), int(w*.47), int(h*.83)))
    data=pytesseract.image_to_data(ImageEnhance.Contrast(ImageOps.grayscale(crop)).enhance(1.4),
                  lang='eng',config='--psm 11',output_type=pytesseract.Output.DICT)
    candidates=[]
    for i,text in enumerate(data['text']):
        raw=text.upper().strip().replace('—','-').replace('–','-').replace('＝','-').replace(' ','')
        raw=raw.replace('WCCB','MCCB').replace('MCC8','MCCB').replace('MC8-','MCB-')
        left=(data['left'][i]+w*.015)/w
        if left>.265:continue
        # Low-confidence tokens can still be useful geometric anchors. Re-read
        # only this tiny text strip rather than trusting the first OCR number.
        if not re.match(r'^(MCCB|MCB|RCBO|DSL)[-_\s]?',raw):continue
        top=(data['top'][i]+h*.12)/h
        width=data['width'][i]/w;height=data['height'][i]/h
        x0=max(0,left-.018);x1=min(.29,max(left+width+.06,left+.20))
        y0=max(0,top-.025);y1=min(1,top+height+.015)
        local=img.crop((int(w*x0),int(h*y0),int(w*x1),int(h*y1)))
        t=pytesseract.image_to_string(local,lang='eng',config='--psm 7')
        candidate=t.upper().replace('—','-').replace('–','-').replace(' ','').replace('WCCB','MCCB').replace('MCC8','MCCB').replace('MC8-','MCB-')
        match=RATING.search(candidate)
        if not match:continue
        typ,curve,amps,pol,neutral=match.groups();amps=int(amps)
        if amps not in {1,2,3,4,6,10,16,20,25,32,40,50,60,63,80,100,125,160,200,250,315,320,400,500,630,800,1000,1250,1600}:continue
        kind={'MCCB':'塑壳断路器','MCB':'微型断路器','RCBO':'漏电断路器','DSL':'隔离开关'}[typ]
        model=(typ+'-TM' if typ=='MCCB' and re.search(r'MCCB-?TM',candidate) else typ)
        spec=f'{model}-{curve or ""}{amps}A/{pol}P'+('+N' if neutral else '')
        candidates.append((left,-float(data['conf'][i]),dict(
           cabinet=cabinet,page=page,kind=kind,spec=spec,qty=1,tag='',status='待核对',source=source,
           raw=t.strip(),remark='进线区域独立复查；保留图纸原型号，核对是否为主开',record_role='incoming',
           rel_boxes=[[round(x0,5),round(y0,5),round(x1,5),round(y1,5)]],
           location_quality='中',location_note='图纸进线文字局部二次OCR证据')))
    if not candidates:return None
    candidates.sort(key=lambda c:(c[0],c[1]))
    return candidates[0][2]


def merge_incoming(rows, incoming):
    if incoming is None:return rows
    # If an existing upstream DSL was already recognized, mark and locate it instead of double counting.
    for row in rows:
        if row.get('kind')==incoming['kind'] and (
            row.get('record_role')=='incoming' or
            (row.get('kind')=='隔离开关' and not row.get('tag'))):
            row.update(spec=incoming['spec'],rel_boxes=incoming['rel_boxes'],record_role='incoming',
                       location_quality=incoming['location_quality'],location_note=incoming['location_note'])
            row['remark']=row.get('remark','')+'；进线区独立OCR位置核验'
            return rows
    return rows+[incoming]
