"""Pure multiprocessing worker. Never imports Tk, safe for Windows spawn."""
import os, json, hashlib
import fitz
from PIL import Image


def run_one(args):
    path,region,cache_dir=args
    os.environ['OMP_THREAD_LIMIT']='1'
    os.environ['OPENBLAS_NUM_THREADS']='1'
    from core import recognize_cabinet_image, normalize_recognition_row
    id=region['id'];page=region['page'];box=region['box']
    stat=os.stat(path)
    key=hashlib.sha256(json.dumps([path,stat.st_size,stat.st_mtime_ns,page,box,'v153-incoming-compact-segmentation-v3'],ensure_ascii=False).encode()).hexdigest()
    cp=os.path.join(cache_dir,key+'.json')
    if os.path.isfile(cp):
        try:
            with open(cp,encoding='utf8') as f:data=json.load(f)
            data['cached']=True
            return data
        except Exception:pass
    doc=fitz.open(path)
    try:
        p=doc[page-1];clip=fitz.Rect(box)&p.rect
        pix=p.get_pixmap(matrix=fitz.Matrix(3.0,3.0),clip=clip,alpha=False)
        img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        rows,diag=recognize_cabinet_image(img,page,source='V1.5分柜识别')
        from incoming_v153 import recognize_incoming,merge_incoming
        from compact_v153 import recognize_compact
        if diag.get('mode')=='fallback':
            compact,compact_diag=recognize_compact(img,page,'V1.5.3短回路专用识别')
            if compact:
                rows,diag=compact,compact_diag
        upstream=recognize_incoming(img,page,cabinet=diag.get('cabinet','待确认柜号'))
        rows=merge_incoming(rows,upstream)
        # Motor/VFD panels need a branch-specific pass. Only add physically
        # observed VFD glyphs; direct-start is never guessed from an FM load.
        from motor_v153 import recognize_vfd_candidates
        cabinet_hint=region.get('cabinet') or diag.get('cabinet','')
        for candidate in recognize_vfd_candidates(img,page,cabinet_hint):
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
            target['location_quality']='高'
            target['location_note']='PDF原生PM文字+仪表图框'
        # SPD label near the surge branch is often implicit in a technical line.
        # Do not hallucinate it: use actual OCR evidence and keep unconfirmed.
        if any(r['kind']=='浪涌后备保护器' for r in rows) and not any(r['kind']=='浪涌保护器' for r in rows):
            import pytesseract
            from ocr_runtime import initialize_ocr
            initialize_ocr()
            sample=img.crop((int(img.width*.24),int(img.height*.81),int(img.width*.63),int(img.height*.96)))
            raw=pytesseract.image_to_string(sample.resize((sample.width*2,sample.height*2)),lang='eng',config='--psm 6')
            if __import__('re').search(r'8\s*/\s*20|Imax\s*=|SPD',raw,__import__('re').I):
                rows.append({'cabinet':diag.get('cabinet','待确认柜号'),'page':page,'kind':'浪涌保护器',
                             'spec':'待确认','qty':1,'tag':'','source':'V1.5分柜识别','raw':raw[:250],
                             'status':'待核对','remark':'浪涌支路OCR证据候选，待人工核对',
                             'rel_boxes':[[.345,.865,.57,.94]],'location_quality':'估计','location_note':'浪涌文字参数附近'})
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
            elif 'pdf_rel_y' in r:
                y=clip.y0+float(r['pdf_rel_y'])*clip.height;x=clip.x0+float(r.get('pdf_rel_x',.29))*clip.width
                r['pdf_boxes']=[[round(x-20,2),round(y-10,2),round(x+70,2),round(y+10,2)]]
        data={'region_id':id,'rows':rows,'diag':{'mode':diag.get('mode',''), 'feeders':diag.get('feeders',0),'reason':diag.get('reason',''), 'cabinet':diag.get('cabinet','')},'cached':False}
        os.makedirs(cache_dir,exist_ok=True)
        tmp=cp+'.tmp'+str(os.getpid())
        with open(tmp,'w',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False)
        os.replace(tmp,cp)
        return data
    finally:doc.close()
