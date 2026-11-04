"""V1.7 surge branch extraction from observed SCB/SPD labels.

This module deliberately does NOT manufacture an SPD when only an SCB has
been observed (or vice versa). An unmatched pair becomes a review warning.
Iimp and Imax are distinct, and a model token's 80 is not assumed to be Imax.
"""
from __future__ import annotations
import re
from PIL import Image, ImageOps, ImageEnhance

SCB_MODEL = re.compile(r"\b((?:[A-Z0-9]{2,}[-_]\s*|[A-Z0-9]{2,})?SCB\s*\d*\s*/\s*\d+\s*/\s*[1-4]P)\b", re.I)
SPD_MODEL = re.compile(r"\b((?:[A-Z0-9]{2,}[-_]\s*)?B\s*\d+\s*/\s*\d+\s*/\s*[1-4]P)\b", re.I)
SPD_KIND = '浪涌保护器'
SCB_KIND = '浪涌后备保护器'

# Text in CAD PDFs is often rendered as outlines. Extract parameters independently
# from the technical legend rather than inferring them from the model suffix.
def parse_surge_text(raw):
    t=raw.upper().replace('—','-').replace('–','-').replace('Μ','U').replace('μ','U')
    t=t.replace('Ｉ','I').replace('Ｍ','M')
    t=re.sub(r'\s+', ' ',t)
    scb=SCB_MODEL.search(t)
    spd=SPD_MODEL.search(t)
    def num(k,unit):
        m=re.search(r'\b'+re.escape(k)+r'\s*[:=]\s*(\d+(?:\.\d+)?)\s*'+unit+r'\b',t,re.I)
        return float(m.group(1)) if m else None
    params={
      'in_ka':num('IN',r'K\s*A'),
      'imax_ka':num('IMAX',r'K\s*A'),
      'iimp_ka':num('IIMP',r'K\s*A'),
      'uc_v':num('UC',r'V'),
      'up_kv':num('UP',r'K\s*V'),
    }
    typ=re.search(r'(?<!\w)T\s*([12])(?:\s*\+\s*T?([12]))?(?!\w)',t)
    params['spd_type']=('T'+typ.group(1)+('+'+'T'+typ.group(2) if typ.group(2) else '')) if typ else ''
    params['spd_model']=re.sub(r'\s+','',spd.group(1)) if spd else ''
    params['scb_model']=re.sub(r'\s+','',scb.group(1)) if scb else ''
    if params['spd_model']:
        m=re.search(r'/([1-4])P$',params['spd_model'])
        params['spd_pole']=m.group(1)+'P' if m else ''
    else:params['spd_pole']=''
    if params['scb_model']:
        m=re.search(r'/([1-4])P$',params['scb_model'])
        params['scb_pole']=m.group(1)+'P' if m else ''
    else:params['scb_pole']=''
    # A technical In/Imax/Uc line alone is evidence of an SPD parameter block;
    # require multiple independent parameters before creating an SPD candidate.
    params['has_spd']=bool(spd or re.search(r'\bSPD\b',t) or
        (params['uc_v'] is not None and any(params[k] is not None for k in ('imax_ka','iimp_ka'))))
    params['has_scb']=bool(scb or re.search(r'\bSCB\b',t))
    return params


def _quantity(row):
    """Missing/uncertain counts remain unknown, never silently become one."""
    value=row.get('qty',1)
    try:
        number=float(value)
        if not number.is_integer() or number < 0:return None
        return int(number)
    except (TypeError, ValueError, OverflowError):return None


def surge_pair_warnings(rows):
    """Check counts without claiming an uncertain set is a matched pair."""
    spd=[r for r in rows if r.get('kind')==SPD_KIND]
    scb=[r for r in rows if r.get('kind')==SCB_KIND]
    warnings=[]
    if any(r.get('quantity_ambiguous') or _quantity(r) is None for r in spd+scb):
        warnings.append('防雷器件数量或实体对应关系尚未核实；保留原记录，不能按数量相等判定配对成功。')
    if spd and not scb:warnings.append('发现SPD，但没有识别到对应SCB；请复查防雷支路，不自动补料。')
    if scb and not spd:warnings.append('发现SCB，但没有识别到对应SPD；请复查防雷支路，不自动补料。')
    if spd and scb and all(_quantity(r) is not None for r in spd+scb):
        if sum(_quantity(r) for r in spd)!=sum(_quantity(r) for r in scb):
            warnings.append('SPD与SCB数量不相等；请核对是否为成套/共用配置。')
    return warnings


