"""Electrical BOM capture core; do not infer purchasing substitutions from drawings."""
import re, json, csv, math, os, subprocess, shutil, tempfile
from pathlib import Path

TYPES=['微型断路器','塑壳断路器','漏电断路器','隔离开关','变频器','接触器','热继电器','电流互感器','多功能仪表','浪涌保护器','浪涌后备保护器','其他']
KEYWORDS=[('RCBO 漏电断路器',r'\b(?:RCBO|RCCB|漏电(?:断路器|保护器))\b'),('MCCB 塑壳断路器',r'\b(?:MCCB|塑壳(?:断路器)?)\b'),('MCB 微型断路器',r'\b(?:MCB|微型断路器|微断)\b'),('隔离开关',r'\b(?:DSL|ISOLATOR|隔离开关|隔离断路器)\b'),('变频器',r'\b(?:VFD|INVERTER|变频器)\b'),('接触器',r'\b(?:KM\d*|CONTACTOR|接触器)\b'),('热继电器',r'\b(?:FR\d*|OVERLOAD|热继电器)\b'),('电流互感器',r'\b(?:CT\d+|互感器)\b'),('多功能仪表',r'\b(?:PM|多功能仪表|电力仪表)\b'),('浪涌后备保护器',r'\b(?:SCB|后备保护器)\b'),('浪涌保护器',r'\b(?:SPD|浪涌保护器)\b')]

# Keep type detection before currents; a 63A MCB must never be merged with a 60A MCCB.
def parse_lines(text, page=1, cabinet='待分柜', source='PDF文字'):
    """Extract distinct printed occurrences, never deduplicate repeated devices by identical text."""
    rows=[]
    aliases=[
      ('RCBO 漏电断路器',r'(?<![A-Z])(?:RCBO|ROBO|RCB0|R[C(]BO)[-_\s]*'),
      ('MCCB 塑壳断路器',r'(?<![A-Z])(?:MCCB|MCC8|MCC0)[-_\s]*'),
      ('MCB 微型断路器',r'(?<![A-Z])(?:MCB|WCB|NMCB)[-_\s]*'),
      ('隔离开关',r'(?<![A-Z])(?:DSL|ISOLATOR)[-_\s]*'),
      ('变频器',r'(?<![A-Z])(?:VFD)[-_\s]*'),
    ]
    for raw in text.splitlines():
        line=' '.join(raw.strip().split())
        if not line: continue
        up=line.upper().replace('—','-').replace('–','-').replace('¥','V')
        if len(up)>500:continue
        occurrences=[]
        for kind,pattern in aliases:
            for m in re.finditer(pattern,up,re.I): occurrences.append((m.start(),m.end(),kind))
        occurrences.sort()
        # If OCR includes whole rows with multiple component identifiers, split at every identifier.
        for i,(start,finish,kind) in enumerate(occurrences):
            # skip a nested type inside a longer previously matched identifier
            if i and start<occurrences[i-1][1]:continue
            chunk=up[finish:(occurrences[i+1][0] if i+1<len(occurrences) else len(up))]
            chunk=chunk[:65]
            # ignore unqualified labels such as 'VFD FM' only if no nearby technical value
            amp=re.search(r'(\d{1,4}(?:\.\d+)?)\s*A\b',chunk)
            pole=re.search(r'([1-4])\s*P(?:\s*\+\s*N)?',chunk)
            curve=re.search(r'(?<![A-Z])([BCD])\s*([0-9ILOG]{1,3})\s*A?',chunk)
            kw=re.search(r'(\d+(?:\.\d+)?)\s*KW',chunk)
            vals=[]
            if curve:
                nr=curve.group(2).replace('I','1').replace('L','1').replace('O','0').replace('G','6')
                if nr.isdigit():vals.append(curve.group(1)+nr+'A')
            elif amp: vals.append(amp.group(1)+'A')
            if pole: vals.append(pole.group(1)+'P'+ ('+N' if re.search(r'\+\s*N',pole.group(0)) else ''))
            if kind=='变频器' and kw: spec=kw.group(1)+'kW'
            else: spec='/'.join(vals) or '待确认'
            rows.append(dict(cabinet=cabinet,page=page,kind=kind,spec=spec,qty=1,tag='',source=source,raw=line,status='待核对',remark='OCR候选，确认后使用'))
        if not occurrences:
            for kind,pattern in KEYWORDS:
                if kind in ('MCB 微型断路器','MCCB 塑壳断路器','RCBO 漏电断路器','隔离开关','变频器'):continue
                if re.search(pattern,up,re.I):
                    spec='待确认'
                    ratio=re.search(r'(\d{2,4})\s*/\s*5\s*A?',up)
                    if kind=='电流互感器' and ratio:spec=ratio.group(1)+'/5A'
                    rows.append(dict(cabinet=cabinet,page=page,kind=kind,spec=spec,qty=1,tag='',source=source,raw=line,status='待核对',remark='OCR候选，确认后使用'))
                    break
    return [normalize_recognition_row(r) for r in rows]

