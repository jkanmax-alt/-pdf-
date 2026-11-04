"""Rotation-safe coordinates and inexpensive electrical drawing orientation check.

Rotation is about the individual segmented panel. The stored normalized box is
always converted back into the *unrotated* original PDF clip coordinates.
"""
from PIL import Image
import re

def rotate(img, k):
    return img.rotate(90*(k%4),expand=True) if k else img

def unrotate_box(box,k):
    """A normalized rectangle in CCW-rotated image -> original normalized image."""
    x0,y0,x1,y1=box
    def point(x,y):
        k0=k%4
        return [(x,y),(1-y,x),(1-x,1-y),(y,1-x)][k0]
    xy=[point(x,y) for x,y in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
    return [round(max(0,min(1,min(q[0] for q in xy))),5),round(max(0,min(1,min(q[1] for q in xy))),5),
            round(max(0,min(1,max(q[0] for q in xy))),5),round(max(0,min(1,max(q[1] for q in xy))),5)]

def score_header(text):
    t=text.upper().replace(' ','')
    s=0
    for token,v in [('PANELNO',9),('CABLENO',8),('INCOMING',6),('OUTGOING',6),('EQT.NAME',2),('CAPACITY',2),('MCCB',3),('MCB',2),('RCBO',2),('DSL',3)]:
        if token in t:s+=v
    if re.search(r'\d[-]?\d?[-]?(?:PP|AP|AL|ACP|KT|VFD)\d+',t):s+=7
    return s

def detect_rotation(img,override='自动'):
    """0/90/180/270 degrees CCW to restore readable panel orientation.

    Scoring is based on actual title text and avoids OCRing the entire page.
    Low scores are explicitly marked uncertain; operator override is supported.
    """
    if override not in (None,'自动','auto',''):
        try:k=(int(override)//90)%4;return k,{'rotation':k*90,'reason':'人工指定','confidence':'人工'}
        except (ValueError,TypeError):pass
    import pytesseract
    from PIL import ImageOps
    ranked=[]
    for k in range(4):
        test=rotate(img,k)
        w,h=test.size
        # Title is normally near upper-left in both sample drawing families.
        clip=test.crop((max(0,int(w*.02)),max(0,int(h*.02)),max(1,int(w*.63)),max(1,int(h*.24))))
        if clip.width>1300:clip.thumbnail((1300,400))
        s=pytesseract.image_to_string(ImageOps.grayscale(clip),lang='eng',config='--psm 6')
        ranked.append((score_header(s),k,s[:160]))
        # Strong, unambiguous title evidence permits early exit and saves 3 OCR calls.
        if k==0 and ranked[-1][0]>=17:
            return 0,{'rotation':0,'confidence':'高','reason':'原始方向的标题栏识别充分','scores':[(ranked[-1][0],0)]}
    # A blank/unreadable title must not choose k=3 just because it sorts last.
    ranked.sort(key=lambda entry: (-entry[0], entry[1]))
    score,k,_=ranked[0]
    if not score or ranked[1][0]==score:
        return 0,{'rotation':0,'confidence':'低',
                  'reason':'方向证据不足，保留原方向' if not score else '多个方向得分相同，保留原方向待人工确认',
                  'scores':[(x[0],x[1]*90) for x in ranked]}
    return k,{'rotation':k*90,'confidence':'中' if score>=8 and (len(ranked)<2 or score-ranked[1][0]>=3) else '低',
              'reason':'标题文字方向交叉检测' if score else '方向证据不足，默认原方向','scores':[(x[0],x[1]*90) for x in ranked]}
