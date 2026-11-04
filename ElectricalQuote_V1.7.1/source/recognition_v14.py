"""V1.4: geometry-backed source coordinates and targeted OCR evidence.
Raw electrical labels are never substituted with a purchased part number.
"""
import re
from PIL import Image, ImageOps, ImageEnhance, ImageFilter


def _ocr_crop(img, box, psm=7, binary=False):
    import pytesseract
    w,h=img.size
    x0,y0,x1,y1=box
    crop=img.crop((max(0,int(x0)),max(0,int(y0)),min(w,int(x1)),min(h,int(y1))))
    if crop.width<5 or crop.height<4: return ''
    crop=ImageOps.grayscale(crop)
    if binary:
        crop=ImageEnhance.Contrast(crop).enhance(2.2).point(lambda v: 255 if v>175 else 0)
    crop=crop.resize((crop.width*3,crop.height*3))
    return pytesseract.image_to_string(crop,lang='eng',config=f'--psm {psm}').strip()


def _recognize_missing_feeder(img, y, step):
    """Read the band ABOVE the horizontal conductor with a cut that excludes cables.
    Only accept a well-formed observed electrical label. No copying neighboring feeders.
    """
    w,h=img.size
    box=(w*.205,y-step*.95,w*.485,y-step*.03)
    candidates=[]
    for psm in (7,6,11):
        for binary in (False,True):
            raw=_ocr_crop(img,box,psm,binary)
            normalized=raw.upper().replace('—','-').replace('–','-').replace(' ','')
            # normalize only literal OCR misreads inside a technical keyword
            normalized=normalized.replace('MC8-','MCB-').replace('WCB-','MCB-').replace('P-+N','P+N').replace('P--N','P+N')
            m=re.search(r'\b(MCCB|MCB|RCBO|RCBQ)[-_:=]*(?:TM[-_]*)?([BCD])?([0-9IO]{1,3})A?[/\\]([1-4])P(\+N)?',normalized)
            if m:
                kind={'MCB':'MCB 微型断路器','MCCB':'MCCB 塑壳断路器','RCBO':'RCBO 漏电断路器','RCBQ':'RCBO 漏电断路器'}[m.group(1)]
                amp=int(m.group(3).translate(str.maketrans('IO','10')))
                if amp not in (1,2,3,4,6,10,13,16,20,25,32,40,50,60,63,80,100,125,160,200,225,250,315,320,400,500,630,800):continue
                spec=(m.group(2) or '')+str(amp)+'A/'+m.group(4)+'P'+(m.group(5) or '')
                candidates.append((kind,spec,raw))
    if not candidates:return None
    # Prefer recurrent exact label, otherwise preserve a single reading as unconfirmed.
    counts={}
    for kind,spec,_ in candidates:counts[(kind,spec)]=counts.get((kind,spec),0)+1
    winner=max(counts,key=counts.get)
    return winner[0],winner[1],counts[winner], ' | '.join(dict.fromkeys(x[2] for x in candidates))[:480]


def _set_locations(rec, boxes, kind, confidence, note, W, H):
    valid=[]
    for x0,y0,x1,y1 in boxes:
        b=[max(0,round(x0/W,5)),max(0,round(y0/H,5)),min(1,round(x1/W,5)),min(1,round(y1/H,5))]
        if b[2]>b[0] and b[3]>b[1]:valid.append(b)
    if valid:
        rec['rel_boxes']=valid
        rec['evidence_type']=kind
        rec['location_quality']=confidence
        rec['location_note']=note


def _text_box(img, keywords, zone, reference=None):
    """OCR position hint only, never used to invent devices."""
    import pytesseract
    w,h=img.size
    crop=img.crop(tuple(map(int,zone)))
    scale=2
    large=ImageEnhance.Contrast(ImageOps.grayscale(crop)).enhance(1.4)
    large=large.resize((crop.width*scale,crop.height*scale))
    data=pytesseract.image_to_data(large,config='--psm 11',lang='eng',output_type=pytesseract.Output.DICT)
    hits=[]
    for j,word in enumerate(data['text']):
        normalized=word.upper().replace(' ','').replace('O','0')
        if not any(re.search(k,normalized) for k in keywords):continue
        x=zone[0]+data['left'][j]/scale;y=zone[1]+data['top'][j]/scale
        bw=data['width'][j]/scale;bh=data['height'][j]/scale
        if reference:
            if abs(x-reference[0])>w*.2 or abs(y-reference[1])>h*.14:continue
        hits.append((x,y,x+bw,y+bh))
    if not hits:return None
    if reference:hits.sort(key=lambda b:abs(b[0]-reference[0])+abs(b[1]-reference[1]))
    return hits[0]