KIND_ALIASES={
    'MCB 微型断路器':'微型断路器',
    'MCCB 塑壳断路器':'塑壳断路器',
    'RCBO 漏电断路器':'漏电断路器',
}
PREFIXES={'微型断路器':'MCB', '塑壳断路器':'MCCB', '漏电断路器':'RCBO'}

def normalize_recognition_row(row):
    """Keep generic category separate from PDF part model/specification.

    Never replace a drawing specification with a catalog purchasing model.
    """
    old=row.get('kind','')
    new=KIND_ALIASES.get(old,old)
    spec=str(row.get('spec','') or '')
    if new in PREFIXES:
        prefix=PREFIXES[new]
        if not spec.upper().startswith(prefix):
            raw=str(row.get('raw','')).upper()
            label=prefix+('-TM' if prefix=='MCCB' and __import__('re').search(r'MCCB[\s\-_=]*TM',raw) else '')
            if spec and spec not in ('待确认','断路器类型待确认'):
                spec=label+'-'+spec
            elif spec=='断路器类型待确认':
                spec='型号待确认'
    row['kind']=new
    row['spec']=spec
    # Old versions inserted three CTs from a ratio alone. Preserve human
    # confirmation, but never carry that unverified assumption into a new BOM.
    if (new=='电流互感器' and row.get('status')!='已确认'
            and not row.get('manual_modified') and not row.get('quantity_verified')
            and row.get('quantity_source') not in ('manual','人工录入','人工核对')
            and any(t in str(row.get('remark','')) for t in
                    ('三相常规3只为推定值','数量3只为三相常规推定'))):
        if row.get('qty') is not None:row['legacy_inferred_qty']=row['qty']
        row['qty']=None
        row['quantity_source']='数量待核对（旧版推定已清除）'
    row.setdefault('quantity_source','人工录入' if row.get('source')=='人工录入' else '图纸候选，待核对')
    return row

def quantity_value(row):
    """Return a non-negative integral quantity, or None for unresolved counts."""
    value=row.get('qty')
    if value is None or value=='' or isinstance(value,bool):return None
    try:
        number=float(value)
    except (TypeError,ValueError,OverflowError):return None
    if not math.isfinite(number) or number<0 or not number.is_integer():return None
    return int(number)

def aggregate(rows, confirmed_only=False):
    """Keep known candidate counts separate from confirmed and unknown counts.

    qty is the sum of known quantities, not a claim that all candidates are
    confirmed. Unknown quantities never become one or zero silently.
    """
    groups={}
    for r in rows:
        if confirmed_only and r.get('status')!='已确认':continue
        key=(r.get('cabinet',''),r.get('kind',''),r.get('spec',''))
        if key not in groups:
            groups[key]={'cabinet':key[0],'kind':key[1],'spec':key[2],
                         'qty':0,'confirmed_qty':0,'pending_qty':0,'unknown_qty_count':0}
        group=groups[key];qty=quantity_value(r)
        if qty is None:
            group['unknown_qty_count']+=1
        else:
            group['qty']+=qty
            group['confirmed_qty' if r.get('status')=='已确认' else 'pending_qty']+=qty
    return list(groups.values())

