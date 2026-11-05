"""Conservative first-pass VFD evidence capture for electrical single-line drawings.

This is NOT an electrical motor wiring interpreter. It only adds a candidate
where VFD (or the common VED OCR confusion) occurs in a plausible VFD cabinet
symbol region. Direct-start/contactors/overloads are NEVER inferred.
"""
import re


def recognize_vfd_candidates(img, page, cabinet, source='变频图纸专项候选'):
    import pytesseract
    from ocr_runtime import initialize_ocr
    initialize_ocr()
    w,h=img.size
    if 'VFD' not in cabinet.upper():
        return []
    # VFD glyphs in this drawing family are in the middle branch symbol column.
    left=.45; right=.53; top=.23; bottom=.70
    crop=img.crop((int(w*left),int(h*top),int(w*right),int(h*bottom)))
    data=pytesseract.image_to_data(crop,lang='eng',config='--psm 6',output_type=pytesseract.Output.DICT)
    terms=[];powers=[]
    for i,txt in enumerate(data['text']):
        clean=txt.upper().strip().replace(' ','')
        if not clean:continue
        x=(int(w*left)+data['left'][i])/w;y=(int(h*top)+data['top'][i])/h
        wid=data['width'][i]/w;hei=data['height'][i]/h
        if re.fullmatch(r'VFD|VED|VF[D0]',clean):terms.append((x,y,wid,hei,clean))
        m=re.fullmatch(r'(\d+(?:[.,]\d+)?)KW',clean)
        if m:powers.append((y,m.group(1).replace(',','.')))
    # Different VFD symbols must be spatially separated. Do not count twice.
    seen=[];result=[]
    for x,y,ww,hh,raw in terms:
        if any(abs(y-old)<.035 for old in seen):continue
        seen.append(y)
        prior=[(y-py,val) for py,val in powers if -.01<=y-py<.10]
        best=min(prior,key=lambda z:z[0])[1] if prior else None
        spec=f'{best}kW（OCR候选）' if best else 'VFD功率待确认'
        result.append(dict(cabinet=cabinet,page=page,kind='变频器',spec=spec,qty=1,tag='',
            source=source,status='待核对',raw=raw,
            remark='从变频器图形文字定位；仅统计图上可见设备，控制/散热配件不自动推断',
            record_role='vfd_candidate',
            rel_boxes=[[round(max(0,x-.012),5),round(max(0,y-.02),5),round(min(1,x+ww+.012),5),round(min(1,y+hh+.022),5)]],
            location_quality='中' if raw=='VFD' else '低',location_note='VFD或VED文字锚点（待核）'))
    return result
