"""Measured PDF-vector motor symbols and independent load-based sizing advice.

Supported template: an open contact with semicircular fixed contact; thermal
relay rectangle with a five-segment internal step. Text is read only after the
symbol has been found. Unsupported/scanned symbols remain for manual review.
"""
import math
import re
import fitz


def _ocr(page, box, psm=7, scale=5):
    import pytesseract
    from PIL import Image, ImageOps
    box=fitz.Rect(box)&page.rect
    if box.is_empty:return ''
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=box,alpha=False)
    return pytesseract.image_to_string(ImageOps.expand(Image.frombytes('RGB',(pix.width,pix.height),pix.samples),border=16,fill='white'),
                                      lang='eng',config=f'--psm {psm}').strip()


def load_selection(power_kw):
    """User's estimating rule. This does not change a printed device rating."""
    if power_kw is None or not math.isfinite(float(power_kw)) or float(power_kw)<=0:return None
    current=round(float(power_kw)*2,6)
    minimum=round(current*1.3,6)
    # Common Schneider TeSys D AC-3 size steps; coil/order suffix is unresolved.
    steps=[9,12,18,25,32,38,40,50,65,80,95]
    selected=next((n for n in steps if n>minimum),None)
    return dict(load_kw=power_kw,estimated_current_a=current,contactor_threshold_a=minimum,
        contactor_suggested_a=selected,contactor_series='Schneider TeSys D (AC-3)',
        thermal_target_a=current,rule='用户估算规则：I=2×kW，接触器额定电流>1.3×I，最小9A',
        note='选型建议待核对；热继整定范围须覆盖负载电流，具体系列/型号/线圈电压另行确认')


def vector_motor_symbols(page, clip):
    """Return symbol types and real page-coordinate boxes, not text guesses."""
    clip=fitz.Rect(clip)
    paths=[p for p in page.get_drawings() if clip.contains(p['rect'])]
    symbols=[]
    slants=[]
    for p in paths:
        if len(p['items'])==1 and p['items'][0][0]=='l':
            _,a,b=p['items'][0]
            if 5<abs(a.x-b.x)<35 and 2<abs(a.y-b.y)<18:slants.append(p['rect'])
    for p in paths:
        r=p['rect'];items=p['items']
        # A fixed semicircular contact plus its adjacent open blade. A breaker
        # cross or a bare isolator blade cannot satisfy the semicircle evidence.
        if len(items)==2 and all(i[0]=='c' for i in items) and 2<r.width<15 and 1<r.height<8 and 1.7<r.width/r.height<2.3:
            for blade in slants:
                if abs(blade.x0-(r.x0+r.x1)/2)<1.2 and abs(blade.y0-r.y0)<1.2 and blade.x1>r.x1+3:
                    symbols.append(('接触器',r|blade));break
        # An outline alone could be a fuse, VFD, or label. The internal step
        # must meet the rectangle's sides and contain exactly two vertical legs.
        if len(items)==1 and items[0][0]=='re' and 4<r.width<24 and 5<r.height<30 and .35<r.width/r.height<1.4:
            for inner in paths:
                cmds=inner['items'];q=inner['rect']
                if len(cmds)!=5 or not all(c[0]=='l' for c in cmds):continue
                if not (abs(q.x0-r.x0)<.7 and abs(q.x1-r.x1)<.7 and r.y0<q.y0<q.y1<r.y1):continue
                axes=[abs(c[1].x-c[2].x)<.1 for c in cmds]
                if axes==[False,True,False,True,False]:
                    symbols.append(('热继电器',r));break
    result=[]
    for kind,r in symbols:
        if not any(k==kind and abs(q.x0-r.x0)<1 and abs(q.y0-r.y0)<1 for k,q in result):result.append((kind,r))
    return sorted(result,key=lambda s:(s[1].y0,s[1].x0))