def upgrade_recognition(img, rows, diag):
    """Enhance the existing tested 14-feeder recognizer; add source coordinates
    for upstream equipment, CT instruments, and surge branch.
    """
    w,h=img.size
    feeds=[r for r in rows if r.get('record_role')=='feeder' or re.fullmatch(r'W\d+',r.get('tag',''))]
    if not feeds:return rows,diag
    ys=[int(float(r['pdf_rel_y'])*h) for r in feeds if 'pdf_rel_y' in r]
    default_step=sorted([b-a for a,b in zip(ys,ys[1:])])[len(ys)//2-1] if len(ys)>2 else h*.045
    repairs=[]
    for r in feeds:
        step=float(r['pdf_rel_pitch'])*h if r.get('pdf_rel_pitch') else default_step
        y=int(float(r['pdf_rel_y'])*h)
        x0,x1=w*.26,w*.465
        _set_locations(r,[(x0,y-step*.86,x1,y-step*.02)],'回路文字+横向导线','高','基于独立回路横线检测，并已定位器件文字列',w,h)
        if r['kind']=='其他' or '待确认' in r.get('spec',''):
            found=_recognize_missing_feeder(img,y,step)
            if found:
                kind,spec,votes,raw=found
                if r['kind']=='其他' or '断路器类型待确认' in r.get('spec',''):
                    r.update(kind=kind,spec=spec,qty=1,quantity_source='图纸局部文字候选',raw=raw,status='待核对',remark=f'V1.4独立局部二次OCR命中{votes}次；请人工核对')
                    repairs.append((r.get('tag'),spec))
                else:
                    # do not overwrite a complete, different original reading
                    r['remark']=r.get('remark','')+'；局部OCR备选:'+spec
    # In this CAD-style drawing, the main breaker+measurement branch are upstream
    # of the feeder bus; their regions are evaluated independent of cable CT tokens.
    for r in rows:
        if r.get('rel_boxes'):continue
        kind=r.get('kind','')
        if kind=='隔离开关':
            reference=(w*.16,h*.415)
            t=_text_box(img,[r'DSL',r'IS0LAT0R'],(w*.05,h*.30,w*.31,h*.55),reference)
            # Box includes text and disconnector symbol, not the whole incoming bus.
            if t:boxes=[(t[0]-w*.018,t[1]-h*.015,t[2]+w*.06,t[3]+h*.032)];quality='中';note='OCR文字锚点+进线符号附近'
            else:boxes=[(w*.11,h*.39,w*.22,h*.47)];quality='估计';note='由一次图进线区域结构推定位置；需核对'
            _set_locations(r,boxes,'进线结构+局部OCR',quality,note,w,h)
        elif kind=='多功能仪表':
            t=_text_box(img,[r'^PM$'],(w*.11,h*.24,w*.35,h*.49),(w*.22,h*.34))
            if t:boxes=[(t[0]-w*.012,t[1]-h*.018,t[2]+w*.012,t[3]+h*.018)];quality='中';note='PM文字锚点'
            else:boxes=[(w*.182,h*.325,w*.25,h*.375)];quality='估计';note='按测量支路布局估计，人工核对'
            _set_locations(r,boxes,'仪表文字',quality,note,w,h)
        elif kind=='电流互感器':
            # Three phase current transformers are a grouped quantity; mapping is
            # a measurement branch region, not three individually proven circles.
            t=_text_box(img,[r'\d+/5A',r'250/5'],(w*.12,h*.33,w*.34,h*.53),(w*.22,h*.43))
            if t: boxes=[(t[0]-w*.028,t[1]-h*.062,t[2]+w*.028,t[3]+h*.025)];quality='中';note='250/5A变比文字+上方测量符号组；三只仍需图纸复核'
            else:boxes=[(w*.195,h*.36,w*.275,h*.465)];quality='估计';note='测量支路区域估计，数量3只为三相常规推定'
            _set_locations(r,boxes,'互感器变比+符号组',quality,note,w,h)
        elif kind in ('浪涌保护器','浪涌后备保护器'):
            if kind=='浪涌后备保护器':
                t=_text_box(img,[r'SCB',r'HKPD'],(w*.245,h*.77,w*.65,h*.94),(w*.38,h*.84))
                boxes=[(t[0]-w*.012,t[1]-h*.01,t[2]+w*.055,t[3]+h*.025)] if t else [(w*.315,h*.835,w*.46,h*.875)]
                note='SCB字符定位，可能与SPD共用标注区域' if t else '底部浪涌支路推定位置'
            else:
                t=_text_box(img,[r'8/20',r'1MAX',r'420V',r'SPD'],(w*.24,h*.80,w*.66,h*.97),(w*.45,h*.87))
                boxes=[(t[0]-w*.02,t[1]-h*.022,t[2]+w*.09,t[3]+h*.04)] if t else [(w*.345,h*.865,w*.57,h*.94)]
                note='浪涌技术参数附近定位，不代表精确识别全部符号' if t else '底部浪涌分支推定位置'
            _set_locations(r,boxes,'浪涌支路+OCR', '中' if t else '估计',note,w,h)
    diag['repairs']=repairs
    diag['locatable']=sum(bool(r.get('rel_boxes')) for r in rows)
    diag['weak_locations']=sum(r.get('location_quality')=='估计' for r in rows)
    return rows,diag
