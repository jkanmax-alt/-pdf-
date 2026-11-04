import os,sys,json,datetime,re,copy
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
import fitz
from PIL import Image,ImageTk
from core import TYPES,parse_lines,aggregate,quote_preview,save_csv,save_xlsx,ocr_image,recognize_cabinet_image

BASE=Path(__file__).resolve().parent
class Main:
 def __init__(self,root):
  self.root=root;root.title('电气图纸识别与报价 V1.4 · 混合定位版');root.geometry('1450x850');root.minsize(1080,650)
  self.doc=None;self.pdf_path='';self.page=0;self.rows=[];self.current_cabinet=tk.StringVar(value='待分柜');self.zoom=tk.DoubleVar(value=1.6);self.image=None;self.ocr_rect=None;self.drag_start=None;self.photo=None
  self.type=tk.StringVar(value='柜');self.direct=tk.IntVar(value=0);self.vfd=tk.IntVar(value=0);self.fire=tk.BooleanVar();self.dual=tk.BooleanVar();self.lamp=tk.BooleanVar(value=True)
  self.build();self.root.protocol('WM_DELETE_WINDOW',self.close)
 def build(self):
  style=ttk.Style();style.theme_use('clam');style.configure('Treeview',rowheight=27,font=('Microsoft YaHei UI',10));style.configure('TButton',font=('Microsoft YaHei UI',10));style.configure('TLabel',font=('Microsoft YaHei UI',10))
  bar=tk.Frame(self.root,bg='#19334d',height=64);bar.pack(side='top',fill='x');tk.Label(bar,text='⚡ 电气图纸识别与报价  V1.4',bg='#19334d',fg='white',font=('Microsoft YaHei UI',17,'bold')).pack(side='left',padx=15)
  for title,fun in [('打开PDF',self.open_pdf),('打开项目',self.open_project),('保存项目',self.save_project),('导出Excel',self.export_xlsx),('导出CSV',self.export_csv)]:tk.Button(bar,text=title,command=fun,relief='flat',bg='#eaf2fb',padx=12,pady=7).pack(side='left',padx=5)
  pan=ttk.Panedwindow(self.root,orient='horizontal');pan.pack(fill='both',expand=True,padx=8,pady=8)
  left=ttk.Frame(pan);right=ttk.Frame(pan);pan.add(left,weight=5);pan.add(right,weight=6)
  nav=ttk.Frame(left);nav.pack(fill='x',pady=(0,5));ttk.Button(nav,text='◀ 上一页',command=lambda:self.go(-1)).pack(side='left');self.page_label=ttk.Label(nav,text='未打开PDF');self.page_label.pack(side='left',padx=10);ttk.Button(nav,text='下一页 ▶',command=lambda:self.go(1)).pack(side='left');ttk.Label(nav,text='缩放').pack(side='left',padx=(16,2));ttk.Combobox(nav,textvariable=self.zoom,values=[0.75,1,1.3,1.6,2,2.5,3],width=6,state='readonly').pack(side='left');self.zoom.trace_add('write',lambda *_:self.show_pdf())
  self.canvas=tk.Canvas(left,bg='#b7c0ca',cursor='crosshair');sbv=ttk.Scrollbar(left,orient='vertical',command=self.canvas.yview);sbh=ttk.Scrollbar(left,orient='horizontal',command=self.canvas.xview);self.canvas.configure(yscrollcommand=sbv.set,xscrollcommand=sbh.set)
  self.canvas.pack(side='left',fill='both',expand=True);sbv.pack(side='right',fill='y');sbh.pack(side='bottom',fill='x');self.canvas.bind('<ButtonPress-1>',self.down);self.canvas.bind('<B1-Motion>',self.move);self.canvas.bind('<ButtonRelease-1>',self.up)
  tools=ttk.Frame(right);tools.pack(fill='x',pady=(0,5));ttk.Label(tools,text='当前柜号').pack(side='left');ttk.Entry(tools,textvariable=self.current_cabinet,width=18).pack(side='left',padx=5);ttk.Button(tools,text='高清OCR识别整页',command=self.scan_page_ocr).pack(side='left',padx=3);ttk.Button(tools,text='框选高清OCR',command=self.scan_region).pack(side='left',padx=3);ttk.Button(tools,text='逐回路识别V1.4',command=self.scan_feeders).pack(side='left',padx=3)
  ttk.Button(tools,text='检查OCR环境',command=self.check_ocr_environment).pack(side='left',padx=3)
  ttk.Button(tools,text='高清证据预览',command=self.show_selected_evidence).pack(side='left',padx=3)
  tools2=ttk.Frame(right);tools2.pack(fill='x');ttk.Button(tools2,text='新增元器件',command=self.add).pack(side='left',padx=2);ttk.Button(tools2,text='编辑选中',command=self.edit).pack(side='left',padx=2);ttk.Button(tools2,text='删除选中',command=self.delete).pack(side='left',padx=2);ttk.Button(tools2,text='同类数量汇总',command=self.show_summary).pack(side='left',padx=2);ttk.Button(tools2,text='识别质量检查',command=self.show_quality).pack(side='left',padx=2)
  ttk.Label(right,text='图纸原始识别清单（单击定位原图 / 双击编辑；识别项待核对）',foreground='#52677c').pack(anchor='w',pady=(8,3))
  keys=['cabinet','page','kind','spec','qty','tag','status'];self.keys=keys
  treebox=ttk.Frame(right);treebox.pack(fill='both',expand=True)
  self.tree=ttk.Treeview(treebox,columns=keys,show='headings',selectmode='browse');labels=['柜号','页','类型','图纸规格','数量','位号','状态'];widths=[95,42,145,110,45,65,75]
  for key,title,width in zip(keys,labels,widths):self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=38,stretch=(key in ('kind','spec')))
  self.tree.pack(side='left',fill='both',expand=True);ss=ttk.Scrollbar(treebox,orient='vertical',command=self.tree.yview);ss.pack(side='right',fill='y');self.tree.configure(yscrollcommand=ss.set);self.tree.bind('<Double-1>',lambda e:self.edit());self.tree.bind('<<TreeviewSelect>>',lambda e:self.focus_selected())
  rules=ttk.LabelFrame(right,text='第二阶段预览（独立于原始识别清单）');rules.pack(fill='x',pady=(10,5))
  opts=ttk.Frame(rules);opts.pack(fill='x',padx=8,pady=5)
  ttk.Label(opts,text='类型').pack(side='left');ttk.Combobox(opts,textvariable=self.type,values=['柜','箱'],state='readonly',width=4).pack(side='left',padx=(3,10))
  ttk.Label(opts,text='直启路').pack(side='left');tk.Spinbox(opts,textvariable=self.direct,from_=0,to=99,width=4).pack(side='left',padx=3)
  ttk.Label(opts,text='变频路').pack(side='left');tk.Spinbox(opts,textvariable=self.vfd,from_=0,to=99,width=4).pack(side='left',padx=3)
  ttk.Checkbutton(opts,text='消防',variable=self.fire).pack(side='left');ttk.Checkbutton(opts,text='双电源',variable=self.dual).pack(side='left');ttk.Checkbutton(opts,text='三相指示灯',variable=self.lamp).pack(side='left')
  ttk.Button(rules,text='计算建议（不修改原始清单）',command=self.preview).pack(anchor='w',padx=8,pady=2)
  self.rule_text=tk.Text(rules,height=5,font=('Microsoft YaHei UI',10),wrap='word',bg='#f5f8fb');self.rule_text.pack(fill='x',padx=8,pady=5);self.preview()
  self.status=ttk.Label(self.root,text='就绪。先打开PDF，可框选单柜/元器件区域OCR；识别不保证100%准确，请人工核对。',foreground='#315471');self.status.pack(side='bottom',fill='x',padx=12,pady=3)
 def note(self,msg):self.status.configure(text=msg)
 def open_pdf(self):
  p=filedialog.askopenfilename(filetypes=[('PDF图纸','*.pdf')]);
  if not p:return
  try:self.doc=fitz.open(p);self.pdf_path=p;self.page=0;self.show_pdf();self.note(f'打开成功：{Path(p).name}，共{len(self.doc)}页。')
  except Exception as e:messagebox.showerror('打开失败',str(e))
 def show_pdf(self):
  if not self.doc:return
  try:
   p=self.doc[self.page];z=float(self.zoom.get());pix=p.get_pixmap(matrix=fitz.Matrix(z,z),alpha=False);im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
   self.image=im;self.photo=ImageTk.PhotoImage(im);self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.photo);self.canvas.configure(scrollregion=(0,0,im.width,im.height));self.page_label.configure(text=f'第 {self.page+1} / {len(self.doc)} 页');self.ocr_rect=None
  except Exception as e:self.note(str(e))
 def go(self,n):
  if self.doc and 0<=self.page+n<len(self.doc):self.page+=n;self.show_pdf()
 def down(self,e):
  self.drag_start=(self.canvas.canvasx(e.x),self.canvas.canvasy(e.y));self.canvas.delete('region')
 def move(self,e):
  if not self.drag_start:return
  x,y=self.drag_start;x2,y2=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y);self.canvas.delete('region');self.canvas.create_rectangle(x,y,x2,y2,outline='#e04b35',width=3,tags='region')
 def up(self,e):
  if not self.drag_start:return
  x,y=self.drag_start;x2,y2=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y);self.ocr_rect=(int(min(x,x2)),int(min(y,y2)),int(max(x,x2)),int(max(y,y2)));self.drag_start=None
 def scan_text(self):
  if not self.doc:return messagebox.showinfo('提示','请先打开PDF')
  raw=self.doc[self.page].get_text('text');self.consume(raw,'PDF文字')
  if len(raw.strip())<30:self.note('这一页可提取文字很少，建议放大并框选一台柜子使用区域OCR。')
 def scan_page_ocr(self):
  if not self.doc:return messagebox.showinfo('提示','请先打开PDF')
  if not messagebox.askyesno('确认','将对当前整页进行高清OCR。若一页有多个柜，建议先框选单柜，以免混柜。继续吗？'):return
  try:
   self.note('高清OCR进行中，请保持软件打开...');self.root.update_idletasks()
   p=self.doc[self.page];pix=p.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False)
   im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
   raw=ocr_image(im);self.consume(raw,'整页高清OCR');self.show_ocr_raw(raw)
  except Exception as e:messagebox.showwarning('OCR失败',str(e))
 def scan_region(self):
  if self.doc is None:return messagebox.showinfo('提示','请先打开PDF')
  if not self.ocr_rect:return messagebox.showinfo('提示','请在左侧图纸拖动鼠标，框选要识别的区域')
  x1,y1,x2,y2=self.ocr_rect
  if x2-x1<25 or y2-y1<15:return messagebox.showinfo('提示','框选范围太小')
  try:
   # The screen zoom is NOT the OCR resolution. Re-render the actual PDF clipping rectangle.
   z=float(self.zoom.get());region=fitz.Rect(x1/z,y1/z,x2/z,y2/z)
   region=region & self.doc[self.page].rect
   self.note('框选区域高清OCR进行中...');self.root.update_idletasks()
   pix=self.doc[self.page].get_pixmap(matrix=fitz.Matrix(3,3),clip=region,alpha=False)
   img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
   raw=ocr_image(img);self.consume(raw,'高清区域OCR');self.show_ocr_raw(raw)
  except Exception as e:messagebox.showwarning('OCR失败',str(e))
 def check_ocr_environment(self):
  import importlib.util
  errors=[]
  details=['软件Python: '+sys.executable]
  for name in ('fitz','PIL','pytesseract','numpy'):
   ok=importlib.util.find_spec(name) is not None
   details.append(name+': '+('已安装' if ok else '未安装'))
   if not ok:errors.append(name+' 未安装')
  try:
   from core import locate_tesseract
   path=locate_tesseract()
   details.append('Tesseract引擎: '+(path or '未找到'))
   if path:
    import pytesseract
    details.append('Tesseract版本: '+str(pytesseract.get_tesseract_version()))
   else: errors.append('Tesseract未找到')
  except Exception as e: errors.append(str(e))
  if errors:
   messagebox.showwarning('OCR环境检查','\n'.join(details)+'\n\n需要处理：\n'+'\n'.join(errors))
  else:
   messagebox.showinfo('OCR环境检查','\n'.join(details)+'\n\nOCR调用环境正常。识别准确率仍需人工核对。')
 def scan_feeders(self):
  if self.doc is None:return messagebox.showinfo('提示','请先打开PDF')
  try:
   if self.ocr_rect:
    x1,y1,x2,y2=self.ocr_rect;z=float(self.zoom.get())
    clip=fitz.Rect(x1/z,y1/z,x2/z,y2/z)&self.doc[self.page].rect
   else:clip=self.doc[self.page].rect
   self.note('V1.4图形辅助识别中：检查横向回路、元件标注与测量支路...');self.root.update_idletasks()
   pix=self.doc[self.page].get_pixmap(matrix=fitz.Matrix(2.5,2.5),clip=clip,alpha=False)
   image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
   found,diag=recognize_cabinet_image(image,self.page+1,source='V1.4图形辅助逐回路识别')
   for r in found:
    if r.get('rel_boxes'):
     boxes=[]
     for x0,y0,x1,y1 in r['rel_boxes']:
      boxes.append([round(clip.x0+x0*clip.width,2),round(clip.y0+y0*clip.height,2),round(clip.x0+x1*clip.width,2),round(clip.y0+y1*clip.height,2)])
     r['pdf_boxes']=boxes
     r['pdf_x']=round((boxes[0][0]+boxes[0][2])/2,2)
     r['pdf_y']=round((boxes[0][1]+boxes[0][3])/2,2)
    elif 'pdf_rel_y' in r:
     r['pdf_y']=round(clip.y0+float(r['pdf_rel_y'])*clip.height,2)
     r['pdf_x']=round(clip.x0+float(r.get('pdf_rel_x',0.29))*clip.width,2)
   # CAD drawing paths corroborate geometric source positions, but never invent a device.
   vector_paths=self.doc[self.page].get_drawings()
   validated=0
   for r in found:
    for box in r.get('pdf_boxes',[])[:1]:
     area=fitz.Rect(box)
     n=sum(1 for path in vector_paths if path.get('rect') and area.intersects(path['rect']))
     r['vector_path_hits']=n
     if n and r.get('location_quality')=='高':validated+=1
   diag['vector_validated']=validated
   if diag.get('mode')!='row':
    messagebox.showwarning('当前版式暂不支持',diag.get('reason','识别失败'))
    self.note('未识别到可靠的回路结构，已有清单未改变。')
    return
   cabinet=diag.get('cabinet','待确认柜号')
   if not messagebox.askyesno('识别预览',f"识别柜号：{cabinet}\n检测到断路器/待确认馈线：{diag['feeders']} 条\n共得到 {len(found)} 条候选记录。\n\n将替换当前页同柜号的旧识别结果，其他柜号数据不动。继续吗？"):
    self.show_ocr_raw(diag.get('raw',''));return
   self.rows=[r for r in self.rows if not (r.get('page')==self.page+1 and r.get('cabinet')==cabinet and r.get('source') in ('V1.2逐回路OCR','V1.3多轮逐回路OCR','V1.3.1多轮逐回路OCR','V1.4图形辅助逐回路识别'))]
   self.rows.extend(found);self.current_cabinet.set(cabinet);self.refresh()
   self.note(f"V1.4识别完成：{cabinet}，{diag['feeders']}条馈线，{len(found)}条候选。请核对所有待确认项。")
   self.show_ocr_raw(diag.get('raw',''))
  except Exception as e:messagebox.showerror('逐回路识别失败',str(e))
 def show_ocr_raw(self,raw):
  w=tk.Toplevel(self.root);w.title('OCR原文核对（识别结果需人工复核）');w.geometry('750x540')
  t=tk.Text(w,wrap='word');t.pack(fill='both',expand=True);t.insert('1.0',raw)
  ttk.Button(w,text='复制OCR原文',command=lambda:(self.root.clipboard_clear(),self.root.clipboard_append(t.get('1.0','end-1c')))).pack(pady=5)
 def consume(self,raw,source):
  found=parse_lines(raw,self.page+1,self.current_cabinet.get(),source);self.rows+=found;self.refresh();self.note(f'{source}提取 {len(found)} 条候选项（并非实际元件数量，请核对后调整）。')
  if not found:messagebox.showinfo('未得到有效候选','OCR可能没有成功读出关键词。请查看随后弹出的OCR原文、缩小选区至元器件列，或手动补录。')
 def refresh(self):
  self.tree.delete(*self.tree.get_children());self.canvas.delete('focus')
  for i,r in enumerate(self.rows):self.tree.insert('', 'end',iid=str(i),values=[r.get(k,'') for k in self.keys])
 def focus_selected(self):
  self.canvas.delete('focus')
  i=self.selected()
  if i is None or not self.doc:return
  row=self.rows[i]
  if not row.get('pdf_boxes') and row.get('pdf_y') is None:
   self.note('此记录尚无图纸坐标（例如旧版OCR或人工新增项）。建议重新执行V1.4逐回路识别。')
   return
  try:
   page=int(row.get('page',1))-1
   if page!=self.page:self.page=page;self.show_pdf()
   z=float(self.zoom.get()); boxes=row.get('pdf_boxes') or []
   if not boxes:
    yy=float(row['pdf_y']);xx=float(row.get('pdf_x',self.doc[self.page].rect.width*.3))
    boxes=[[xx-70,yy-12,xx+100,yy+12]]
   for b in boxes:
    x0,y0,x1,y1=(float(v)*z for v in b)
    self.canvas.create_rectangle(x0,y0,x1,y1,outline='#e22d29',width=4,tags='focus')
   bb=boxes[0];mx=(float(bb[0])+float(bb[2]))*.5*z;my=(float(bb[1])+float(bb[3]))*.5*z
   self.canvas.update_idletasks()
   self.canvas.yview_moveto(max(0,min(1,(my-self.canvas.winfo_height()*.47)/max(self.image.height if self.image else 1,1))))
   self.canvas.xview_moveto(max(0,min(1,(mx-self.canvas.winfo_width()*.47)/max(self.image.width if self.image else 1,1))))
   quality=row.get('location_quality','旧版粗定位')
   self.note(f"图纸定位：{row.get('cabinet','')} {row.get('tag','')} {row.get('spec','')} | 位置证据：{quality}。{row.get('location_note','')}。红框可复核，不能作为无需确认的证明。")
  except Exception as e:self.note('定位失败：'+str(e))
 def show_selected_evidence(self):
  idx=self.selected()
  if idx is None:return messagebox.showinfo('提示','请先选中右侧一条元器件')
  if not self.doc:return messagebox.showinfo('提示','请先打开原始PDF')
  r=self.rows[idx]; boxes=r.get('pdf_boxes')
  if not boxes:return messagebox.showinfo('未定位','当前项目记录没有坐标，请重新识别后再预览')
  page=int(r.get('page',1))-1
  if not 0<=page<len(self.doc):return
  b=fitz.Rect(boxes[0]);pg=self.doc[page]
  # Include surrounding context for a useful human decision.
  pad_x=max(25,b.width*.65);pad_y=max(23,b.height*.9)
  b=fitz.Rect(b.x0-pad_x,b.y0-pad_y,b.x1+pad_x,b.y1+pad_y)&pg.rect
  pix=pg.get_pixmap(matrix=fitz.Matrix(3.2,3.2),clip=b,alpha=False)
  im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
  im.thumbnail((1040,610))
  win=tk.Toplevel(self.root);win.title(f"高清证据 · {r.get('tag','')} {r.get('kind','')}");win.geometry('1060x750')
  # Keep the Tk reference alive
  win.preview_image=ImageTk.PhotoImage(im)
  tk.Label(win,image=win.preview_image,bg='#e7ecf0').pack(fill='both',expand=True,padx=10,pady=10)
  ttk.Label(win,text=f"图纸规格: {r.get('spec','')}  |  定位质量: {r.get('location_quality','未知')}  |  {r.get('location_note','')} ",wraplength=1020).pack(fill='x',padx=12)
  ttk.Label(win,text=f"OCR原文: {str(r.get('raw','')).replace(chr(10),' ')[:400]}",wraplength=1020).pack(fill='x',padx=12,pady=4)
  ttk.Button(win,text='编辑该元器件',command=lambda:(win.destroy(),self.edit())).pack(pady=8)
 def show_quality(self):
  rows=self.rows
  cabinet=self.current_cabinet.get()
  chosen=[r for r in rows if r.get('cabinet')==cabinet]
  if not chosen:chosen=rows
  feeder=[r for r in chosen if re.fullmatch(r'W\d+',str(r.get('tag','')))]
  missing=[r for r in chosen if not r.get('pdf_boxes')]
  unknown=[r for r in chosen if r.get('kind')=='其他' or '待确认' in r.get('spec','')]
  unconfirmed=[r for r in chosen if r.get('status')!='已确认']
  lines=[f'柜号：{cabinet}',f'元器件候选：{len(chosen)}',f'已发现出线回路：{len(feeder)}',f'缺少定位：{len(missing)}',f'类别/规格存在待确认：{len(unknown)}',f'尚未人工确认：{len(unconfirmed)}','', '注意：定位成功≠规格已验证，所有OCR候选须复核。','']
  lines+=['待确认项目：']+[f"{r.get('tag','公共支路') or '公共支路'} {r.get('kind','')} {r.get('spec','')}" for r in unknown]
  lines+=['','无坐标项目：']+[f"{r.get('tag','') or '公共支路'} {r.get('kind','')}" for r in missing]
  win=tk.Toplevel(self.root);win.title('识别质量检查');win.geometry('650x510')
  t=tk.Text(win,wrap='word',font=('Microsoft YaHei UI',10));t.pack(fill='both',expand=True,padx=10,pady=10);t.insert('1.0','\n'.join(lines));t.configure(state='disabled')
 def selected(self):
  ids=self.tree.selection();return int(ids[0]) if ids else None
 def dialog(self,record=None):
  record=record or dict(cabinet=self.current_cabinet.get(),page=self.page+1,kind=TYPES[0],spec='',qty=1,tag='',status='已确认',source='人工录入',raw='',remark='')
  w=tk.Toplevel(self.root);w.title('元器件明细');w.geometry('560x550');w.transient(self.root);w.grab_set();entries={}
  fields=[('cabinet','柜号'),('page','PDF页'),('kind','元器件类别'),('spec','图纸规格'),('qty','数量'),('tag','位号'),('status','状态'),('raw','识别原文'),('remark','备注')]
  for idx,(key,label) in enumerate(fields):
   ttk.Label(w,text=label).grid(row=idx,column=0,sticky='w',padx=15,pady=8)
   var=tk.StringVar(value=str(record.get(key,'')))
   if key=='kind':entry=ttk.Combobox(w,textvariable=var,values=TYPES,width=43)
   elif key=='status':entry=ttk.Combobox(w,textvariable=var,values=['已确认','待核对','无法识别'],width=43)
   else:entry=ttk.Entry(w,textvariable=var,width=45)
   entry.grid(row=idx,column=1,sticky='ew',padx=8);entries[key]=var
  result=[]
  def ok():
   try:
    d={k:v.get().strip() for k,v in entries.items()};d['qty']=int(d['qty']);d['page']=int(d['page']);assert d['qty']>=0
    d.update({k:copy.deepcopy(v) for k,v in record.items() if k not in d});d['source']=record.get('source','人工录入');result.append(d);w.destroy()
   except Exception:messagebox.showwarning('数据错误','页码和数量应为非负整数（页码至少为1）。',parent=w)
  ttk.Button(w,text='保存',command=ok).grid(row=10,column=1,pady=15,sticky='e');w.wait_window();return result[0] if result else None
 def add(self):
  d=self.dialog();
  if d:self.rows.append(d);self.refresh()
 def edit(self):
  i=self.selected()
  if i is None:return
  d=self.dialog(self.rows[i]);
  if d:self.rows[i]=d;self.refresh()
 def delete(self):
  i=self.selected()
  if i is not None and messagebox.askyesno('确认','删除选中项？'):self.rows.pop(i);self.refresh()
 def show_summary(self):
  agg=aggregate(self.rows);w=tk.Toplevel(self.root);w.title('按柜号/类别/规格汇总');w.geometry('730x500');t=tk.Text(w,font=('Consolas',11));t.pack(fill='both',expand=True)
  for a in agg:t.insert('end',f"{a['cabinet']:16} {a['kind']:20} {a['spec']:15} × {a['qty']}\n")
 def preview(self):
  try:vals=quote_preview(self.rows,self.type.get(),self.direct.get(),self.vfd.get(),self.fire.get(),self.dual.get(),self.lamp.get())
  except Exception as e:return self.note('规则参数有误：'+str(e))
  self.rule_text.delete('1.0','end');self.rule_text.insert('end','\n'.join(f'{a}：{b}（{c}）' for a,b,c in vals))
 def data(self):return {'version':'1.4','pdf_path':self.pdf_path,'rows':self.rows,'settings':{'cabinet_type':self.type.get(),'direct':self.direct.get(),'vfd':self.vfd.get(),'fire':self.fire.get(),'dual':self.dual.get(),'lamp':self.lamp.get()}}
 def save_project(self):
  p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('项目文件','*.json')]);
  if not p:return
  Path(p).write_text(json.dumps(self.data(),ensure_ascii=False,indent=2),encoding='utf-8');self.note('项目已保存：'+p)
 def open_project(self):
  p=filedialog.askopenfilename(filetypes=[('项目文件','*.json')]);
  if not p:return
  try:
   data=json.loads(Path(p).read_text(encoding='utf-8'));self.rows=data['rows'];s=data.get('settings',{});self.type.set(s.get('cabinet_type','柜'));self.direct.set(s.get('direct',0));self.vfd.set(s.get('vfd',0));self.fire.set(s.get('fire',False));self.dual.set(s.get('dual',False));self.lamp.set(s.get('lamp',True));self.refresh();self.preview()
   old=data.get('pdf_path','');
   if old and Path(old).exists():self.doc=fitz.open(old);self.pdf_path=old;self.page=0;self.show_pdf()
   else:self.pdf_path='';self.note('项目已打开；原PDF路径不可用，请手动重新打开PDF。')
  except Exception as e:messagebox.showerror('读取失败',str(e))
 def export_csv(self):
  p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV文件','*.csv')]);
  if p:save_csv(p,self.rows);self.note('已导出：'+p)
 def export_xlsx(self):
  p=filedialog.asksaveasfilename(defaultextension='.xlsx',filetypes=[('Excel工作簿','*.xlsx')]);
  if not p:return
  try:save_xlsx(p,self.rows,quote_preview(self.rows,self.type.get(),self.direct.get(),self.vfd.get(),self.fire.get(),self.dual.get(),self.lamp.get()));self.note('已导出Excel：'+p)
  except Exception as e:messagebox.showerror('Excel导出失败',str(e)+'\n可先导出CSV。')
 def close(self):
  if self.rows and not messagebox.askyesno('退出确认','退出前请确认已保存项目。仍要退出吗？'):return
  if self.doc:self.doc.close()
  self.root.destroy()
if __name__=='__main__':
 root=tk.Tk();Main(root);root.mainloop()