def ct_quantity_from_text(text, ratio):
    """Only accept a printed CT quantity, never the usual three-phase count."""
    t=str(text).upper()
    patterns=[r'\bCT\s*(?:QTY\s*[:=]?|[X×*])\s*(\d{1,2})\b',
              r'(?<!\w)(\d{1,2})\s*[X×*]\s*CT\b',
              r'(?<!\d)(\d{1,2})\s*[X×*]\s*'+re.escape(ratio)]
    for pattern in patterns:
        m=re.search(pattern,t)
        if m and 0<int(m.group(1))<100:return int(m.group(1))
    return None

def quote_preview(rows, cabinet_type='柜', direct=0, vfd=0, fire=False, dual=False, lamp=True):
    direct=max(0,int(direct));vfd=max(0,int(vfd))
    base=500 if cabinet_type=='柜' else 300
    material=math.ceil((base+30*direct+50*vfd)/100)*100
    ctrl=math.ceil((direct+vfd)/2)
    # These are rule suggestions, never merge into original PDF capture.
    suggested=[('控制回路1P熔断器',f'{ctrl}只','每只最多供2路；独立照明/散热保护另行核验'),('三相指示灯','3只' if lamp else '0只','默认带，可关闭'),('辅料费用',f'{material}元','柜500/箱300 + 直启30/路 + 变频50/路，整百进位')]
    if vfd:suggested.append(('变频散热公共附件','一套待核','按柜合并，风机/百叶窗/温控器及控制回路需核验'))
    if fire or dual:suggested.append(('主开铜排总长度',f'{12 if dual else 8}米','双电源12米替代5米；消防无双电源时5+3'))
    else:suggested.append(('主开铜排总长度','5米','仅主开基准；不含分路铜排'))
    return suggested

def save_csv(path,rows):
    fields=['cabinet','page','kind','spec','qty','tag','source','status','raw','remark','quantity_source','confirmed_qty','pending_qty','quantity_unknown']
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for row in rows:
            r=dict(row);qty=quantity_value(r);r['qty']=qty
            r['confirmed_qty']=qty if qty is not None and r.get('status')=='已确认' else 0
            r['pending_qty']=qty if qty is not None and r.get('status')!='已确认' else 0
            r['quantity_unknown']=qty is None
            writer.writerow(r)