def _detect_t_glyph(image, bbox):
    """Read a printed boxed T1/T2 symbol, not a model-derived guess.
    Return (type, source_bbox) in panel image pixels or ('',None).
    """
    import numpy as np, cv2, pytesseract
    x0,y0,x1,y1=map(int,bbox)
    crop=image.crop((x0,y0,x1,y1)).convert('L')
    a=np.asarray(crop)
    binary=cv2.threshold(a,170,255,cv2.THRESH_BINARY_INV)[1]
    contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for cnt in contours:
        x,y,w,h=cv2.boundingRect(cnt)
        if not (17<=w<=115 and 15<=h<=70 and .8<w/max(1,h)<3.5):continue
        approx=cv2.approxPolyDP(cnt,.05*cv2.arcLength(cnt,True),True)
        if not 4<=len(approx)<=7:continue
        if x<5 or y<2 or x+w>=crop.width-5 or y+h>=crop.height-2:continue
        region=crop.crop((max(0,x+2),max(0,y+2),x+w-2,y+h-2))
        for scale in (3,5):
            large=region.resize((region.width*scale,region.height*scale))
            txt=pytesseract.image_to_string(large,lang='eng',config='--psm 10 -c tessedit_char_whitelist=T12').strip().upper()
            if txt in ('T1','T2'):
                candidates.append((txt,(x0+x,y0+y,x0+x+w,y0+y+h)))
                break
    if not candidates:return '',None
    candidates.sort(key=lambda t: (t[1][2]-t[1][0])*(t[1][3]-t[1][1]),reverse=True)
    first=candidates[0]
    c0=((first[1][0]+first[1][2])/2,(first[1][1]+first[1][3])/2)
    # Nested inner/outer contours of the SAME printed T-box are expected.
    if all(t[0]==first[0] and abs((t[1][0]+t[1][2])/2-c0[0])<12 and abs((t[1][1]+t[1][3])/2-c0[1])<12 for t in candidates):return first
    return '',None


