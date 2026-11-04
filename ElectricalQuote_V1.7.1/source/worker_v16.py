"""Pure multiprocessing worker. Never imports Tk, safe for Windows spawn."""
import os, json, hashlib
import fitz
from PIL import Image

ALGORITHM_VERSION='v171-quantity-evidence-and-region-binding-1'

def cache_key(path,region):
    """Identity-independent cache, invalidated by actual PDF content changes."""
    digest=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    spec=[os.path.realpath(path),digest.hexdigest(),region['page'],region['box'],
          ALGORITHM_VERSION,region.get('rotation_override','自动')]
    return hashlib.sha256(json.dumps(spec,ensure_ascii=False).encode()).hexdigest()

def bind_region(data,region):
    """Cached evidence belongs to the current request, never an old UI id."""
    data['region_id']=region['id']
    name=region.get('cabinet')
    if not name or name=='待确认柜号':name=data.get('diag',{}).get('cabinet')
    for row in data['rows']:
        row['region_id']=region['id']
        if name:row['cabinet']=name
    return data


def run_one(args):
    path,region,cache_dir=args
    os.environ['OMP_THREAD_LIMIT']='1'
    os.environ['OPENBLAS_NUM_THREADS']='1'
    from core import recognize_cabinet_image, normalize_recognition_row
    id=region['id'];page=region['page'];box=region['box']
    key=cache_key(path,region)
    cp=os.path.join(cache_dir,key+'.json')
    if os.path.isfile(cp):
        try:
            with open(cp,encoding='utf8') as f:data=json.load(f)
            if not isinstance(data.get('rows'),list) or not isinstance(data.get('diag'),dict):
                raise ValueError('Invalid cached recognition result')
            data['cached']=True
            return bind_region(data,region)
        except (OSError,ValueError,TypeError,KeyError):pass
    doc=fitz.open(path)
    try:
        p=doc[page-1];clip=fitz.Rect(box)&p.rect
        pix=p.get_pixmap(matrix=fitz.Matrix(3.0,3.0),clip=clip,alpha=False)
        img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        from orientation_v16 import detect_rotation,rotate,unrotate_box
        from vertical_recognition_v16 import find_vertical_columns, recognize_vertical
        turns,orientation=detect_rotation(img,region.get('rotation_override','自动'))
        corrected=rotate(img,turns)
        columns,column_info=find_vertical_columns(corrected)
        # A true vertical-branch schedule is predominantly wide; a tall
        # horizontally-fed cabinet can contain table columns but is NOT vertical.
        vertical=len(columns)>=2 and corrected.width>=corrected.height*1.08
        if vertical:
            rows,diag=recognize_vertical(corrected,page,region.get('cabinet','待确认柜号'))
            # All result locations must be mapped from normalized panel back to
            # original PDF pixels; painting uses the unrotated PDF coordinates.
            for row in rows:
                if row.get('rel_boxes'):
                    row['rel_boxes']=[unrotate_box(b,turns) for b in row['rel_boxes']]
        else:
            rows,diag=recognize_cabinet_image(corrected,page,source='V1.6结构识别')
            for row in rows:
                if row.get('rel_boxes'):
                    row['rel_boxes']=[unrotate_box(b,turns) for b in row['rel_boxes']]
                if 'pdf_rel_x' in row and 'pdf_rel_y' in row:
                    # Converted relative center evidence; boxes will be built below.
                    row['_anchor_corrected_y']=float(row['pdf_rel_y'])
                    row.pop('pdf_rel_x',None);row.pop('pdf_rel_y',None)
        diag['orientation']=orientation
        diag['layout']='纵向分支/底部表格' if vertical else '横向馈线/其他'

        from incoming_v153 import recognize_incoming,merge_incoming
        from compact_v153 import recognize_compact
        if not vertical and diag.get('mode')=='fallback':
            compact,compact_diag=recognize_compact(corrected,page,'V1.6短回路专用识别')
            if compact:
                rows,diag=compact,compact_diag
                for row in rows:
                    if row.get('rel_boxes'):
                        row['rel_boxes']=[unrotate_box(b,turns) for b in row['rel_boxes']]
                diag['orientation']=orientation;diag['layout']='短回路'
        if not vertical:
            upstream=recognize_incoming(corrected,page,cabinet=diag.get('cabinet','待确认柜号'))
            for row in ([upstream] if upstream else []):
                if row.get('rel_boxes'):
                    row['rel_boxes']=[unrotate_box(b,turns) for b in row['rel_boxes']]
            rows=merge_incoming(rows,upstream)
        # Motor/VFD panels need a branch-specific pass. Only add physically
        # observed VFD glyphs; direct-start is never guessed from an FM load.
        from motor_v153 import recognize_vfd_candidates
        cabinet_hint=region.get('cabinet') or diag.get('cabinet','')
        for candidate in ([] if vertical else recognize_vfd_candidates(corrected,page,cabinet_hint)):
            if candidate.get('rel_boxes'):
                candidate['rel_boxes']=[unrotate_box(b,turns) for b in candidate['rel_boxes']]
            if not any(r.get('kind')=='变频器' and r.get('rel_boxes')==candidate['rel_boxes'] for r in rows):
                rows.append(candidate)
        # CAD text may still expose PM as a native PDF text object even when
        # the breaker labels are vector glyphs. Use it for accurate positioning.
        native_words=[w for w in p.get_text('words',clip=clip) if str(w[4]).strip().upper()=='PM']
        if native_words:
            wd=native_words[0]
            rects=[]
            for draw in p.get_drawings():
                rr=draw.get('rect')
                if rr and rr.contains(fitz.Point((wd[0]+wd[2])/2,(wd[1]+wd[3])/2)) and 8<rr.width<140 and 8<rr.height<90:
                    rects.append(rr)
            frame=min(rects,key=lambda rr:rr.get_area()) if rects else fitz.Rect(wd[:4])
            target=next((r for r in rows if r['kind']=='多功能仪表'),None)
            if target is None:
                target={'cabinet':diag.get('cabinet','待确认柜号'),'page':page,
                        'kind':'多功能仪表','spec':'PM','qty':1,'tag':'',
                        'status':'待核对','source':'V1.5分柜识别','raw':'PM (PDF原生文字)',
                        'remark':'PM原生文字和图框定位；需人工核对'}
                rows.append(target)
            target['pdf_boxes']=[[round(frame.x0,2),round(frame.y0,2),round(frame.x1,2),round(frame.y1,2)]]
            target['location_quality']='符号实测' if rects else '文字实测'
            target['evidence_type']='verified_symbol' if rects else 'printed_label'
            target['location_note']='PDF矢量仪表矩形与PM文字核对' if rects else 'PDF原生PM文字坐标（未验证仪表外框）'
        # Independently inspect the observed surge branch, preserving T1/T2,
        # Imax, In, Uc, Up and the separate SPD vs SCB original model.
        from surge_recognition_v17 import recognize_surge, surge_pair_warnings
        surge_warnings=[]
        if not vertical:
            import builtins
            old_ids={builtins.id(r) for r in rows}
            rows,surge_warnings=recognize_surge(corrected,rows,page,diag.get('cabinet') or cabinet_hint)
            for item in rows:
                if builtins.id(item) not in old_ids and item.get('rel_boxes'):
                    item['rel_boxes']=[unrotate_box(bb,turns) for bb in item['rel_boxes']]
        else:
            surge_warnings=surge_pair_warnings(rows)
        diag['surge_warnings']=surge_warnings
        diag['surge_pair_status']='待复核' if surge_warnings else ('已找到SPD与SCB' if any(x['kind']=='浪涌保护器' for x in rows) else '未发现浪涌器件')
        # Clear layout-guessed source boxes; reattach ONLY OCR-observed glyphs.
        from precise_locator_v161 import locate_observed_printed_labels
        preserved=[]
        for r in rows:
            if r.get('evidence_type')=='verified_symbol':
                preserved.append((r,list(r.get('pdf_boxes',[])),list(r.get('rel_boxes',[])),r.get('location_note','')))
            elif r.get('record_role')=='vfd' and r.get('rel_boxes') and r.get('location_quality') in ('中','高'):
                r['evidence_type']='verified_symbol'
                r['location_quality']='符号实测'
                r['location_note']='已OCR确认VFD字样的实际图形边框'
                preserved.append((r,list(r.get('pdf_boxes',[])),list(r['rel_boxes']),r['location_note']))
        locate_observed_printed_labels(corrected,rows,turns,unrotate_box)
        for row,actual,relative,note in preserved:
            if actual:row['pdf_boxes']=actual
            if relative:row['rel_boxes']=relative
            row['location_quality']='符号实测'
            row['location_note']=note
        for r in rows:
            normalize_recognition_row(r)
            r['region_id']=id
            if r.get('pdf_boxes'):
                continue
            if r.get('rel_boxes'):
                boxes=[]
                for x0,y0,x1,y1 in r['rel_boxes']:
                    boxes.append([round(clip.x0+x0*clip.width,2),round(clip.y0+y0*clip.height,2),round(clip.x0+x1*clip.width,2),round(clip.y0+y1*clip.height,2)])
                r['pdf_boxes']=boxes
            # No placeholder coordinates: missing evidence means NO box.
        # Validate measured boxes against actual pixels before exposing them.
        # A no-ink crop is not localization, even if coordinates are inside PDF.
        import numpy as np
        for r in rows:
            valid=[]
            for coords in r.get('pdf_boxes',[]):
                bb=fitz.Rect(coords)&p.rect
                if bb.width<=1 or bb.height<=1:continue
                try:
                    px=p.get_pixmap(matrix=fitz.Matrix(2,2),clip=bb,alpha=False)
                    values=np.frombuffer(px.samples,dtype=np.uint8).reshape(px.height,px.width,px.n)
                    ink=(values[:,:,:3].max(axis=2)<175).mean()
                    if ink>=.006:valid.append(coords)
                except Exception:continue
            if valid:
                r['pdf_boxes']=valid
            else:
                r.pop('pdf_boxes',None)
                r.pop('rel_boxes',None)
                r['location_quality']='未定位'
                r['location_note']='位置证据无法在PDF原图验证；未绘制估算框'
        # Keep warnings and completeness diagnostics visible to the UI. The
        # old whitelist dropped unreadable tags and unexplained missing rows.
        data={'region_id':id,'rows':rows,'diag':{k:v for k,v in diag.items() if k!='raw'},'cached':False}
        os.makedirs(cache_dir,exist_ok=True)
        tmp=cp+'.tmp'+str(os.getpid())
        with open(tmp,'w',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False)
        os.replace(tmp,cp)
        return bind_region(data,region)
    finally:doc.close()
