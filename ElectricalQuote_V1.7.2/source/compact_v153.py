"""Small, often two-row, single-line diagram OCR without minimum-four-feeder assumption.

Does not infer any device from a load label alone. Uses observed RCBO/MCB/MCCB
labels, records source position, and keeps OCR uncertainty explicit.
"""
import re
from PIL import ImageEnhance, ImageOps

R=re.compile(r'\b(MCCB|MCB|RCBO)\s*[-_:=]*\s*(?:TM\s*[-_]*)?\s*([BCD])?\s*(\d{1,4})\s*A\s*[-/\\]\s*([1-4])\s*P(\s*\+\s*N)?',re.I)

def recognize_compact(img,page,source,cabinet='待确认柜号'):
    import pytesseract
    from ocr_runtime import initialize_ocr
    initialize_ocr()
    w,h=img.size
    if w/h<1.1:return [],{'mode':'fallback','feeders':0,'reason':'非横向简图，等待专业回路识别'}
    # Single OCR on the feeder device-label column, where cable models are excluded.
    x0=int(w*.265);x1=int(w*.55);y0=int(h*.10);y1=int(h*.88)
    crop=img.crop((x0,y0,x1,y1))
    # Raw rendered images often outperform binarization for narrow CAD strokes.
    data=pytesseract.image_to_data(crop,lang='eng',config='--psm 6',output_type=pytesseract.Output.DICT)
    result=[]
    for i,text in enumerate(data['text']):
        normalized=text.upper().replace('—','-').replace('–','-').replace(' ','').replace('ROBO','RCBO').replace('R0BO','RCBO')
        m=R.search(normalized)
        if not m:continue
        typ,curve,amp,pole,neutral=m.groups();amp=int(amp)
        if amp not in {6,10,16,20,25,32,40,50,63,80,100,125,160,200,250,400,630}:continue
        kind={'MCB':'微型断路器','MCCB':'塑壳断路器','RCBO':'漏电断路器'}[typ]
        model=typ+'-TM' if typ=='MCCB' and re.search(r'MCCB\s*[-_:=]*\s*TM',normalized) else typ
        spec=f'{model}-{curve or ""}{amp}A/{pole}P'+('+N' if neutral else '')
        xx=(x0+data['left'][i])/w;yy=(y0+data['top'][i])/h
        xx2=(x0+data['left'][i]+data['width'][i])/w;yy2=(y0+data['top'][i]+data['height'][i])/h
        result.append(dict(cabinet=cabinet,page=page,kind=kind,spec=spec,qty=1,tag='',
            record_role='feeder',source=source,raw=text,status='待核对',
            remark='短回路图中的独立元器件文字；位号及数量需核对',
            location_quality='中',location_note='短回路图独立设备标签',
            rel_boxes=[[round(max(0,xx-.012),5),round(max(0,yy-.023),5),
                        round(min(1,xx2+.012),5),round(min(1,yy2+.022),5)]]))
    # Two text lines = two physical outgoing devices here; more requires manual review.
    return result,dict(mode='compact',feeders=len(result),reason='短回路OCR：需核对设备实际位置及数量')