def recognize_motor_symbols(page, clip, rows, cabinet, page_number):
    clip=fitz.Rect(clip);symbols=vector_motor_symbols(page,clip)
    # Determine the rightmost power-table divider from long actual rules.
    dividers=[]
    for p in page.get_drawings():
        if not clip.intersects(p['rect']):continue
        for cmd in p['items']:
            if cmd[0]=='l':edges=[cmd[1:]]
            elif cmd[0]=='qu':
                q=cmd[1];edges=[(q.ul,q.ur),(q.ur,q.lr),(q.lr,q.ll),(q.ll,q.ul)]
            elif cmd[0]=='re':
                r=cmd[1];edges=[(r.tl,r.bl),(r.tr,r.br)]
            else:continue
            for a,b in edges:
                mid=(a.x+b.x)/2
                if abs(a.x-b.x)<max(3,abs(a.y-b.y)*.005) and abs(a.y-b.y)>clip.height*.25 and clip.x0+clip.width*.7<mid<clip.x1-5:
                    if not any(abs(mid-(c.x+e.x)/2)<2 for c,e in dividers):dividers.append((a,b))
    dividers.sort(key=lambda edge:(edge[0].x+edge[1].x)/2)
    feeder_rows=[r for r in rows if r.get('record_role')=='feeder']
    result=[];cells={}
    for kind,box in symbols:
        # Associate only rows sharing the physical conductor. Labels above
        # their blade/relay are extracted independently from device detection.
        cy=box.y0 if kind=='接触器' else box.y0+box.height*.34
        near=[r for r in feeder_rows if r.get('pdf_boxes') and abs((r['pdf_boxes'][0][1]+r['pdf_boxes'][0][3])/2-cy)<25]
        anchor=min(near,key=lambda r:abs((r['pdf_boxes'][0][1]+r['pdf_boxes'][0][3])/2-cy)) if near else None
        text=_ocr(page,(box.x0-5,box.y0-16,box.x1+(20 if kind=='热继电器' else 7),box.y0-1))
        if kind=='热继电器':
            m=re.search(r'(\d+(?:\.\d+)?)\s*[~～−–-]\s*(\d+(?:\.\d+)?)\s*A',text)
            spec=(m.group(1)+'~'+m.group(2)+'A') if m and 0<float(m.group(1))<=float(m.group(2)) else '整定范围待确认'
        else:
            m=re.search(r'(?<![\d.])(\d+(?:\.\d+)?)\s*A\b',text)
            spec=m.group(1)+'A' if m else '额定电流待确认'
        power=None;power_raw='';tag=anchor.get('tag','') if anchor else ''
        cell_key=round(cy)
        if cell_key in cells:
            power,power_raw,tag=cells[cell_key]
        elif dividers:
            cy=float(cell_key)
            at_y=lambda edge:edge[0].x+(cy-edge[0].y)*(edge[1].x-edge[0].x)/(edge[1].y-edge[0].y)
            power_left=at_y(dividers[-1]);readings=[];values=[]
            for scale in (5,8):
                text=_ocr(page,(power_left+2,cy-20,clip.x1-2,cy+7),psm=6,scale=scale)
                readings.append(text)
                matches=re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*K\s*W\b',text,re.I)
                if not matches:matches=re.findall(r'^\s*(\d+(?:\.\d+)?)\s*$',text,re.M)
                if len(set(matches))==1:values.append(float(matches[0]))
            power_raw=' | '.join(readings)
            # A dropped decimal point changes sizing by tenfold. Conflicting
            # independent renderings must not produce a purchasing suggestion.
            if len(values)==2 and values[0]==values[1]:power=values[0]
            if len(dividers)>=3:
                tag_text=_ocr(page,(at_y(dividers[0])+2,cy-16,at_y(dividers[1])-2,cy-1))
                tag_match=re.fullmatch(r'W[1-9]\d{0,2}',tag_text.strip().upper())
                if tag_match:tag=tag_match.group(0)
            cells[cell_key]=(power,power_raw,tag)
        record=dict(cabinet=cabinet,page=page_number,kind=kind,spec=spec,qty=1,
            tag=tag,status='待核对',source='PDF矢量电气符号',
            raw=text,record_role='motor_symbol',quantity_source='独立电气符号计数',
            pdf_boxes=[[round(v,3) for v in box]],evidence_type='verified_symbol',
            location_quality='符号实测',location_note='开触点半圆+刀片' if kind=='接触器' else '矩形内五段热元件阶梯',
            remark='按符号识别，原图参数与负载选型建议分开；需核对回路归属',load_raw=power_raw)
        if power is not None:
            advice=load_selection(power);record['selection_advice']=advice
            if advice:
                record['remark']+=f"；负载{power:g}kW→估算{advice['estimated_current_a']:g}A，接触器建议{advice['contactor_suggested_a'] or '需选更高档'}A；热继范围应覆盖该负载电流（选型建议）"

        result.append(record)
    return result