def _box_iou(a, b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=max(0,(a[2]-a[0])*(a[3]-a[1]))+max(0,(b[2]-b[0])*(b[3]-b[1]))-inter
    return inter/union if union else 0


def _extract_anchors(data, origin=(0,0)):
    """Return observed label entities with image pixel boxes (not guessed symbols).

    Joining words only within an OCR line supports fragmented model labels;
    every separate full-model occurrence retains its own coordinates.
    """
    lines={}
    for i,raw in enumerate(data.get('text',[])):
        raw=str(raw).strip()
        if not raw:continue
        try:
            x=float(data['left'][i])+origin[0];y=float(data['top'][i])+origin[1]
            w=float(data['width'][i]);h=float(data['height'][i])
        except (KeyError,IndexError,TypeError,ValueError):continue
        if w<=0 or h<=0:continue
        key=tuple(data.get(k,[0]*len(data['text']))[i] for k in ('block_num','par_num','line_num'))
        lines.setdefault(key,[]).append((raw,[x,y,x+w,y+h]))
    anchors=[]
    for words in lines.values():
        words.sort(key=lambda item:item[1][0])
        text='';spans=[]
        for word,box in words:
            if text:text+=' '
            start=len(text);text+=word.upper().replace('—','-').replace('–','-')
            spans.append((start,len(text),box))
        for kind,model,generic in ((SCB_KIND,SCB_MODEL,r'\bSCB\d*\b'),(SPD_KIND,SPD_MODEL,r'\bSPD\b')):
            matches=list(model.finditer(text))
            matches.extend(m for m in re.finditer(generic,text,re.I)
                if not any(m.start()<full.end() and m.end()>full.start() for full in matches))
            matches.sort(key=lambda m:m.start())
            for m in matches:
                boxes=[b for start,end,b in spans if start<m.end() and end>m.start()]
                if not boxes:continue
                box=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
                anchors.append({'kind':kind,'box':box,'raw':m.group(0)})
    return anchors


def _merge_anchors(anchors):
    """IoU fuses repeated OCR of one label, never identical text elsewhere."""
    result=[]
    for anchor in anchors:
        previous=next((a for a in result if a['kind']==anchor['kind'] and _box_iou(a['box'],anchor['box'])>=.3),None)
        if previous is None:result.append(dict(anchor))
        elif len(anchor['raw'])>len(previous['raw']):
            previous.update(raw=anchor['raw'],box=anchor['box'])
    return result


def _entity_crop_box(anchor, anchors, image_size, search_box):
    """Bound OCR by nearby same-kind labels so one SPD cannot borrow another's parameters."""
    w,h=image_size;b=anchor['box'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
    left,top,right,bottom=search_box
    top=max(top,b[1]-.025*h);bottom=min(bottom,b[3]+.16*h)
    left=max(left,b[0]-.06*w);right=min(right,b[2]+.22*w)
    for other in anchors:
        if other is anchor or other['kind']!=anchor['kind']:continue
        q=other['box'];ox=(q[0]+q[2])/2;oy=(q[1]+q[3])/2
        if abs(ox-cx)/max(w,1)>abs(oy-cy)/max(h,1):
            mid=(cx+ox)/2
            if ox>cx:right=min(right,mid)
            else:left=max(left,mid)
        else:
            mid=(cy+oy)/2
            if oy>cy:bottom=min(bottom,mid)
            else:top=max(top,mid)
    # Include the observed model itself even when neighboring OCR is crowded.
    return tuple(map(int,(min(left,b[0]),min(top,b[1]),max(right,b[2]),max(bottom,b[3]))))


def _merge_evidence(first, second):
    """Merge missing attributes only after spatial identity was established."""
    result=dict(first)
    for key,value in second.items():
        if result.get(key) in ('',None,False) and value not in ('',None,False):result[key]=value
    return result


def _make_row(kind, evidence, raw, page, cabinet, loc=None, qty=1):
    if kind==SCB_KIND:
        spec=evidence.get('scb_model') or 'SCB（型号待确认）'
        metadata={'model':spec,'pole':evidence.get('scb_pole','')}
    else:
        metadata=dict(evidence);parts=[]
        if evidence.get('spd_model'):parts.append(evidence['spd_model'])
        parts.append(evidence.get('spd_type') or 'T类型待确认')
        parts.append('Imax%gkA'%evidence['imax_ka'] if evidence.get('imax_ka') is not None else 'Imax待确认')
        if evidence.get('spd_pole'):parts.append(evidence['spd_pole'])
        elif not evidence.get('spd_model'):parts.append('极数待确认')
        for field,label,unit in (('in_ka','In','kA'),('iimp_ka','Iimp','kA'),('uc_v','Uc','V'),('up_kv','Up','kV')):
            if evidence.get(field) is not None:parts.append(label+('%g'%evidence[field])+unit)
        spec=' / '.join(parts)
    row=dict(cabinet=cabinet,page=page,kind=kind,spec=spec,qty=qty,tag='',
        source='V1.7.1防雷实体OCR',raw=raw[:1200],status='待核对',record_role='surge',
        remark='仅保留同一空间实体的原图参数；型号、数量和配对仍需人工核对',surge_params=metadata)
    if loc:row.update(rel_boxes=[loc],evidence_type='printed_label',location_quality='文字实测',
        location_note='独立器件标签的OCR实测坐标；多轮OCR按位置去重')
    if qty is None:row['quantity_ambiguous']=True
    return row


def _merge_existing(existing, observed, kind):
    """Never reduce a previously recorded count on incomplete OCR evidence."""
    old=[r for r in existing if r.get('kind')==kind]
    if not old:return observed
    if not observed:return old
    previous=[_quantity(r) for r in old]
    current=[_quantity(r) for r in observed]
    ambiguous=(any(n is None for n in previous+current) or
               sum(n or 0 for n in previous)>sum(n or 0 for n in current))
    # The legacy recognizer creates one unconfirmed placeholder per kind.
    # A complete set of spatially observed labels can replace that placeholder.
    if not ambiguous and len(old)==1 and previous==[1] and old[0].get('status','待核对')!='已确认':
        replacements=[dict(r) for r in observed]
        if len(replacements)==1:
            for k in ('tag','status'):
                if old[0].get(k):replacements[0][k]=old[0][k]
        return replacements
    # Older rows already use original-PDF coordinates in the worker; comparing
    # them to corrected-image anchors (or copying them as new rows) is unsafe.
    # Preserve those objects and their counts until a reviewer resolves identity.
    for row in old:
        row['quantity_ambiguous']=True
        message='本次OCR不足以核实原有防雷实体对应关系，保留原数量待复核'
        if message not in row.get('remark',''):row['remark']=row.get('remark','')+'；'+message
    return old


def recognize_surge(image, rows, page, cabinet):
    """Read each lower-branch SCB/SPD entity separately; preserve unresolved counts."""
    import pytesseract
    w,h=image.size
    feeders=[r for r in rows if r.get('record_role')=='feeder']
    ys=sorted(float(r.get('_anchor_corrected_y',r.get('pdf_rel_y',0))) for r in feeders)
    start=max(.62,min(.83,ys[-1]+.012) if ys else .78)
    box=(int(w*.22),int(h*start),int(w*.84),h)
    if box[3]-box[1]<25:return rows,surge_pair_warnings(rows)
    sample=image.crop(box)
    texts=[];anchors=[]
    for psm in (6,11):
        texts.append(pytesseract.image_to_string(sample,lang='eng',config=f'--psm {psm}'))
        data=pytesseract.image_to_data(sample,lang='eng',config=f'--psm {psm}',output_type=pytesseract.Output.DICT)
        anchors.extend(_extract_anchors(data,box[:2]))
    anchors=_merge_anchors(anchors)
    observed=[]
    for anchor in anchors:
        local_box=_entity_crop_box(anchor,anchors,image.size,box)
        crop=image.crop(local_box)
        evidence=parse_surge_text(anchor['raw']);raws=[anchor['raw']];conflict=False
        for psm in (6,11):
            raw=pytesseract.image_to_string(crop,lang='eng',config=f'--psm {psm}')
            candidate=parse_surge_text(raw)
            # One local crop is allowed to supply only this anchor's parameters.
            # If multiple same-kind labels survived the boundary, keep label-only evidence.
            pattern=SCB_MODEL if anchor['kind']==SCB_KIND else SPD_MODEL
            model_field='scb_model' if anchor['kind']==SCB_KIND else 'spd_model'
            anchor_model=parse_surge_text(anchor['raw']).get(model_field)
            candidate_model=candidate.get(model_field)
            compatible=not (anchor_model and candidate_model and anchor_model!=candidate_model)
            if compatible and len(list(pattern.finditer(raw)))<=1:
                evidence=_merge_evidence(evidence,candidate);raws.append(raw)
            else:
                conflict=True;raws.append('[未采用：其他型号/多个实体] '+raw)
        if anchor['kind']==SPD_KIND and not evidence.get('spd_type'):
            typ,_=_detect_t_glyph(image,local_box)
            if typ:evidence['spd_type']=typ
        loc=[round(anchor['box'][0]/w,6),round(anchor['box'][1]/h,6),round(anchor['box'][2]/w,6),round(anchor['box'][3]/h,6)]
        detected=_make_row(anchor['kind'],evidence,'\n'.join(dict.fromkeys(raws)),page,cabinet,loc)
        if conflict:detected['remark']+='；局部OCR含其他型号或多个实体，冲突参数未采用'
        observed.append(detected)
    for kind,flag,pattern in ((SCB_KIND,'has_scb',SCB_MODEL),(SPD_KIND,'has_spd',SPD_MODEL)):
        positioned=[r for r in observed if r['kind']==kind]
        if positioned:
            generic=r'\bSCB\d*\b' if kind==SCB_KIND else r'\bSPD\b'
            text_count=max(max(len(list(pattern.finditer(text))),len(re.findall(generic,text,re.I))) for text in texts)
            if text_count>len(positioned):
                for row in positioned:
                    row['quantity_ambiguous']=True
                    row['remark']+='；整段文字含更多防雷标注，但无法逐个定位，数量待复核'
            continue
        # Text-only compatibility for a single unlocated parameter paragraph.
        # Do not combine fields across different OCR paragraphs or different entities.
        choices=[(parse_surge_text(text),text) for text in texts]
        choices=[(e,text) for e,text in choices if e[flag]]
        if not choices:continue
        evidence,raw=max(choices,key=lambda v:sum(value not in ('',None,False) for value in v[0].values()))
        count=max(len(list(pattern.finditer(text))) for text in texts)
        generic=r'\bSCB\d*\b' if kind==SCB_KIND else r'\bSPD\b'
        count=max(count,max(len(re.findall(generic,text,re.I)) for text in texts))
        qty=None if count>1 else 1
        if qty is None:
            # Whole-zone text cannot attribute any first model/parameter to an
            # individual entity. Keep only the observed category and raw text.
            evidence=parse_surge_text('SCB' if kind==SCB_KIND else 'SPD')
        if kind==SPD_KIND and not evidence.get('spd_type') and qty==1:
            typ,_=_detect_t_glyph(image,box)
            if typ:evidence['spd_type']=typ
        observed.append(_make_row(kind,evidence,raw,page,cabinet,qty=qty))
    result=[r for r in rows if r.get('kind') not in (SPD_KIND,SCB_KIND)]
    for kind in (SCB_KIND,SPD_KIND):
        result.extend(_merge_existing(rows,[r for r in observed if r['kind']==kind],kind))
    return result,surge_pair_warnings(result)