def save_xlsx(path,rows,preview=None):
    """Export candidate evidence and confirmed totals as separate, plain cells."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb=Workbook();wb.remove(wb.active)
    def sheet(name, heads, values):
        sh=wb.create_sheet(name)
        for values_row in [heads]+values:
            sh.append(values_row)
        for row in sh:
            for cell in row:
                # Drawing/OCR text must remain literal, including leading '='.
                if isinstance(cell.value,str):cell.data_type='s'
        for cell in sh[1]:
            cell.fill=PatternFill('solid',fgColor='17324D')
            cell.font=Font(color='FFFFFF',bold=True)
            cell.alignment=Alignment(wrap_text=True)
        sh.freeze_panes='A2';sh.auto_filter.ref=sh.dimensions
        for column in sh.columns:
            width=min(60,max(12,max(len(str(c.value or '')) for c in column)+2))
            sh.column_dimensions[get_column_letter(column[0].column)].width=width
        return sh
    fields=('cabinet','page','kind','spec','qty','tag','source','status','raw','remark','quantity_source')
    details=[]
    for r in rows:
        values=[quantity_value(r) if k=='qty' else r.get(k,'') for k in fields]
        details.append(values)
    sheet('图纸识别明细',['柜号','PDF页','元器件类别','图纸型号/参数','数量（空白待核）','位号','来源','确认状态','图纸原文','备注','数量依据'],details)
    keys=('cabinet','kind','spec','qty','confirmed_qty','pending_qty','unknown_qty_count')
    sheet('分类汇总',['柜号','元器件类别','图纸型号/参数','候选已知数量（含已确认）','已确认数量','待核对已知数量','数量未知记录数'],
          [[v[k] for k in keys] for v in aggregate(rows)])
    sheet('已确认汇总',['柜号','元器件类别','图纸型号/参数','已确认数量','数量未知记录数'],
          [[v[k] for k in ('cabinet','kind','spec','confirmed_qty','unknown_qty_count')] for v in aggregate(rows,confirmed_only=True)])
    surge=[r for r in rows if r.get('kind') in ('浪涌保护器','浪涌后备保护器')]
    if surge:
        vals=[]
        for r in surge:
            meta=r.get('surge_params') or {}
            vals.append([r.get('cabinet',''),r.get('kind',''),r.get('spec',''),
                meta.get('spd_type',''),meta.get('imax_ka'),meta.get('in_ka'),meta.get('iimp_ka'),
                meta.get('spd_pole','') if r.get('kind')=='浪涌保护器' else meta.get('pole',''),
                meta.get('uc_v'),meta.get('up_kv'),quantity_value(r),r.get('remark',''),r.get('status','')])
        sheet('防雷原图参数',['柜号','元器件类别','图纸型号参数','T类型','Imax(kA)','In(kA)','Iimp(kA)','极数','Uc(V)','Up(kV)','数量（空白待核）','来源说明','确认状态'],vals)
    sheet('规则预览',['补充项目','计算建议','说明'],[list(x) for x in (preview or [])])
    wb.save(str(path))


def locate_tesseract():
    import pytesseract, shutil
    candidates=[shutil.which('tesseract'),r'C:\Program Files\Tesseract-OCR\tesseract.exe',r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd=candidate
            return candidate
    return None

def ocr_image(img):
    import pytesseract
    from PIL import ImageOps, ImageEnhance, ImageFilter
    if not locate_tesseract():
        raise RuntimeError('未发现Tesseract OCR。请先安装Tesseract OCR并加入PATH，再重启软件。')
    # OCR images of electrical drawings are sparse: psm 11 works for scattered annotations,
    # psm 6 better for tight vertically stacked feeder rows.
    if img.width<900: img=img.resize((img.width*2,img.height*2))
    if img.width>5000:
        ratio=5000/img.width;img=img.resize((5000,max(1,int(img.height*ratio))))
    gray=ImageEnhance.Contrast(ImageOps.grayscale(img)).enhance(1.5)
    outs=[]
    for psm in (6,11):
        try:outs.append(pytesseract.image_to_string(gray,config=f'--psm {psm}',lang='eng'))
        except Exception as e:raise RuntimeError('OCR失败：'+str(e))
    # One output is returned, not a concatenation that would double-count everything.
    return max(outs,key=lambda s: sum(s.upper().count(w) for w in ('MCB','MCCB','RCBO','DSL','VFD')))

# V1.2: graph-structured feeder capture. Never convert cable CT/JDG into current transformers.
def parse_cabinet_id(raw):
    raw=raw.upper().replace('—','-').replace('–','-')
    m=re.search(r'\b(?:[A-Z]-)?(\d+\s*[-–]\s*\d+\s*[-–]?\s*(?:AP|PP|VFD|AL|APZ)\s*\d+)\b',raw)
    return re.sub(r'\s+','',m.group(1)).replace('--','-') if m else ''

def recognize_cabinet_image(img, page=1, source='V1.2逐回路OCR'):
    """Electrical single-line cabinet with horizontal feeder rows.
    Returns (rows, diagnostics). Segments by horizontal conductor lines, OCRs each
    feeder once and rejects cable text as a device source. No claim of full automation.
    """
    import numpy as np
    import pytesseract
    from PIL import ImageEnhance, ImageOps
    if not locate_tesseract():
        raise RuntimeError('找不到Tesseract OCR，建议检查 C:\\Program Files\\Tesseract-OCR')
    img=img.convert('RGB')
    w,h=img.size
    # A scale-specific detector uses relative geometry; nonmatching layouts are
    # explicitly reported as unsupported rather than inventing result counts.
    from feeder_geometry_v152 import detect_feeder_lines, read_drawn_tags
    lines, geometry_diag=detect_feeder_lines(img)
    if len(lines)<4:
        return [], {'mode':'fallback','reason':geometry_diag.get('reason','未识别到连续出线'), 'feeders':0,'raw':''}
    printed_tags,tag_warnings=read_drawn_tags(img,lines,geometry_diag.get('groups'))
    def read_crop(box, psm=7):
        crop=img.crop(tuple(int(z) for z in box))
        crop=crop.resize((max(250,crop.width*3),max(70,crop.height*3)))
        g=ImageEnhance.Contrast(ImageOps.grayscale(crop)).enhance(1.7)
        return pytesseract.image_to_string(g,lang='eng',config=f'--psm {psm}').strip()
    # Every detected physical feeder produces a record, including unknown OCR.
    # The printed W tag is read independently; missing tags are NEVER inferred.
    # For each physical feeder, gather independent OCR readings. The original
    # narrow cut often clips the '+' or 'N' and even drops a whole row.
    default_height=geometry_diag.get('pitch') or (float(np.median(np.diff(lines))) if len(lines)>1 else h*.05)
    pitches={y:group['pitch'] for group in geometry_diag.get('groups',[]) for y in group['lines']}
    valid_ratings={1,2,3,4,6,10,13,16,20,25,32,40,50,60,63,80,100,125,160,200,225,250,315,320,400,500,630,800,1000,1250,1600}
    def interpret(text):
        t=text.upper().replace('—','-').replace('–','-').replace(' ','').replace('\n','')
        t=t.replace('CI','C1').replace('CO','C0').replace('DI','D1')
        # A slash followed by IP is a common OCR form of /1P.
        t=re.sub(r'(?<=/)I(?=P)', '1', t)
        if re.search(r'MCCB|WCCB|MCC8',t): kind='MCCB 塑壳断路器'
        elif re.search(r'RCBO|ROBO|RCB0|R0BO|RCBQ',t):kind='RCBO 漏电断路器'
        elif re.search(r'MCB|MC8|MCR|NCR',t):kind='MCB 微型断路器'
        else:return None
        # Extract electrical rating ONLY after the breaker name, never from MCB itself.
        mtype=re.search(r'(?:MCCB|WCCB|MCC8|RCBO|ROBO|RCB0|R0BO|RCBQ|MCB|MC8|MCR|NCR)',t)
        rating_text=t[mtype.end():] if mtype else t
        # Never silently coerce a nonstandard current into the nearest rating.
        curve=re.search(r'([BCD])([0-9IOBLG]{1,3})A?',rating_text)
        bare=re.search(r'(?<!\d)([0-9IOBLG]{2,4})A',rating_text)
        cur='';amp=None
        if curve:
            n=curve.group(2).translate(str.maketrans('IOLGB','10168'))
            if n.isdigit():cur=curve.group(1)+n+'A';amp=int(n)
        elif bare:
            n=bare.group(1).translate(str.maketrans('IOLGB','10168'))
            if n.isdigit():cur=n+'A';amp=int(n)
        pole=''
        # Be lenient about separators, but require positive evidence of each pole.
        pm=re.search(r'([1-4I])P(?:[+\-]?[4H]?N)?',t)
        if pm:
            pole=pm.group(1).replace('I','1')+'P'
            if re.search(r'P[+\-]?[4H]?N',pm.group(0)) or re.search(r'P\+N',t):pole+='+N'
        return dict(kind=kind,cur=cur,pole=pole,amp=amp,valid=amp in valid_ratings if amp is not None else False,raw=text)
    def rate(c):
        return (int(bool(c['kind']))*3 + int(c['valid'])*5 + int(bool(c['pole']))*3 + int(c['pole'].endswith('+N'))*2 + int('MCCB' in c['raw'].upper() or 'RCBO' in c['raw'].upper() or 'MCB' in c['raw'].upper())*2)
    # First use a broad cut; OCR retries only for incomplete or contradictory cases.
    variants=[(.255,.45,.73,.08,7),(.26,.48,1.03,-.10,7),(.26,.44,.88,-.05,6),(.265,.40,.85,.02,7),(.255,.46,.10,-.68,6)]
    feeder_ocr=[]
    for ix,y in enumerate(lines):
        row_height=pitches.get(y,default_height)
        samples=[]
        for j,(xl,xr,above,below,psm) in enumerate(variants):
            crop=(w*xl,max(0,y-row_height*above),w*xr,min(h,y-row_height*below))
            raw=read_crop(crop,psm=psm)
            interpreted=interpret(raw)
            if interpreted:samples.append(interpreted)
            if j==0 and interpreted and interpreted['valid'] and interpreted['pole'] and interpreted['pole'].endswith('+N'):
                break
            if j==1 and interpreted and interpreted['valid'] and interpreted['pole'] and interpreted['kind']=='MCCB 塑壳断路器':
                break
            if j>=2 and samples and max(rate(q) for q in samples)>=13:
                break
        feeder_ocr.append((y,samples))
    # OCR title and measuring zone in separate, constrained regions.
    header=read_crop((w*.02,h*.03,w*.36,h*.20),psm=6)
    upper=read_crop((w*.08,h*.32,w*.29,h*.55),psm=11)
    bottom=read_crop((w*.23,h*.80,w*.61,h*.96),psm=11)
    cabinet=parse_cabinet_id(header) or parse_cabinet_id(ocr_image(img)) or '待确认柜号'
    def item(kind,spec,qty,tag,raw,remark='逐回路OCR候选，核对规格'):
        return dict(cabinet=cabinet,page=page,kind=kind,spec=spec,qty=qty,tag=tag,source=source,raw=raw,status='待核对',remark=remark)
    rows=[]
    for i,(y,candidates) in enumerate(feeder_ocr,1):
        row_height=pitches.get(y,default_height)
        tag=printed_tags[i-1] if i-1<len(printed_tags) else ''
        pos={'pdf_rel_y':round(float(y/h),5), 'pdf_rel_x':0.29, 'pdf_rel_pitch':float(row_height/h), 'record_role':'feeder', 'physical_row_index':i}
        if not candidates:
            extra=read_crop((w*.20,max(0,y-row_height*.94),w*.49,min(h,y-row_height*.01)),psm=6)
            observed=interpret(extra)
            if observed and observed['valid']:candidates.append(observed)
        if not candidates:
            # Do not confuse a failed OCR row with an absent component.
            if True:
                rec=item('其他','断路器类型待确认',None,tag,'多次OCR未读出','线路已检测，元件类型及数量待确认；不计入已知数量')
                rec.update(pos);rows.append(rec)
            continue
        best=max(candidates,key=rate)
        # Competing OCR values are saved as uncertainty, never auto-substituted.
        valid=[c for c in candidates if c['valid']]
        supported={}
        for c in valid:
            key=(c['kind'],c['cur'])
            supported[key]=supported.get(key,0)+1
        if supported:
            most=max(supported,key=lambda k:(supported[k], k==(best['kind'],best['cur'])))
            best=max([c for c in valid if (c['kind'],c['cur'])==most],key=rate)
        pole_candidates=[c['pole'] for c in candidates if c['pole']]
        if pole_candidates:
            # Prefer explicit +N rather than a truncated 1P when the same row
            # independently shows the plus-N suffix.
            best_pole=sorted(pole_candidates,key=lambda p:(pole_candidates.count(p),int('+N' in p)),reverse=True)[0]
            if '+N' in pole_candidates and best_pole=='1P': best_pole='1P+N'
        else:best_pole=''
        # A 2P RCBO suffix can be hallucinated from adjacent cable annotations.
        # Explicit +N belongs to 1P+N in this feeder format; preserve unclear cases for review.
        if best['kind']=='RCBO 漏电断路器' and best_pole=='2P+N': best_pole='2P'
        vals=[v for v in (best['cur'],best_pole) if v]
        spec='/'.join(vals) if vals else '待确认'
        issues=[]
        if not best['valid']:issues.append('电流待确认')
        if not best_pole:issues.append('极数待确认')
        if len(supported)>1 and max(supported.values())<2:issues.append('OCR电流冲突')
        if issues:spec+='（'+','.join(issues)+'）'
        evidence=' | '.join(dict.fromkeys(c['raw'].replace('\n',' ') for c in candidates))
        rec=item(best['kind'],spec,1,tag,evidence,'多次局部OCR交叉核对；仍须人工确认')
        rec.update(pos)
        rows.append(rec)
    if not rows:return [],{'mode':'fallback','reason':'识别了横线但未读到可靠断路器标注','feeders':len(feeder_ocr),'raw':'\n'.join(' | '.join(c['raw'] for c in cand) for _,cand in feeder_ocr)}
    # Singleton measurement items must not be triggered on each occurrence of CT in cable codes.
    ratio_source=upper
    ratio=re.search(r'\b(\d{2,4})\s*/\s*5(?:A|\b)',ratio_source.upper().replace('O','0'))
    if not ratio:
        # Compact panels put the CT ratio just below the narrow upstream OCR
        # region. Retry the measuring branch alone, without cable CT legends.
        ratio_source=read_crop((w*.07,h*.29,w*.32,h*.62),psm=6)
        ratio=re.search(r'\b(\d{2,4})\s*/\s*5(?:A|\b)',ratio_source.upper().replace('O','0'))
    if ratio:
        quantity=ct_quantity_from_text(ratio_source,ratio.group(0))
        rec=item('电流互感器',ratio.group(1)+'/5A',quantity,'',ratio_source,
                 '原图数量标注，需人工核对' if quantity is not None else '仅识别到变比；数量留空，请核对原图符号或倍数标注')
        rec['quantity_source']='图纸数量标注' if quantity is not None else '数量待核对'
        rows.append(rec)
    if re.search(r'\bPM\b',upper,re.I):rows.append(item('多功能仪表','PM',1,'',upper,'仅测量区域一次计入'))
    isol=re.search(r'\bDSL\s*[- ]?\s*(\d{2,4})\s*A\s*/\s*([34])\s*P',upper,re.I)
    if isol:rows.append(item('隔离开关',isol.group(1)+'A/'+isol.group(2)+'P',1,'',upper,'由进线测量区域识别'))
    # SPD/SCB are tricky: recognize only identifiable type labels from the bottom zone.
    if re.search(r'SCB\s*2|SCB\b|HKPD.SCB',bottom,re.I):rows.append(item('浪涌后备保护器','待确认',1,'',bottom,'底部浪涌支路，规格待核对'))
    if re.search(r'SPD|8\s*/\s*20\s*(?:US|ΜS|MS)|Imax\s*=\s*80',bottom,re.I):rows.append(item('浪涌保护器','待确认',1,'',bottom,'底部浪涌支路，规格待核对'))
    diag={'mode':'row','cabinet':cabinet,'feeders':len(rows) - sum(r['kind'] in ('电流互感器','多功能仪表','隔离开关','浪涌后备保护器','浪涌保护器') for r in rows),
          'raw':'柜号原文:\n'+header+'\n\n进线测量区域:\n'+upper+'\n\n逐回路:\n'+'\n'.join(f'{i}: '+(' | '.join(c['raw'] for c in samples) or '[OCR未识别]') for i,(_,samples) in enumerate(feeder_ocr,1))+'\n\n底部:\n'+bottom}
    diag['unreadable_tags']=tag_warnings
    diag['detected_geometry_rows']=len(lines)
    diag['geometry']=geometry_diag
    diag['geometry_warnings']=geometry_diag.get('warnings',[])
    from recognition_v14 import upgrade_recognition
    rows,diag=upgrade_recognition(img,rows,diag)
    for rec in rows:
        normalize_recognition_row(rec)
    return rows,diag
