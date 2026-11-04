"""ElectricalQuote V1.5: panel segmentation + parallel cabinet OCR + human review."""
import os, sys, json, copy, queue, threading, concurrent.futures, multiprocessing, re
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import fitz
from PIL import Image,ImageTk
from app import Main as PreviousMain
from segmentation_v15 import detect_document
from worker_v15 import run_one
from core import aggregate,save_csv,save_xlsx,quote_preview,TYPES,normalize_recognition_row

BASE=Path(__file__).resolve().parent
CACHE=BASE/'cache'
SOURCES=('V1.5分柜识别',)

class Main(PreviousMain):
 def __init__(self,root):
  self.regions=[];self.active_region=None;self.events=queue.Queue();self.cancel_flag=threading.Event();self.busy=False;self.pool=None
  super().__init__(root)
  self.root.after(120,self.poll_events)
  self.root.after(350,self.initial_sash_width)

 def build(self):
  self.root.title('电气图纸识别 V1.5.3 · 自动分柜与并行识别');self.root.geometry('1580x940');self.root.minsize(1150,690)
  style=ttk.Style();style.theme_use('clam');style.configure('Treeview',rowheight=27,font=('Microsoft YaHei UI',10));style.configure('TButton',font=('Microsoft YaHei UI',10))
  header=tk.Frame(self.root,bg='#17324d');header.pack(side='top',fill='x')
  tk.Label(header,text='⚡ 电气图纸智能识别  V1.5.3',bg='#17324d',fg='white',font=('Microsoft YaHei UI',16,'bold')).pack(side='left',padx=16,pady=11)
  for text,fn in [('打开PDF',self.open_pdf),('打开项目',self.open_project),('保存项目',self.save_project),('导出Excel',self.export_xlsx),('导出CSV',self.export_csv)]:
   tk.Button(header,text=text,command=fn,bg='#eaf1f9',relief='flat',padx=10,pady=7).pack(side='left',padx=4)
  self.tabs=ttk.Panedwindow(self.root,orient='horizontal');self.tabs.pack(fill='both',expand=True,padx=6,pady=6)
  side=ttk.Frame(self.tabs,width=230);mid=ttk.Frame(self.tabs);right=ttk.Frame(self.tabs)
  self.tabs.add(side,weight=3);self.tabs.add(mid,weight=5);self.tabs.add(right,weight=6)
  ttk.Label(side,text='单柜区域目录',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=6,pady=6)
  ttk.Button(side,text='① 检测整份PDF分柜',command=self.detect_regions).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='② 并行识别全部柜子',command=self.start_batch).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='识别当前选中柜子',command=self.recognize_selected).pack(fill='x',padx=5,pady=2)
  ttk.Button(side,text='取消未开始的任务',command=self.cancel_batch).pack(fill='x',padx=5,pady=2)
  self.regionlist=tk.Listbox(side,exportselection=False,font=('Microsoft YaHei UI',10),selectmode='browse',width=26);self.regionlist.pack(fill='both',expand=True,padx=5,pady=(10,3))
  self.regionlist.bind('<<ListboxSelect>>',self.select_region)
  tweak=ttk.Frame(side);tweak.pack(fill='x',padx=4)
  ttk.Button(tweak,text='框选新增',command=self.add_region).pack(side='left',padx=2)
  ttk.Button(tweak,text='框选替换',command=self.replace_region).pack(side='left',padx=2)
  ttk.Button(tweak,text='删除',command=self.delete_region).pack(side='left',padx=2)
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
  for t,fn in [('新增',self.add),('修改',self.edit),('删除',self.delete),('分类汇总',self.show_summary),('证据预览',self.show_selected_evidence),('识别质量',self.show_quality)]:
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

 def initial_sash_width(self):
  """Keep cabinet labels and action buttons readable at first launch."""
  try:
   target=min(255,max(210,int(self.root.winfo_width()*.16)))
   self.tabs.sashpos(0,target)
  except Exception:
   pass
 def note(self,message):self.status.configure(text=message)
 def open_pdf(self):
  p=filedialog.askopenfilename(filetypes=[('PDF文件','*.pdf')]);
  if not p:return
  self.load_pdf(p)
 def load_pdf(self,path):
  if self.busy:return messagebox.showwarning('识别进行中','请先取消或等待当前识别任务')
  try:
   if self.doc:self.doc.close()
   self.doc=fitz.open(path);self.pdf_path=str(path);self.page=0;self.regions=[];self.active_region=None;self.rows=[];self.refresh();self.render_regions();self.show_pdf()
   self.note(f'已打开 {Path(path).name}（{len(self.doc)}页），请先检测分柜。')
  except Exception as e:messagebox.showerror('打开PDF失败',str(e))
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
  z=float(self.zoom.get())
  for r in self.regions:
   if r['page']!=self.page+1:continue
   x0,y0,x1,y1=(v*z for v in r['box']);color='#16a34a' if r['state']=='已识别' else '#e0a11a'
   if r['id']==self.active_region:color='#e3342f'
   self.canvas.create_rectangle(x0,y0,x1,y1,outline=color,width=3,tags='cabinet_frames')
   self.canvas.create_text(x0+5,y0+5,text=r.get('cabinet','待确认柜号'),anchor='nw',font=('Microsoft YaHei UI',9,'bold'),fill=color,tags='cabinet_frames')
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
   self.regionlist.insert('end',f"{label} | 第{r['page']}页 | {r['state']} ({r['count']})")
  idx=next((i for i,r in enumerate(self.regions) if r['id']==self.active_region),None)
  if idx is not None:self.regionlist.selection_clear(0,'end');self.regionlist.selection_set(idx);self.regionlist.see(idx)
 def selected_region(self):
  ss=self.regionlist.curselection()
  if ss:return self.regions[ss[0]]
  return next((r for r in self.regions if r['id']==self.active_region),None)
 def select_region(self,e=None):
  r=self.selected_region()
  if not r:return
  self.active_region=r['id'];self.current_cabinet.set(r['cabinet']);self.page=r['page']-1;self.show_pdf();self.refresh();self.move_to_box(r['box'])
 def move_to_box(self,box):
  z=float(self.zoom.get());x=(box[0]+box[2])/2*z;y=(box[1]+box[3])/2*z
  self.canvas.update_idletasks()
  iw=max(1,self.image.width);ih=max(1,self.image.height)
  self.canvas.xview_moveto(max(0,min(1,(x-self.canvas.winfo_width()*.48)/iw)))
  self.canvas.yview_moveto(max(0,min(1,(y-self.canvas.winfo_height()*.32)/ih)))
 def chosen_rectangle(self):
  if self.ocr_rect is None:messagebox.showinfo('框选提示','请在左侧图纸按住鼠标拖出红色选择框');return None
  z=float(self.zoom.get());a,b,c,d=self.ocr_rect
  rect=fitz.Rect(a/z,b/z,c/z,d/z)&self.doc[self.page].rect
  if rect.width<45 or rect.height<45:messagebox.showwarning('区域太小','请重新框选更完整的单柜区域');return None
  return [round(v,2) for v in (rect.x0,rect.y0,rect.x1,rect.y1)]
 def add_region(self):
  if not self.doc:return
  bb=self.chosen_rectangle()
  if bb is None:return
  i=1
  existing={r['id'] for r in self.regions}
  while f'p{self.page+1}_manual{i}' in existing:i+=1
  r={'id':f'p{self.page+1}_manual{i}','page':self.page+1,'box':bb,'cabinet':'待确认柜号','state':'未识别','count':0}
  self.regions.append(r);self.active_region=r['id'];self.render_regions();self.paint_regions();self.note('已新增单柜区域；识别前可继续调整。')
 def replace_region(self):
  r=self.selected_region()
  if not r:return
  if r['page']!=self.page+1:return messagebox.showinfo('提示','请先切换到选中区域所在页面再框选')
  bb=self.chosen_rectangle()
  if bb is None:return
  if r['state']=='已识别' and not messagebox.askyesno('确认','更改已识别区域的边界会删除该区域的旧识别结果。继续吗？'):return
  self.rows=[row for row in self.rows if row.get('region_id')!=r['id']]
  r.update(box=bb,state='未识别',count=0);self.refresh();self.render_regions();self.paint_regions()
 def delete_region(self):
  r=self.selected_region()
  if not r:return
  if not messagebox.askyesno('删除区域','同时删除该区域的识别结果？'):return
  self.regions.remove(r);self.rows=[x for x in self.rows if x.get('region_id')!=r['id']]
  self.active_region=self.regions[0]['id'] if self.regions else None
  self.refresh();self.render_regions();self.paint_regions()
 def rename_region(self):
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
   self.tree.insert('','end',iid=str(i),values=[r.get(k,'') for k in self.keys])
 def focus_selected(self):
  self.canvas.delete('focus')
  idx=self.selected()
  if idx is None or self.doc is None:return
  r=self.rows[idx];box=r.get('pdf_boxes',[])
  if not box:return self.note('该项尚无定位证据，请核对原图。')
  page=int(r.get('page',1))-1
  if self.page!=page:self.page=page;self.show_pdf()
  z=float(self.zoom.get());b=box[0];x0,y0,x1,y1=(float(v)*z for v in b)
  self.canvas.create_rectangle(x0,y0,x1,y1,outline='#f02222',width=4,tags='focus');self.move_to_box(b)
  self.note(f"原图位置：{r.get('kind')} {r.get('spec')}；证据质量：{r.get('location_quality','待核对')}")
 def recognize_selected(self):
  r=self.selected_region()
  if not r:return messagebox.showinfo('提示','请先检测并选择单柜区域')
  self.start_tasks([r])
 def start_batch(self):
  if not self.regions:return messagebox.showinfo('提示','请先点击检测分柜')
  self.start_tasks(list(self.regions))
 def start_tasks(self,regions):
  if self.busy:return messagebox.showinfo('正在识别','请先完成或取消当前识别')
  if not self.pdf_path or not Path(self.pdf_path).exists():return messagebox.showerror('缺少PDF','PDF文件路径不可用')
  self.busy=True;self.cancel_flag.clear();self.progress['value']=0
  self.progress_label.config(text=f'识别0/{len(regions)}，可继续浏览页面')
  self.note('识别已在后台开始。每个工作进程独立识别一台柜子。')
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
  if r.get('state')=='已识别':
   # Existing manually reviewed rows must not be silently overwritten.
   existing=[x for x in self.rows if x.get('region_id')==rid]
   if any(x.get('status')=='已确认' for x in existing):
    r['state']='需人工核对';self.note(f'{rid}含人工确认记录，新OCR结果未覆盖。');return
  self.rows=[x for x in self.rows if x.get('region_id')!=rid]
  parsed=[normalize_recognition_row(x) for x in result['rows']];diag=result['diag']
  label=diag.get('cabinet') or '待确认柜号'
  if r.get('manual_name') or (r.get('cabinet') not in ('','待确认柜号')):
   # The header-only pass is less likely to pick the incoming feeder's
   # upstream cabinet. Never silently overwrite a manual or header ID.
   label=r['cabinet']
  if diag.get('cabinet') not in ('', '待确认柜号',label) and label not in ('','待确认柜号'):
   r['cabinet_warning']='标题柜号与逐回路OCR柜号不一致：'+str(diag['cabinet'])
  r.update(cabinet=label,state='已识别' if parsed else '需人工核对',count=len(parsed))
  for row in parsed:row['cabinet']=label
  self.rows.extend(parsed)
  self.render_regions();self.refresh();self.paint_regions()
  if diag.get('unreadable_tags'):self.note(f"{label}: {len(diag['unreadable_tags'])}项图纸位号无法可靠读取，已留空待核对，没有自动编造。")
  if result.get('cached'):self.note(f'{rid}从缓存读取识别结果。')
 def show_quality(self):
  selected=self.selected_region();chosen=[r for r in self.rows if not selected or r.get('region_id')==selected['id']]
  missing=[r for r in chosen if not r.get('pdf_boxes')];review=[r for r in chosen if '待确认' in r.get('spec','') or r.get('kind')=='其他']
  txt=[f'区域：{selected["id"] if selected else "全部"}',f'候选：{len(chosen)}',f'待确认参数：{len(review)}',f'无定位证据：{len(missing)}','\n以下原文保留供检查；软件不会以OCR猜测替代图纸：']
  txt += [f'{r.get("tag","")} | {r.get("kind","")} | {r.get("spec","")} | OCR: {r.get("raw","")[:150]}' for r in review]
  win=tk.Toplevel(self.root);win.title('识别质量及高级诊断');win.geometry('800x580')
  t=tk.Text(win,wrap='word');t.pack(fill='both',expand=True);t.insert('1.0','\n'.join(txt));t.configure(state='disabled')
 def show_summary(self):
  chosen_region=self.selected_region();rr=[x for x in self.rows if not chosen_region or x.get('region_id')==chosen_region['id']]
  win=tk.Toplevel(self.root);win.title('元器件分类数量汇总');win.geometry('810x520')
  t=tk.Text(win,font=('Consolas',11));t.pack(fill='both',expand=True)
  for item in aggregate(rr):t.insert('end',f"{item['cabinet']:17} {item['kind']:22} {item['spec']:19} ×{item['qty']}\n")
 def data(self):
  base=super().data();base.update(version='1.5.3',regions=self.regions);return base
 def open_project(self):
  p=filedialog.askopenfilename(filetypes=[('项目文件','*.json')]);
  if not p:return
  try:
   data=json.loads(Path(p).read_text(encoding='utf-8'));pdf=data.get('pdf_path','')
   if pdf and Path(pdf).exists():self.load_pdf(pdf)
   else:messagebox.showwarning('原图不可用','项目中的PDF路径已失效，请重新打开PDF后恢复项目数据')
   self.rows=[normalize_recognition_row(x) for x in data.get('rows',[])];self.regions=data.get('regions',[]);self.active_region=self.regions[0]['id'] if self.regions else None
   settings=data.get('settings',{});self.type.set(settings.get('cabinet_type','柜'));self.direct.set(settings.get('direct',0));self.vfd.set(settings.get('vfd',0));self.fire.set(settings.get('fire',False));self.dual.set(settings.get('dual',False));self.lamp.set(settings.get('lamp',True))
   self.render_regions();self.refresh();self.show_pdf();self.preview();self.note('项目已读取。')
  except Exception as e:messagebox.showerror('读取项目失败',str(e))
 def close(self):
  if self.busy and not messagebox.askyesno('识别进行中','后台识别仍在进行，确定退出吗？'):return
  if self.rows and not messagebox.askyesno('保存提醒','建议先保存项目。仍要退出吗？'):return
  self.cancel_flag.set()
  if self.doc:self.doc.close()
  self.root.destroy()

if __name__=='__main__':
 multiprocessing.freeze_support()
 root=tk.Tk();Main(root);root.mainloop()
