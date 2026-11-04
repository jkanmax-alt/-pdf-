"""ElectricalQuote V1.7: panel segmentation + parallel cabinet OCR + human review."""
import os, sys, json, copy, queue, threading, concurrent.futures, multiprocessing, re, hashlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import fitz
from PIL import Image,ImageTk
from app import Main as PreviousMain
from segmentation_v16 import detect_document
from worker_v16 import run_one
from core import aggregate,save_csv,save_xlsx,quote_preview,TYPES,normalize_recognition_row

BASE=Path(__file__).resolve().parent
CACHE=BASE/'cache'
SOURCES=('V1.5分柜识别',)

class Main(PreviousMain):
 def __init__(self,root):
  self.regions=[];self.active_region=None;self.events=queue.Queue();self.cancel_flag=threading.Event();self.busy=False;self.pool=None
  self.frame_edit=tk.BooleanVar(value=False);self.frame_drag=None;self.mark_row_idx=None
  self.missing_pdf_path='';self.project_pdf_sha256=''
  super().__init__(root)
  self.root.after(120,self.poll_events)
  self.root.after(350,self.initial_sash_width)

 def build(self):
  self.root.title('电气图纸识别 V1.7.1 · 图框/位号与防雷支路识别');self.root.geometry('1580x940');self.root.minsize(1150,690)
  style=ttk.Style();style.theme_use('clam');style.configure('Treeview',rowheight=27,font=('Microsoft YaHei UI',10));style.configure('TButton',font=('Microsoft YaHei UI',10))
  header=tk.Frame(self.root,bg='#17324d');header.pack(side='top',fill='x')
  tk.Label(header,text='⚡ 电气图纸智能识别  V1.7.1',bg='#17324d',fg='white',font=('Microsoft YaHei UI',16,'bold')).pack(side='left',padx=16,pady=11)
  for text,fn in [('打开PDF',self.open_pdf),('关联原PDF',self.reattach_pdf),('打开项目',self.open_project),('保存项目',self.save_project),('导出Excel',self.export_xlsx),('导出CSV',self.export_csv)]:
   tk.Button(header,text=text,command=fn,bg='#eaf1f9',relief='flat',padx=10,pady=7).pack(side='left',padx=4)
  self.tabs=ttk.Panedwindow(self.root,orient='horizontal');self.tabs.pack(fill='both',expand=True,padx=6,pady=6)
  side=ttk.Frame(self.tabs,width=230);mid=ttk.Frame(self.tabs);right=ttk.Frame(self.tabs)
  self.tabs.add(side,weight=3);self.tabs.add(mid,weight=5);self.tabs.add(right,weight=6)
  ttk.Label(side,text='单柜区域目录',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=6,pady=6)
  ttk.Button(side,text='① 检测整份PDF分柜',command=self.detect_regions).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='② 并行识别全部柜子',command=self.start_batch).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='识别当前选中柜子',command=self.recognize_selected).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='取消未开始的任务',command=self.cancel_batch).pack(fill='x',padx=5,pady=2)
  scope=ttk.Frame(side);scope.pack(fill='x',padx=5,pady=(5,1))
  ttk.Button(scope,text='参与 / 跳过当前柜',command=self.toggle_included).pack(side='left',padx=1)
  self.rot_choice=tk.StringVar(value='自动')
  ttk.Combobox(scope,textvariable=self.rot_choice,values=['自动','0','90','180','270'],width=5,state='readonly').pack(side='left',padx=3)
  ttk.Button(scope,text='设方向',command=self.set_rotation).pack(side='left')
  self.regionlist=tk.Listbox(side,exportselection=False,font=('Microsoft YaHei UI',10),selectmode='browse',width=26);self.regionlist.pack(fill='both',expand=True,padx=5,pady=(10,3))
  self.regionlist.bind('<<ListboxSelect>>',self.select_region)
  tweak=ttk.Frame(side);tweak.pack(fill='x',padx=4)
  ttk.Button(tweak,text='框选新增',command=self.add_region).pack(side='left',padx=2)
  ttk.Button(tweak,text='框选替换',command=self.replace_region).pack(side='left',padx=2)
  ttk.Button(tweak,text='删除',command=self.delete_region).pack(side='left',padx=2)
  ttk.Checkbutton(side,text='编辑分柜框（拖动边框/四角调整）',variable=self.frame_edit,command=self.on_toggle_frame_edit).pack(anchor='w',padx=5,pady=4)
  self.progress=ttk.Progressbar(side,maximum=100);self.progress.pack(fill='x',padx=6,pady=(12,4))
  self.progress_label=ttk.Label(side,text='未开始',foreground='#506980',wraplength=270);self.progress_label.pack(fill='x',padx=7,pady=(0,10))
  nav=ttk.Frame(mid);nav.pack(fill='x',pady=4)
  ttk.Button(nav,text='◀',width=3,command=lambda:self.go(-1)).pack(side='left')
  self.page_label=ttk.Label(nav,text='未打开PDF');self.page_label.pack(side='left',padx=8)
  ttk.Button(nav,text='▶',width=3,command=lambda:self.go(1)).pack(side='left')
  self.zoom=tk.DoubleVar(value=.75)
  ttk.Label(nav,text='缩放').pack(side='left',padx=(8,2))
  ttk.Combobox(nav,textvariable=self.zoom,values=[.5,.75,1,1.3,1.6,2,3],width=5,state='readonly').pack(side='left')
  self.zoom.trace_add('write',lambda *_:self.show_pdf())
  panel=ttk.Frame(mid);panel.pack(fill='both',expand=True)
  self.canvas=tk.Canvas(panel,bg='#b9c3cd',cursor='crosshair')
  sbv=ttk.Scrollbar(panel,orient='vertical',command=self.canvas.yview);sbh=ttk.Scrollbar(panel,orient='horizontal',command=self.canvas.xview)
  self.canvas.configure(yscrollcommand=sbv.set,xscrollcommand=sbh.set)
  sbv.pack(side='right',fill='y');sbh.pack(side='bottom',fill='x');self.canvas.pack(side='left',fill='both',expand=True)
  self.canvas.bind('<ButtonPress-1>',self.down);self.canvas.bind('<B1-Motion>',self.move);self.canvas.bind('<ButtonRelease-1>',self.up)
  ttk.Label(right,text='当前柜号').pack(anchor='w')
  self.cabinetfield=ttk.Frame(right);self.cabinetfield.pack(fill='x',pady=3)
  ttk.Entry(self.cabinetfield,textvariable=self.current_cabinet,width=19).pack(side='left')
  ttk.Button(self.cabinetfield,text='修改柜号/中文名称',command=self.rename_region).pack(side='left',padx=6)
  ttk.Label(right,text='图纸元器件清单 · 单击定位 / 双击修改',foreground='#506980').pack(anchor='w',pady=(12,4))
  self.keys=['cabinet','page','kind','spec','qty','tag','status']
  box=ttk.Frame(right);box.pack(fill='both',expand=True)
  self.tree=ttk.Treeview(box,columns=self.keys,show='headings',selectmode='browse')
  labels=['柜号','页','类别','图纸型号/参数','数量','位号','状态'];sizes=[80,36,115,180,44,60,65]
  for key,title,width in zip(self.keys,labels,sizes):self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=30,stretch=key in ('kind','spec'))
  self.tree.pack(side='left',fill='both',expand=True);sc=ttk.Scrollbar(box,orient='vertical',command=self.tree.yview);sc.pack(side='right',fill='y');self.tree.configure(yscrollcommand=sc.set)
  self.tree.bind('<<TreeviewSelect>>',lambda e:self.focus_selected());self.tree.bind('<Double-1>',lambda e:self.edit())
  buttons=ttk.Frame(right);buttons.pack(fill='x',pady=8)
  for t,fn in [('新增',self.add),('修改',self.edit),('删除',self.delete),('分类汇总',self.show_summary),('证据预览',self.show_selected_evidence),('定位元件',self.mark_selected_device),('识别质量',self.show_quality)]:
   ttk.Button(buttons,text=t,command=fn).pack(side='left',padx=2)
  ttk.Label(right,text='高级诊断：OCR原文默认隐藏，必要时可查看单柜质量报告',foreground='#788896').pack(anchor='w')
  rules=ttk.LabelFrame(right,text='报价规则预览（与识别清单完全分离）');rules.pack(fill='x',pady=(8,2))
  opts=ttk.Frame(rules);opts.pack(fill='x',padx=8,pady=4)
  self.type=tk.StringVar(value='柜');self.direct=tk.IntVar(value=0);self.vfd=tk.IntVar(value=0)
  self.fire=tk.BooleanVar(value=False);self.dual=tk.BooleanVar(value=False);self.lamp=tk.BooleanVar(value=True)
  ttk.Label(opts,text='类别').pack(side='left');ttk.Combobox(opts,textvariable=self.type,values=['柜','箱'],width=4,state='readonly').pack(side='left')
  for label,var in [('直启',self.direct),('变频',self.vfd)]:ttk.Label(opts,text=label).pack(side='left',padx=(8,1));tk.Spinbox(opts,textvariable=var,from_=0,to=100,width=3).pack(side='left')
  ttk.Checkbutton(opts,text='消防',variable=self.fire).pack(side='left');ttk.Checkbutton(opts,text='双电源',variable=self.dual).pack(side='left');ttk.Checkbutton(opts,text='三相灯',variable=self.lamp).pack(side='left')
  ttk.Button(rules,text='计算建议',command=self.preview).pack(anchor='w',padx=8)
  self.rule_text=tk.Text(rules,height=4,wrap='word',bg='#f2f6fa',font=('Microsoft YaHei UI',9));self.rule_text.pack(fill='x',padx=8,pady=6)
  self.preview();self.status=ttk.Label(self.root,text='请打开整份PDF → 检测分柜 → 检查分割框 → 并行识别。',foreground='#33536e');self.status.pack(side='bottom',fill='x',padx=10,pady=4)


 def on_toggle_frame_edit(self):
  self.mark_row_idx=None;self.canvas.configure(cursor='fleur' if self.frame_edit.get() else 'crosshair')
  self.paint_regions()
  self.note('编辑分柜框已开启：拖动框内移动，拖动四角或边缘缩放；完成后仅重识别修改的柜子。' if self.frame_edit.get() else '已退出分柜框编辑模式。')

 def mark_selected_device(self):
  if self.doc is None:return messagebox.showinfo('原图未关联','请先关联项目原PDF，再标定元器件位置。')
  idx=self.selected()
  if idx is None:return messagebox.showinfo('提示','请先选中一条元器件记录')
  if self.busy:return messagebox.showwarning('任务进行中','请先完成识别再标定')
  target=self.rows[idx]
  self.frame_edit.set(False);self.mark_row_idx=idx;self.page=int(target.get('page',1))-1
  self.show_pdf()
  self.note('请在原图上准确框选该元器件符号（不要框空白或整条回路）；松开鼠标后保存人工定位。')

 def _hit_frame(self,x,y):
  z=float(self.zoom.get());tol=max(8,10/z)
  candidates=[]
  for r in self.regions:
   if r['page']!=self.page+1:continue
   l,t,rr,b=r['box'];px=x/z;py=y/z
   if not(l-tol<=px<=rr+tol and t-tol<=py<=b+tol):continue
   edges={'w':abs(px-l)<tol,'e':abs(px-rr)<tol,'n':abs(py-t)<tol,'s':abs(py-b)<tol}
   sides=''.join(k for k in ('n','s','w','e') if edges[k])
   mode=sides or ('move' if l<=px<=rr and t<=py<=b else None)
   if mode:candidates.append((r['id']!=self.active_region,(rr-l)*(b-t),r,mode))
  if not candidates:return None,None
  candidates.sort(key=lambda a:(a[0],a[1]));return candidates[0][2],candidates[0][3]

 def down(self,e):
  if self.busy:return
  if self.frame_edit.get():
   x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
   r,mode=self._hit_frame(x,y)
   if r is None:return
   self.active_region=r['id'];self.frame_drag={'id':r['id'],'start':(x,y),'original':list(r['box']),'mode':mode}
   self.render_regions();self.paint_regions();return
  return super().down(e)

 def move(self,e):
  if self.frame_edit.get():
   d=self.frame_drag
   if not d:return
   r=next((r for r in self.regions if r['id']==d['id']),None)
   if not r:return
   z=float(self.zoom.get());dx=(self.canvas.canvasx(e.x)-d['start'][0])/z;dy=(self.canvas.canvasy(e.y)-d['start'][1])/z
   l,t,rr,b=d['original'];mode=d['mode']
   if mode=='move':l+=dx;rr+=dx;t+=dy;b+=dy
   else:
    if 'w' in mode:l+=dx
    if 'e' in mode:rr+=dx
    if 'n' in mode:t+=dy
    if 's' in mode:b+=dy
   bounds=self.doc[self.page].rect
   if mode=='move':
    w,h=rr-l,b-t;l=max(bounds.x0,min(bounds.x1-w,l));t=max(bounds.y0,min(bounds.y1-h,t));rr=l+w;b=t+h
   else:
    l=max(bounds.x0,min(bounds.x1,l));rr=max(bounds.x0,min(bounds.x1,rr))
    t=max(bounds.y0,min(bounds.y1,t));b=max(bounds.y0,min(bounds.y1,b))
   if rr-l<38 or b-t<38:return
   r['box']=[l,t,rr,b];self.paint_regions();return
  return super().move(e)

 def up(self,e):
  if self.frame_edit.get():
   d=self.frame_drag;self.frame_drag=None
   if not d:return
   r=next((r for r in self.regions if r['id']==d['id']),None)
   if not r:return
   prev=d['original'];now=r['box']
   if max(abs(x-y) for x,y in zip(prev,now))<1:return
   has_records=any(x.get('region_id')==r['id'] for x in self.rows)
   if has_records and not messagebox.askyesno('修改分柜范围','分柜边界已变更。需要清除该柜旧识别结果后重新识别。是否保存新边界？'):
    r['box']=prev;self.paint_regions();return
   r['box']=[round(v,2) for v in now]
   self.rows=[x for x in self.rows if x.get('region_id')!=r['id']]
   r.update(state='未识别',count=0,manual_box=True)
   self.refresh();self.render_regions();self.paint_regions()
   self.note(f'{r["cabinet"]}边界已人工修正；请点击「识别当前选中柜子」，不会重算其他柜。')
   return
  result=super().up(e)
  if self.mark_row_idx is None:return result
  idx=self.mark_row_idx;self.mark_row_idx=None
  if self.ocr_rect is None:return result
  z=float(self.zoom.get());a,b,c,d=self.ocr_rect;self.ocr_rect=None
  if min(c-a,d-b)<6:return messagebox.showwarning('区域太小','请沿着实际元器件符号拖动更大的框')
  pg=self.doc[self.page];rect=fitz.Rect(a/z,b/z,c/z,d/z)&pg.rect
  if rect.width<=0 or rect.height<=0:return
  r=self.rows[idx];r['pdf_boxes']=[[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]]
  r['page']=self.page+1;r['location_quality']='人工标定';r['evidence_type']='verified_symbol'
  r['location_note']='操作者在PDF原图上框定的元器件实际符号位置'
  r['status']='待核对';r['manual_modified']=True
  self.canvas.delete('region');self.refresh();self.tree.selection_set(str(idx));self.focus_selected()
  self.note('实际元器件位置已绑定。该坐标已保存到本次清单；请保存项目以持久保留。')
  return result

 def initial_sash_width(self):
  """Keep cabinet labels and action buttons readable at first launch."""
  try:
   target=min(255,max(210,int(self.root.winfo_width()*.16)))
   self.tabs.sashpos(0,target)
  except Exception:
   pass
 def note(self,message):self.status.configure(text=message)
 def editing_allowed(self):
  if self.busy:
   messagebox.showwarning('识别进行中','请先取消或等待当前识别任务，再修改清单或项目。')
   return False
  return True

 @staticmethod
 def pdf_digest(path):
  digest=hashlib.sha256()
  with open(path,'rb') as stream:
   for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
  return digest.hexdigest()

 def detach_pdf(self):
  if self.doc is not None:self.doc.close()
  self.doc=None;self.pdf_path='';self.page=0;self.image=None;self.ocr_rect=None
  self.canvas.delete('all');self.page_label.configure(text='原图未关联')

 def open_pdf(self):
  if not self.editing_allowed():return
  if self.missing_pdf_path:return self.reattach_pdf()
  p=filedialog.askopenfilename(filetypes=[('PDF文件','*.pdf')])
  if not p:return
  if self.rows and not messagebox.askyesno('打开新PDF','打开新图纸会清除当前清单与分柜框。请先保存项目。继续吗？'):return
  self.load_pdf(p)

 def reattach_pdf(self):
  """Rebind a moved project PDF without replacing its reviewed records."""
  if not self.editing_allowed():return
  if not (self.regions or self.rows):
   return messagebox.showinfo('提示','请先打开需要恢复原图的项目；新图纸请使用「打开PDF」。')
  path=filedialog.askopenfilename(title='选择项目原PDF（保留清单与分柜框）',filetypes=[('PDF文件','*.pdf')])
  if path:self.load_pdf(path,preserve_project=True)

 def load_pdf(self,path,preserve_project=False):
  if not self.editing_allowed():return False
  candidate=None
  try:
   # Validate the replacement before closing an existing usable document.
   candidate=fitz.open(path)
   if candidate.needs_pass or len(candidate)<1:raise ValueError('PDF已加密或没有可读取页面。')
   digest=self.pdf_digest(path)
   if preserve_project:
    expected=getattr(self,'project_pdf_sha256','')
    if expected and expected!=digest:raise ValueError('所选PDF与项目保存的原图不同，请选择原文件。')
    for r in self.regions:
     page=int(r['page'])
     if not 1<=page<=len(candidate):raise ValueError('所选PDF页数与项目分柜数据不匹配。')
     rect=fitz.Rect(r['box']);bounds=candidate[page-1].rect
     if rect.is_empty or rect.x0<bounds.x0-1 or rect.y0<bounds.y0-1 or rect.x1>bounds.x1+1 or rect.y1>bounds.y1+1:
      raise ValueError('所选PDF页面尺寸与项目分柜坐标不匹配。')
   if self.doc is not None:self.doc.close()
   self.doc=candidate;candidate=None;self.pdf_path=str(path);self.page=0
   self.project_pdf_sha256=digest;self.missing_pdf_path=''
   if not preserve_project:self.regions=[];self.active_region=None;self.rows=[]
   self.refresh();self.render_regions();self.show_pdf()
   self.note(('原PDF已重新关联，清单与分柜框保持不变。' if preserve_project else f'已打开 {Path(path).name}（{len(self.doc)}页），请先检测分柜。'))
   return True
  except Exception as e:
   messagebox.showerror('打开PDF失败',str(e));return False
  finally:
   if candidate is not None:candidate.close()
 def show_pdf(self):
  if self.doc is None:return
  try:
   p=self.doc[self.page];z=float(self.zoom.get());pix=p.get_pixmap(matrix=fitz.Matrix(z,z),alpha=False)
   im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);self.image=im;self.photo=ImageTk.PhotoImage(im)
   self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.photo)
   self.canvas.configure(scrollregion=(0,0,im.width,im.height));self.page_label.configure(text=f'第{self.page+1}/{len(self.doc)}页');self.ocr_rect=None
   self.paint_regions()
  except Exception as e:self.note('渲染失败：'+str(e))
 def paint_regions(self):
  self.canvas.delete('cabinet_frames')
  if self.doc is None:return
  z=float(self.zoom.get())
  for r in self.regions:
   if r['page']!=self.page+1:continue
   x0,y0,x1,y1=(v*z for v in r['box']);color='#16a34a' if r['state']=='已识别' else '#e0a11a'
   if r['id']==self.active_region:color='#e3342f'
   if not r.get('included',True):color='#8b949e'
   self.canvas.create_rectangle(x0,y0,x1,y1,outline=color,width=3,tags='cabinet_frames')
   self.canvas.create_text(x0+5,y0+5,text=r.get('cabinet','待确认柜号'),anchor='nw',font=('Microsoft YaHei UI',9,'bold'),fill=color,tags='cabinet_frames')
   if self.frame_edit.get() and r['id']==self.active_region:
    for hx,hy in ((x0,y0),(x1,y0),(x0,y1),(x1,y1),((x0+x1)/2,y0),((x0+x1)/2,y1),(x0,(y0+y1)/2),(x1,(y0+y1)/2)):
     self.canvas.create_rectangle(hx-5,hy-5,hx+5,hy+5,fill='white',outline='#e3342f',width=2,tags='cabinet_frames')
 def go(self,n):
  if self.doc is not None and 0<=self.page+n<len(self.doc):self.page+=n;self.show_pdf()
 def detect_regions(self):
  if not self.pdf_path:return messagebox.showinfo('提示','请先打开PDF')
  if self.busy:return
  if self.rows and not messagebox.askyesno('检测分柜','重新检测会清除当前识别清单，建议先保存项目。继续吗？'):return
  self.rows=[];self.refresh();self.note('正在检测单柜图框...');self.root.update_idletasks()
  try:
   self.regions=detect_document(self.pdf_path)
   self.active_region=self.regions[0]['id'] if self.regions else None
   self.render_regions();self.show_pdf();named=sum(x.get('cabinet') not in ('','待确认柜号') for x in self.regions);self.note(f'检测到{len(self.regions)}个候选单柜区域，已初步读取{named}个柜号，另外{len(self.regions)-named}个需手动确认；识别结果和分割框均需复核。')
  except Exception as e:messagebox.showerror('分柜失败',str(e))
 def render_regions(self):
  self.regionlist.delete(0,'end')
  for r in self.regions:
   # Use the real cabinet label first; the internal p1_r1 identifier is only
   # a database key, not something the operator needs to read.
   label=r.get('cabinet','待确认柜号')
   marker='●' if r.get('included',True) else '－'
   self.regionlist.insert('end',f"{marker} {label} | 第{r['page']}页 | {r['state']} ({r['count']})")
  idx=next((i for i,r in enumerate(self.regions) if r['id']==self.active_region),None)
  if idx is not None:self.regionlist.selection_clear(0,'end');self.regionlist.selection_set(idx);self.regionlist.see(idx)
 def selected_region(self):
  ss=self.regionlist.curselection()
  if ss:return self.regions[ss[0]]
  return next((r for r in self.regions if r['id']==self.active_region),None)
 def select_region(self,e=None):
  r=self.selected_region()
  if not r:return
  self.active_region=r['id'];self.current_cabinet.set(r['cabinet']);self.rot_choice.set(str(r.get('rotation_override','自动')));self.page=r['page']-1;self.show_pdf();self.refresh();self.move_to_box(r['box'])
 def move_to_box(self,box):
  if self.doc is None or self.image is None:return
  z=float(self.zoom.get());x=(box[0]+box[2])/2*z;y=(box[1]+box[3])/2*z
  self.canvas.update_idletasks()
  iw=max(1,self.image.width);ih=max(1,self.image.height)
  self.canvas.xview_moveto(max(0,min(1,(x-self.canvas.winfo_width()*.48)/iw)))
  self.canvas.yview_moveto(max(0,min(1,(y-self.canvas.winfo_height()*.32)/ih)))
 def toggle_included(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if not r:return
  r['included']=not r.get('included',True)
  self.render_regions();self.paint_regions()
  self.note(f"{r.get('cabinet')}: {'将参与批量识别' if r['included'] else '已跳过批量识别（保留图纸和已有记录）'}")
 def set_rotation(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if not r:return
  angle=self.rot_choice.get()
  r['rotation_override']=angle
  self.note(f"{r.get('cabinet')}: 识别旋转角度设为 {angle}。重新识别后生效，已有人工确认数据不会自动覆盖。")
 def chosen_rectangle(self):
  if self.ocr_rect is None:messagebox.showinfo('框选提示','请在左侧图纸按住鼠标拖出红色选择框');return None
  z=float(self.zoom.get());a,b,c,d=self.ocr_rect
  rect=fitz.Rect(a/z,b/z,c/z,d/z)&self.doc[self.page].rect
  if rect.width<45 or rect.height<45:messagebox.showwarning('区域太小','请重新框选更完整的单柜区域');return None
  return [round(v,2) for v in (rect.x0,rect.y0,rect.x1,rect.y1)]
 def add_region(self):
  if not self.editing_allowed():return
  if not self.doc:return
  bb=self.chosen_rectangle()
  if bb is None:return
  i=1
  existing={r['id'] for r in self.regions}
  while f'p{self.page+1}_manual{i}' in existing:i+=1
  r={'id':f'p{self.page+1}_manual{i}','page':self.page+1,'box':bb,'cabinet':'待确认柜号','state':'未识别','count':0,'included':True,'rotation_override':'自动'}
  self.regions.append(r);self.active_region=r['id'];self.render_regions();self.paint_regions();self.note('已新增单柜区域；识别前可继续调整。')
 def replace_region(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if not r:return
  if r['page']!=self.page+1:return messagebox.showinfo('提示','请先切换到选中区域所在页面再框选')
  bb=self.chosen_rectangle()
  if bb is None:return
  if any(row.get('region_id')==r['id'] for row in self.rows) and not messagebox.askyesno('确认','更改区域边界会删除该柜的旧识别及人工核对结果。继续吗？'):return
  self.rows=[row for row in self.rows if row.get('region_id')!=r['id']]
  r.update(box=bb,state='未识别',count=0);self.refresh();self.render_regions();self.paint_regions()
 def delete_region(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if not r:return
  if not messagebox.askyesno('删除区域','同时删除该区域的识别结果？'):return
  self.regions.remove(r);self.rows=[x for x in self.rows if x.get('region_id')!=r['id']]
  self.active_region=self.regions[0]['id'] if self.regions else None
  self.refresh();self.render_regions();self.paint_regions()
 def rename_region(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if not r:return
  name=self.current_cabinet.get().strip()
  if not name:return
  old=r['cabinet'];r['cabinet']=name;r['manual_name']=True
  for x in self.rows:
   if x.get('region_id')==r['id']:x['cabinet']=name
  self.render_regions();self.refresh();self.paint_regions();self.note(f'柜号已更改：{old} → {name}')
 def refresh(self):
  self.tree.delete(*self.tree.get_children());self.canvas.delete('focus')
  chosen=self.active_region
  for i,r in enumerate(self.rows):
   if chosen and self.regions and r.get('region_id')!=chosen:continue
   self.tree.insert('','end',iid=str(i),values=[('待确认' if k=='qty' and r.get(k) is None else r.get(k,'')) for k in self.keys])
 def focus_selected(self):
  self.canvas.delete('focus')
  idx=self.selected()
  if idx is None or self.doc is None:return
  r=self.rows[idx];box=r.get('pdf_boxes',[])
  if not box:return self.note('未检测到该器件的实际位置，不绘制推算红框。可选中记录后点击「定位元件」人工框定。')
  page=int(r.get('page',1))-1
  if self.page!=page:self.page=page;self.show_pdf()
  z=float(self.zoom.get());b=box[0];x0,y0,x1,y1=(float(v)*z for v in b)
  is_symbol=r.get('evidence_type')=='verified_symbol'
  self.canvas.create_rectangle(x0,y0,x1,y1,outline='#e52424' if is_symbol else '#1675dd',width=3,tags='focus');self.move_to_box(b)
  self.note(f"原图定位：{'元器件实际符号' if is_symbol else '原图文字标注（非元件符号）'} | {r.get('location_quality','待核对')}；未验证的位置不会绘制猜测框。")
 def recognize_selected(self):
  r=self.selected_region()
  if not r:return messagebox.showinfo('提示','请先检测并选择单柜区域')
  self.start_tasks([r])
 def start_batch(self):
  if not self.regions:return messagebox.showinfo('提示','请先点击检测分柜')
  selected=[r for r in self.regions if r.get('included',True)]
  if not selected:return messagebox.showinfo('没有选中','请至少设置一台柜子参与识别')
  self.start_tasks(selected)
 def start_tasks(self,regions):
  if self.busy:return messagebox.showinfo('正在识别','请先完成或取消当前识别')
  if self.doc is None or not self.pdf_path or not Path(self.pdf_path).exists():return messagebox.showerror('缺少PDF','请先关联项目原PDF，再进行识别。')
  self.busy=True;self.cancel_flag.clear();self.progress['value']=0
  self.progress_label.config(text=f'识别0/{len(regions)}，可继续浏览页面')
  self.note('已开始后台识别：按柜自动判断横竖布局和旋转方向；每台独立处理。')
  thread=threading.Thread(target=self.batch_runner,args=(copy.deepcopy(regions),),daemon=True);thread.start()
 def batch_runner(self,regions):
  total=len(regions);done=0
  try:
   worker_count=min(4,max(1,(os.cpu_count() or 2)//2),total)
   context=multiprocessing.get_context('spawn')
   CACHE.mkdir(parents=True,exist_ok=True)
   with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count,mp_context=context) as pool:
    self.pool=pool
    futures={pool.submit(run_one,(self.pdf_path,r,str(CACHE))):r['id'] for r in regions}
    for f in concurrent.futures.as_completed(futures):
     if self.cancel_flag.is_set():
      for pending in futures:pending.cancel()
      break
     try:self.events.put(('result',f.result()))
     except Exception as e:self.events.put(('failed',futures[f],str(e)))
     done+=1;self.events.put(('progress',done,total))
   self.events.put(('complete',done,total,self.cancel_flag.is_set()))
  except Exception as e:self.events.put(('fatal',str(e)))
 def cancel_batch(self):
  if self.busy:
   self.cancel_flag.set();self.note('已请求取消；尚未开始的任务将被取消，正在运行的OCR可能需要完成当前任务。')
 def poll_events(self):
  try:
   while True:
    event=self.events.get_nowait()
    if event[0]=='result':self.receive_result(event[1])
    elif event[0]=='failed':
     rid,err=event[1:];r=next((r for r in self.regions if r['id']==rid),None)
     if r:r['state']='失败';self.render_regions()
     self.note(f'{rid}识别失败：{err[:180]}')
    elif event[0]=='progress':
     done,total=event[1:];self.progress['value']=100*done/max(1,total);self.progress_label.config(text=f'已完成 {done}/{total} 台')
    elif event[0]=='complete':
     self.busy=False;self.pool=None
     done,total,canceled=event[1:];self.note(f"{'已取消' if canceled else '识别结束'}：收到{done}/{total}个任务结果。请复核未确认项。")
    elif event[0]=='fatal':self.busy=False;self.note('任务失败：'+event[1]);messagebox.showerror('识别失败',event[1])
  except queue.Empty:pass
  if self.root.winfo_exists():self.root.after(120,self.poll_events)
 def receive_result(self,result):
  rid=result['region_id'];r=next((r for r in self.regions if r['id']==rid),None)
  if r is None:return
  # Human work belongs to records, independently of the region's transient state.
  existing=[x for x in self.rows if x.get('region_id')==rid]
  if any(x.get('status')=='已确认' or x.get('manual_modified') or x.get('source')=='人工录入' or (x.get('evidence_type')=='verified_symbol' and x.get('location_quality')=='人工标定') for x in existing):
   r['state']='需人工核对';r['pending_ocr_result']=copy.deepcopy(result)
   self.render_regions();self.paint_regions()
   self.note(f'{rid}含人工确认或修改记录，保留现有清单；新OCR候选已单独保存到项目。')
   return
  self.rows=[x for x in self.rows if x.get('region_id')!=rid]
  r.pop('pending_ocr_result',None)
  parsed=[normalize_recognition_row(x) for x in result['rows']];diag=result['diag']
  label=diag.get('cabinet') or '待确认柜号'
  if r.get('manual_name') or (r.get('cabinet') not in ('','待确认柜号')):
   # The header-only pass is less likely to pick the incoming feeder's
   # upstream cabinet. Never silently overwrite a manual or header ID.
   label=r['cabinet']
  if diag.get('cabinet') not in ('', '待确认柜号',label) and label not in ('','待确认柜号'):
   r['cabinet_warning']='标题柜号与逐回路OCR柜号不一致：'+str(diag['cabinet'])
  r.update(cabinet=label,state='已识别' if parsed else '需人工核对',count=len(parsed),last_diag=diag)
  for row in parsed:row['cabinet']=label
  self.rows.extend(parsed)
  self.render_regions();self.refresh();self.paint_regions()
  if diag.get('unreadable_tags'):self.note(f"{label}: {len(diag['unreadable_tags'])}项图纸位号无法可靠读取，已留空待核对，没有自动编造。")
  if diag.get('surge_warnings'):
   self.note(label+' 防雷支路需复核：'+'；'.join(diag['surge_warnings']))
  if result.get('cached'):self.note(f'{rid}从缓存读取识别结果。')
 def show_quality(self):
  selected=self.selected_region();chosen=[r for r in self.rows if not selected or r.get('region_id')==selected['id']]
  missing=[r for r in chosen if not r.get('pdf_boxes')];review=[r for r in chosen if '待确认' in r.get('spec','') or r.get('kind')=='其他' or r.get('qty') is None]
  from surge_recognition_v17 import surge_pair_warnings
  alerts=surge_pair_warnings(chosen)
  totals=aggregate(chosen)
  txt=[f'区域：{selected["id"] if selected else "全部"}',f'候选记录：{len(chosen)}',
       f'候选已知数量：{sum(x["qty"] for x in totals)}；已确认数量：{sum(x.get("confirmed_qty",0) for x in totals)}；未知数量记录：{sum(x.get("unknown_qty_count",0) for x in totals)}',
       f'待核对记录：{sum(r.get("status")!="已确认" for r in chosen)}',f'待确认参数或数量：{len(review)}',f'无定位证据：{len(missing)}',
       f'防雷核对：{"；".join(alerts) if alerts else "未发现SPD/SCB单边漏识别风险"}',
       '\n以下原文保留供检查；软件不会以OCR猜测替代图纸：']
  if selected and selected.get('last_diag'):
   d=selected['last_diag'];txt.extend([f'识别布局：{d.get("layout","未知")}',f'方向检测：{d.get("orientation",{})}',f'检测支路/表格列：{d.get("feeders",0)}'])
   txt.append(f'未确认支路：{d.get("unresolved_branches",0)}')
   if d.get('reason'):txt.append('检测说明：'+str(d['reason']))
   warning_fields=[('geometry_warnings','几何检测'),('unreadable_tags','位号')]
   for key,label in warning_fields:
    warnings=d.get(key) or []
    if isinstance(warnings,str):warnings=[warnings]
    txt.extend(label+'：'+str(w) for w in warnings)
   geometry=d.get('geometry') or {}
   if geometry.get('unassigned_lines'):txt.append(f'另有{len(geometry["unassigned_lines"])}条孤立线未计为元器件，请核对。')
  if selected and selected.get('pending_ocr_result'):txt.append('该柜保留有新OCR候选；当前清单中的人工核对结果未被覆盖。')
  txt += [f'{r.get("tag","")} | {r.get("kind","")} | {r.get("spec","")} | OCR: {r.get("raw","")[:150]}' for r in review]
  win=tk.Toplevel(self.root);win.title('识别质量及高级诊断');win.geometry('800x580')
  t=tk.Text(win,wrap='word');t.pack(fill='both',expand=True);t.insert('1.0','\n'.join(txt));t.configure(state='disabled')
 def show_summary(self):
  chosen_region=self.selected_region();rr=[x for x in self.rows if not chosen_region or x.get('region_id')==chosen_region['id']]
  win=tk.Toplevel(self.root);win.title('元器件分类数量汇总');win.geometry('810x520')
  t=tk.Text(win,font=('Consolas',11));t.pack(fill='both',expand=True)
  t.insert('end','候选已知数量包含待核对记录；数量未知的记录不会按1计入。\n\n')
  for item in aggregate(rr):
   t.insert('end',f"{item['cabinet']} | {item['kind']} | {item['spec']}\n  候选已知：{item['qty']}；已确认：{item.get('confirmed_qty',0)}；待核对已知：{item.get('pending_qty',0)}；未知数量记录：{item.get('unknown_qty_count',0)}\n")
 def data(self):
  base=super().data()
  base.update(version='1.7.1',regions=self.regions,pdf_path=self.pdf_path or self.missing_pdf_path,pdf_sha256=self.project_pdf_sha256)
  return base

 def open_project(self):
  if not self.editing_allowed():return
  p=filedialog.askopenfilename(filetypes=[('项目文件','*.json')])
  if not p:return
  if self.rows and not messagebox.askyesno('打开项目','当前清单将被替换，请先保存。继续吗？'):return
  try:
   data=json.loads(Path(p).read_text(encoding='utf-8'))
   rows=[normalize_recognition_row(x) for x in data.get('rows',[])];regions=data.get('regions',[])
   pdf=data.get('pdf_path','')
   # A missing B.pdf must never leave project B bound to an already-open A.pdf.
   self.detach_pdf()
   self.rows=rows;self.regions=regions;self.active_region=regions[0]['id'] if regions else None
   self.project_pdf_sha256=data.get('pdf_sha256','');self.missing_pdf_path=pdf or '原PDF待关联'
   for r in self.rows:
    if r.get('location_quality') in ('估计','高','中','旧版粗定位') and r.get('evidence_type') not in ('verified_symbol','printed_label'):
     r.pop('pdf_boxes',None);r.pop('rel_boxes',None)
     r['location_quality']='未定位';r['location_note']='旧版估算坐标已清除，请重新识别或手工标定'
   settings=data.get('settings',{});self.type.set(settings.get('cabinet_type','柜'));self.direct.set(settings.get('direct',0));self.vfd.set(settings.get('vfd',0));self.fire.set(settings.get('fire',False));self.dual.set(settings.get('dual',False));self.lamp.set(settings.get('lamp',True))
   linked=bool(pdf and Path(pdf).exists() and self.load_pdf(pdf,preserve_project=True))
   self.render_regions();self.refresh();self.show_pdf();self.preview()
   if linked:self.note('项目已读取，原PDF已关联。')
   else:
    self.note('项目清单已读取，原图尚未关联；请点击「关联原PDF」，清单将被保留。')
    messagebox.showwarning('原图未关联','清单与分柜框已保留。请点击「关联原PDF」选择原文件，恢复定位与识别。')
  except Exception as e:messagebox.showerror('读取项目失败',str(e))

 def dialog(self,record=None):
  record=record or dict(cabinet=self.current_cabinet.get(),page=self.page+1,kind=TYPES[0],spec='',qty=None,tag='',status='待核对',source='人工录入',raw='',remark='')
  w=tk.Toplevel(self.root);w.title('元器件明细');w.geometry('590x590');w.transient(self.root);w.grab_set();entries={}
  fields=[('cabinet','柜号'),('page','PDF页'),('kind','元器件类别'),('spec','图纸规格'),('qty','数量（空白为未知）'),('tag','位号'),('status','状态'),('raw','识别原文'),('remark','备注')]
  for idx,(key,label) in enumerate(fields):
   ttk.Label(w,text=label).grid(row=idx,column=0,sticky='w',padx=15,pady=8)
   var=tk.StringVar(value='' if record.get(key) is None else str(record.get(key,'')))
   if key=='kind':entry=ttk.Combobox(w,textvariable=var,values=TYPES,width=43)
   elif key=='status':entry=ttk.Combobox(w,textvariable=var,values=['已确认','待核对','无法识别'],state='readonly',width=43)
   else:entry=ttk.Entry(w,textvariable=var,width=45,state='readonly' if record.get('region_id') and key in ('cabinet','page') else 'normal')
   entry.grid(row=idx,column=1,sticky='ew',padx=8);entries[key]=var
  result=[]
  def ok():
   try:
    d={k:v.get().strip() for k,v in entries.items()};d['qty']=int(d['qty']) if d['qty'] else None;d['page']=int(d['page'])
    if d['page']<1 or (d['qty'] is not None and d['qty']<0):raise ValueError('数量与页码不合法')
    if d['status']=='已确认' and d['qty'] is None:raise ValueError('请填写数量后再设为已确认')
    d.update({k:copy.deepcopy(v) for k,v in record.items() if k not in d})
    d['source']=record.get('source','人工录入');d['manual_modified']=True
    if d['qty']!=record.get('qty') or d['source']=='人工录入':
     d['quantity_source']='manual';d['quantity_verified']=d['qty'] is not None
    result.append(d);w.destroy()
   except Exception as e:messagebox.showwarning('数据错误',str(e)+'。页码至少为1，数量为非负整数或空白。',parent=w)
  ttk.Button(w,text='保存',command=ok).grid(row=10,column=1,pady=15,sticky='e');w.wait_window()
  return result[0] if result else None

 def add(self):
  if not self.editing_allowed():return
  r=self.selected_region()
  if r is None:return messagebox.showinfo('提示','请先选择元器件所属的柜子。')
  record=dict(region_id=r['id'],cabinet=r['cabinet'],page=r['page'],kind=TYPES[0],spec='',qty=None,tag='',status='待核对',source='人工录入',raw='',remark='')
  d=self.dialog(record)
  if d:
   d.update(region_id=r['id'],cabinet=r['cabinet'],page=r['page'],manual_modified=True,quantity_source='manual',quantity_verified=d.get('qty') is not None)
   self.rows.append(d);r['count']=sum(x.get('region_id')==r['id'] for x in self.rows)
   self.refresh();self.render_regions()

 def edit(self):
  if not self.editing_allowed():return
  i=self.selected()
  if i is None:return
  old=self.rows[i];d=self.dialog(old)
  if d:
   d['manual_modified']=True
   if d.get('qty')!=old.get('qty'):
    d['quantity_source']='manual';d['quantity_verified']=d.get('qty') is not None
   self.rows[i]=d;self.refresh()

 def delete(self):
  if not self.editing_allowed():return
  super().delete()
  for r in self.regions:r['count']=sum(x.get('region_id')==r['id'] for x in self.rows)
  self.render_regions()
 def close(self):
  if self.busy and not messagebox.askyesno('识别进行中','后台识别仍在进行，确定退出吗？'):return
  if self.rows and not messagebox.askyesno('保存提醒','建议先保存项目。仍要退出吗？'):return
  self.cancel_flag.set()
  if self.doc:self.doc.close()
  self.root.destroy()

if __name__=='__main__':
 multiprocessing.freeze_support()
 root=tk.Tk();Main(root);root.mainloop()
