"""V1.6.1: attach observed OCR word boxes; never invent physical device coordinates.

A Tesseract word rectangle is a **printed annotation** location, not a breaker
symbol.  Only manual marking or verified graphical glyphs are device locations.
"""
import re
from PIL import ImageOps


def _norm(s):
    s=re.sub(r'[^A-Z0-9+/]', '', str(s).upper())
    # Correct OCR in RATING only; RCBO itself must never become RCB0.
    s=re.sub(r'(?<=[BCD])I(?=[0-9O])','1',s)
    s=re.sub(r'(?<=[BCD1-9])O(?=[0-9A])','0',s)
    return s


def _type(kind):
    k=str(kind).upper()
    if 'MCCB' in k or '塑壳' in k: return 'MCCB'
    if 'RCBO' in k or '漏电' in k: return 'RCBO'
    if 'MCB' in k or '微型' in k: return 'MCB'
    if '隔离' in k: return 'DSL'
    if '互感' in k: return 'CT_RATIO'
    if '仪表' in k: return 'PM'
    if '浪涌后备' in k: return 'SCB'
    if '浪涌' in k: return 'SPD'
    return None


def locate_observed_printed_labels(img, rows, turns, unrotate_box):
    """One sparse OCR layout pass on the ORIGINAL panel raster, coordinates
    transformed back to PDF panel coordinates. Fails closed on missing evidence.
    Old region-guess boxes are intentionally dropped.
    """
    import pytesseract
    from ocr_runtime import initialize_ocr
    initialize_ocr()
    search_zones={}
    # Only original glyph-detection / native PDF frames survive the policy change.
    for row in rows:
        if row.get('record_role')=='surge' and row.get('evidence_type')=='printed_label' and row.get('rel_boxes'):
            continue
        if row.get('location_quality') in ('人工标定','符号实测','高') and row.get('evidence_type')=='verified_symbol':
            continue
        # Upstream layout regions constrain the search, but never become the
        # returned evidence box. The worker has already unrotated these hints.
        if row.get('rel_boxes'):
            search_zones[id(row)]=[unrotate_box(box,-turns) for box in row['rel_boxes']]
        row.pop('rel_boxes',None)
        row.pop('pdf_boxes',None)
        row.pop('location_quality',None)
        row['location_note']='尚未找到可验证的元器件位置'
    width,height=img.size
    words=[]
    # PSM6 reads orderly rows, PSM11 helps scattered legends. Both produce
    # measured pixel rectangles; neither creates a guessed bounding box.
    for psm in (6,11):
        try:
            d=pytesseract.image_to_data(ImageOps.grayscale(img),lang='eng',config=f'--psm {psm}',output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        for j,s in enumerate(d['text']):
            s=str(s).strip();n=_norm(s)
            if not n or d['width'][j]<3 or d['height'][j]<3:continue
            if float(d['conf'][j])<20:continue
            box=(d['left'][j],d['top'][j],d['left'][j]+d['width'][j],d['top'][j]+d['height'][j])
            # PSM6 and PSM11 see the same physical words. Merge their spatial
            # evidence before assignment so one printed label cannot prove two
            # separate devices merely because it was OCRed twice.
            duplicate=None
            for candidate in words:
                a=candidate['box'];b=box
                overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                aa=(a[2]-a[0])*(a[3]-a[1]);bb=(b[2]-b[0])*(b[3]-b[1])
                iou=overlap/max(1,aa+bb-overlap)
                related=any(n in old or old in n for old in candidate['texts'])
                if iou>=.55 or (related and overlap/max(1,min(aa,bb))>=.8):
                    duplicate=candidate;break
            if duplicate is None:
                words.append({'texts':{n},'box':box,'confidence':float(d['conf'][j])})
            else:
                duplicate['texts'].add(n)
                if float(d['conf'][j])>duplicate['confidence']:
                    duplicate['box']=box;duplicate['confidence']=float(d['conf'][j])
    used=set()
    anchors=sorted({float(row['_anchor_corrected_y']) for row in rows if row.get('_anchor_corrected_y') is not None})
    # Constrained feeder rows get their evidence first; an unconstrained
    # incoming candidate must not take a feeder's label before that assignment.
    ordered=sorted(rows,key=lambda row:row.get('_anchor_corrected_y') is None)
    for row in ordered:
        if row.get('record_role')=='surge':continue
        if row.get('evidence_type')=='verified_symbol':continue
        cat=_type(row.get('kind',''))
        if cat is None or cat=='SPD':continue
        # VFD vector/icon candidates already have actual glyph evidence upstream.
        if cat=='VFD':continue
        spec=_norm(row.get('spec',''))
        cur=re.search(r'([BCD]?\d{1,4})A',spec)
        current=cur.group(1) if cur else ''
        matches=[]
        hint=row.get('_anchor_corrected_y')
        low=high=target=None
        if hint is not None:
            hint=float(hint);position=anchors.index(hint)
            local_pitch=row.get('pdf_rel_pitch')
            before=float(local_pitch) if local_pitch else (hint-anchors[position-1] if position else (anchors[1]-hint if len(anchors)>1 else .095))
            after=float(local_pitch) if local_pitch else (anchors[position+1]-hint if position+1<len(anchors) else before)
            # Breaker annotations are above their observed conductor. Adjacent
            # conductor boundaries partition the rows, rather than a broad
            # +/-9.5% band that can include several neighboring feeders.
            low=hint-before*.90;high=hint+after*.10;target=hint-before*.45
        for idx,candidate in enumerate(words):
            if idx in used:continue
            b=candidate['box']
            center_x=(b[0]+b[2])/(2*width);y=(b[1]+b[3])/(2*height)
            zones=search_zones.get(id(row),[])
            if zones and not any(x0-.015<=center_x<=x1+.015 and y0-.015<=y<=y1+.015 for x0,y0,x1,y1 in zones):continue
            if hint is not None and not low<=y<high:continue
            good=False
            for n in candidate['texts']:
                if cat in ('MCB','MCCB','RCBO'):
                    good=n.startswith(cat) and (not current or re.search(r'(?<!\d)'+re.escape(current)+r'(?!\d)',n))
                    pole=re.search(r'[1-4]P(?:\+N)?',spec)
                    actual_pole=re.search(r'[1-9]P(?:\+N)?',n)
                    if pole and actual_pole and pole.group(0)!=actual_pole.group(0):good=False
                elif cat=='DSL':good=n.startswith(('DSL','ISOLAT')) and (not current or re.search(r'(?<!\d)'+re.escape(current)+r'(?!\d)',n))
                elif cat=='PM':good=n=='PM'
                elif cat=='SCB':good='SCB' in n
                elif cat=='CT_RATIO':
                    numbers=re.search(r'(\d{2,4})/5A?',spec)
                    good=bool(numbers and numbers.group(1)+'/5' in n)
                if good:break
            if not good:continue
            # Strictly require an independently observed OCR glyph; do not
            # extrapolate from gridlines or the typical layout proportions.
            delta=abs(y-target) if target is not None else 0
            matches.append((delta,b,idx))
        if not matches:continue
        matches.sort(key=lambda x:x[0])
        _,b,idx=matches[0];used.add(idx)
        rel=[b[0]/width,b[1]/height,b[2]/width,b[3]/height]
        row['rel_boxes']=[unrotate_box(rel,turns)]
        row['location_quality']='文字实测'
        row['evidence_type']='printed_label'
        row['location_note']='定位到原图实际印刷的元器件标注；不是开关符号轮廓'
    return rows