def apply_ct_evidence(page, clip, rows):
    """Count measured CT rings in the main metering branch, never cable CT text."""
    clip=fitz.Rect(clip)
    circles=[]
    for p in page.get_drawings():
        r=p['rect'];items=p['items']
        if not clip.contains(r) or r.x1>clip.x0+clip.width*.4:continue
        if not (6<r.width<24 and .88<r.width/max(r.height,.01)<1.12 and len(items)>=12 and all(i[0]=='l' for i in items)):continue
        center=fitz.Point((r.x0+r.x1)/2,(r.y0+r.y1)/2)
        radii=[abs(i[1]-center) for i in items]
        if min(radii)>0 and max(radii)/min(radii)<1.2:circles.append(r)
    groups=[]
    for first in circles:
        aligned=sorted([r for r in circles if abs(r.x0-first.x0)<1.5 and abs(r.width-first.width)<1],key=lambda r:r.y0)
        if len(aligned)==3 and all(1.1*first.height<b.y0-a.y0<3*first.height for a,b in zip(aligned,aligned[1:])):
            if not any(abs(g[0].x0-aligned[0].x0)<1 for g in groups):groups.append(aligned)
    ct=[r for r in rows if r.get('kind')=='电流互感器']
    if len(groups)==1 and not ct:
        group=groups[0]
        ratio_text=_ocr(page,(min(r.x0 for r in group)-12,max(r.y1 for r in group)+1,
                              max(r.x1 for r in group)+12,max(r.y1 for r in group)+19),psm=6,scale=8)
        ratio=re.search(r'(\d{1,4})\s*/\s*5\s*A?',ratio_text,re.I)
        if ratio or any(r.get('kind')=='多功能仪表' for r in rows):
            record=dict(cabinet=next((r.get('cabinet','') for r in rows if r.get('cabinet')),'待确认柜号'),
                page=page.number+1,kind='电流互感器',spec=ratio.group(1)+'/5A' if ratio else '变比待确认',
                qty=3,tag='',status='待核对',source='主进线CT矢量符号',raw=ratio_text,record_role='metering')
            rows.append(record);ct.append(record)
    if len(groups)==1 and len(ct)==1:
        ct[0].update(qty=3,quantity_source='主进线三相测量：三个实际CT符号',quantity_verified=True,
            pdf_boxes=[[round(v,3) for v in r] for r in groups[0]],evidence_type='verified_symbol',
            location_quality='符号实测',location_note='原图测量支路三个同轴互感器符号',
            remark='主进线三相CT一套3只，依据实际测量符号；待人工核对')
    elif ct:
        # User's explicit project convention: a main 3P metering circuit uses
        # a three-phase CT set. Keep the convention visible as a rule source.
        main_three_phase=any((r.get('record_role')=='incoming' or r.get('kind')=='隔离开关') and
                             re.search(r'/3P(?:\b|$)',r.get('spec','')) for r in rows)
        meter=any(r.get('kind')=='多功能仪表' for r in rows)
        if main_three_phase and meter:
            for item in ct:
                if item.get('qty') is None:
                    item.update(qty=3,quantity_source='用户规则：主进线3P三相计量CT一套3只',
                                remark='主进线3P与测量支路关联，按用户三相CT配置规则计3只；非逐符号实测')
    return rows
