"""Feeder geometry and literal tag recognition, V1.5.2.

IMPORTANT: A detected row is never assigned a fabricated W1/W2/... tag.
An unreadable position is retained as tag='', with its geometric source y.
"""
from collections import Counter
import re
import numpy as np
from PIL import ImageOps


def _centers(mask, max_gap, max_group):
    inds=np.flatnonzero(mask)
    groups=[]
    for k in inds:
        k=int(k)
        if not groups or k-groups[-1][-1]>max_gap:groups.append([k])
        else:groups[-1].append(k)
    return [int(round(sum(g)/len(g))) for g in groups if len(g)<=max_group]


def detect_feeder_lines(image):
    """Find all supported regular groups of observed horizontal conductors.

    No hard-coded page top/bottom fractions: W1 may start above 11% and W20
    may end below 85%. A changed pitch starts another group, rather than dropping
    that group's devices. Isolated borders/SPD lines are not promoted to feeders.
    """
    gray=np.asarray(ImageOps.grayscale(image))
    h,w=gray.shape
    # Outer/table-frame rules traverse almost the entire clip. They must not
    # supply the third point that makes an isolated SPD look like a new group.
    frame_rows=(gray<160).mean(axis=1)>.94
    proposals=[]
    for x0,x1 in ((.57,.68),(.51,.62),(.35,.52)):
        density=(gray[:,int(w*x0):int(w*x1)]<160).mean(axis=1)
        pts=_centers(density>.71,max(2,int(h*.0015)),max(12,int(h*.009)))
        pts=[y for y in pts if not frame_rows[y]]
        if len(pts)<4:continue
        differences=np.diff(pts)
        plausible=[int(d) for d in differences if h*.012<d<h*.13]
        if not plausible:continue
        groups=[]
        # Three conductors (two matching spacings) distinguish a series from
        # an isolated frame edge or SPD branch; no single row is invented.
        for mode,_ in Counter(round(d/5)*5 for d in plausible).most_common():
            current=[]
            for a,b in zip(pts,pts[1:]):
                if abs((b-a)-mode)<=max(7,mode*.20):
                    if not current:current=[a]
                    current.append(b)
                else:
                    if len(current)>=3:groups.append(current)
                    current=[]
            if len(current)>=3:groups.append(current)
        groups.sort(key=lambda group:(-len(group),group[0]))
        selected=[];covered=set()
        for group in groups:
            remaining=[y for y in group if y not in covered]
            if not remaining:continue
            selected.append({'lines':remaining,'pitch':float(np.median(np.diff(group)))})
            covered.update(remaining)
        chosen=sorted(covered)
        if len(chosen)>=4:
            selected.sort(key=lambda group:group['lines'][0])
            proposals.append((len(chosen),chosen,selected,pts))
    if not proposals:return [],{'reason':'没有检测到稳定的横向馈线序列'}
    _,chosen,groups,pts=max(proposals,key=lambda item:item[0])
    spacings=[group['pitch'] for group in groups for _ in group['lines']]
    pitch=float(np.median(spacings))
    warnings=[]
    if len(groups)>1:
        warnings.append(f'发现{len(groups)}组支路间距；已全部保留，请核对分组交界处。')
    unused=[y for y in pts if y not in chosen]
    if unused:warnings.append(f'另有{len(unused)}条孤立横线未作为支路计数，可能是进线或防雷支路，请人工核对。')
    return chosen,{'pitch':pitch,'line_count':len(chosen),'mode_pitch':round(pitch/5)*5,
                   'groups':groups,
                   'warnings':warnings,'unassigned_lines':unused}


def find_tag_column(image, lines):
    """Locate the right-hand position-column's two printed vertical dividers."""
    g=np.asarray(ImageOps.grayscale(image));h,w=g.shape
    if len(lines)<2:return None
    pitch=float(np.median(np.diff(lines)))
    ya=max(0,int(lines[0]+pitch*.1));yb=min(h,int(lines[-1]-pitch*.1))
    density=(g[ya:yb]<210).mean(axis=0)
    groups=[]
    for x in range(int(w*.64),int(w*.88)):
        if density[x]>.60:
            if not groups or x-groups[-1][-1]>4:groups.append([x])
            else:groups[-1].append(x)
    found=[int(round(sum(group)/len(group))) for group in groups]
    pairs=[(a,b) for a,b in zip(found,found[1:]) if .035*w<b-a<.095*w]
    if not pairs:return None
    return max(pairs,key=lambda ab: density[ab[0]]+density[ab[1]])


def read_drawn_tags(image,lines,groups=None):
    """Read only printed W tags, bound to measured physical feeder rows.

    No row-number fabrication. OCR predictions must be complete W+digits.
    Duplicate predictions are blanked rather than falsely moved to a neighbor.
    """
    import pytesseract
    from PIL import ImageEnhance,ImageOps
    tags=['']*len(lines);warnings=[]
    col=find_tag_column(image,lines)
    if not col:return tags,['未找到完整位号列：请检查单柜分割框右边界是否截掉回路编号表。']
    a,b=col;w,h=image.size
    default_pitch=float(np.median(np.diff(lines))) if len(lines)>1 else h*.05
    row_pitches={y:float(group['pitch']) for group in (groups or []) for y in group['lines']}
    def read(crop,scale):
        if crop.width<8 or crop.height<5:return ''
        c=crop.resize((crop.width*scale,crop.height*scale))
        t=pytesseract.image_to_string(c,lang='eng',config='--psm 7 -c tessedit_char_whitelist=W0123456789').strip().upper()
        # Owing to rotated labels W is sometimes read VV; reject rather than guess.
        return t.replace(' ','').replace('\n','')
    for idx,y in enumerate(lines):
        pitch=row_pitches.get(y,default_pitch)
        # First cut excludes vertical grid dividers, which confuse W14/W18.
        cut=image.crop((max(0,a+7),max(0,int(y-pitch*.82)),min(w,b-8),min(h,int(y-pitch*.08))))
        primary=read(cut,2)
        if not re.fullmatch(r'W[1-9]\d{0,2}',primary):
            # A secondary independent crop captures narrow W9/W14 characters.
            extra=image.crop((max(0,a),max(0,int(y-pitch*.90)),min(w,b),min(h,int(y-pitch*.05))))
            secondary=read(extra,3)
            primary=secondary if re.fullmatch(r'W[1-9]\d{0,2}',secondary) else ''
        tags[idx]=primary
        if not primary:warnings.append(f'物理第{idx+1}条支路：未取得完整W编号，保留空白')
    duplicates={v for v,n in Counter(t for t in tags if t).items() if n>1}
    for i,x in enumerate(tags):
        if x in duplicates:
            tags[i]=''
            warnings.append(f'位号{x}在多条支路重复识别；相关位号留空，禁止按位置顺序补号')
    return tags,warnings
