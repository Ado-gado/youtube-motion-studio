"""Native Windows editor. UI stays on Tk's thread; preview/render run separately."""
from pathlib import Path
import copy
import io
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser, font as tkfont
from PIL import Image, ImageTk
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    BaseWindow = TkinterDnD.Tk
except ImportError:
    BaseWindow = tk.Tk
    DND_FILES = None
from .model import ROOT, new_project, new_clip, read_archive, validate_editor, save_project, load_project
from .preview import PreviewWorker
from .rendering import render_project, Cancelled

BG='#151a1f'; PANEL='#20272e'; FIELD='#11171c'; LINE='#34414a'
TEXT='#e8edf0'; MUTED='#a4b1bc'; ACCENT='#95c9b6'; SELECT='#334e49'


def human_size(value):
    for unit in ['Б','КБ','МБ','ГБ']:
        if value<1024 or unit=='ГБ': return f'{value:.1f} {unit}'
        value/=1024


class MotionEditor(BaseWindow):
    def __init__(self):
        super().__init__()
        self.title('Motion Studio · редактор фрагментов')
        self.geometry('1380x860'); self.minsize(1060,700); self.configure(bg=BG)
        self.project=new_project(); self.project_path=None; self.dirty=False
        self.selected=None; self.selected_text=None; self.current_time=0.0
        self.output=queue.Queue(); self.preview=PreviewWorker(self.output); self.preview.start()
        self.preview_token=0; self.photo=None; self.last_image=None; self.preview_busy=False
        self.rendering=False; self.importing=False; self.cancel=threading.Event(); self.playing=False
        self.suppress=False; self.drag=None; self.debounce=None; self.play_started=None
        self.make_style(); self.build_ui()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-s>',lambda event:self.save())
        self.bind('<Control-Shift-S>',lambda event:self.save(True))
        self.bind('<Control-o>',lambda event:self.open())
        self.bind('<space>',self.space)
        if DND_FILES:
            for widget in [self,self.clip_list,self.preview_canvas]:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>',self.drop)
        self.after(70,self.poll)
        self.after(150,self.switch_queue_mode)
        self.refresh_clips(); self.draw_timeline()

    def make_style(self):
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',background=BG,foreground=TEXT,font=('Segoe UI',10),bordercolor=LINE,lightcolor=LINE,darkcolor=LINE)
        style.configure('TButton',background=PANEL,foreground=TEXT,padding=(11,7),borderwidth=0)
        style.map('TButton',background=[('active','#34434b'),('disabled',BG)],foreground=[('disabled','#697880')])
        style.configure('Accent.TButton',background=ACCENT,foreground=BG,font=('Segoe UI',10,'bold'))
        style.map('Accent.TButton',background=[('active','#b2dccd'),('disabled','#42534e')])
        style.configure('TLabel',background=BG,foreground=TEXT)
        style.configure('Muted.TLabel',foreground=MUTED,font=('Segoe UI',9))
        style.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=TEXT,borderwidth=1,padding=5)
        style.configure('TCombobox',fieldbackground=FIELD,foreground=TEXT,background=PANEL,arrowcolor=TEXT,padding=4)
        style.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',TEXT)])
        style.configure('Horizontal.TProgressbar',background=ACCENT,troughcolor=PANEL,borderwidth=0)
        style.configure('Horizontal.TScale',background=BG,troughcolor=LINE)
        self.option_add('*TCombobox*Listbox.background',FIELD)
        self.option_add('*TCombobox*Listbox.foreground',TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground',SELECT)

    def button(self,parent,text,command,accent=False):
        return ttk.Button(parent,text=text,command=command,style='Accent.TButton' if accent else 'TButton')

    def build_ui(self):
        header=ttk.Frame(self,padding=(20,15));header.pack(fill='x')
        ttk.Label(header,text='MOTION STUDIO',font=('Segoe UI',16,'bold')).pack(side='left')
        ttk.Label(header,text='  /  редактор фрагментов',style='Muted.TLabel').pack(side='left')
        for name,fn in [('Новый',self.new),('Открыть',self.open),('Сохранить как',lambda:self.save(True)),('Сохранить',self.save)]:
            self.button(header,name,fn).pack(side='right',padx=4)
        self.project_label=ttk.Label(self,text='Новый проект',style='Muted.TLabel',padding=(22,0,0,10));self.project_label.pack(anchor='w')
        body=ttk.Frame(self,padding=(16,0));body.pack(fill='both',expand=True)
        body.columnconfigure(1,weight=1);body.rowconfigure(0,weight=1)
        left=ttk.Frame(body,width=245);left.grid(row=0,column=0,sticky='nsew',padx=(0,14));left.grid_propagate(False)
        left.columnconfigure(0,weight=1);left.rowconfigure(2,weight=1)
        ttk.Label(left,text='ФРАГМЕНТЫ',font=('Segoe UI',10,'bold')).grid(row=0,column=0,sticky='w',pady=(0,10))
        self.add_button=self.button(left,'＋ Добавить ZIP',self.add_dialog,True);self.add_button.grid(row=1,column=0,sticky='ew',pady=(0,10))
        self.clip_list=tk.Listbox(left,bg=PANEL,fg=TEXT,selectbackground=SELECT,selectforeground=TEXT,relief='flat',borderwidth=0,highlightthickness=0,font=('Segoe UI',11),activestyle='none',exportselection=False)
        self.clip_list.grid(row=2,column=0,sticky='nsew');self.clip_list.bind('<<ListboxSelect>>',self.on_clip_select)
        bar=ttk.Frame(left);bar.grid(row=3,column=0,sticky='ew',pady=8)
        up=self.button(bar,'↑',lambda:self.move(-1));up.configure(width=3);up.pack(side='left',padx=(0,4))
        down=self.button(bar,'↓',lambda:self.move(1));down.configure(width=3);down.pack(side='left',padx=4)
        self.button(bar,'Убрать',self.remove).pack(side='left',padx=(4,0))
        self.button(left,'Дублировать фрагмент',self.duplicate).grid(row=4,column=0,sticky='ew',pady=(0,5))
        self.button(left,'Найти перемещённый ZIP',self.relink).grid(row=5,column=0,sticky='ew',pady=(0,10))
        self.storage=ttk.Label(left,text='',style='Muted.TLabel',wraplength=235);self.storage.grid(row=6,column=0,sticky='w')

        center=ttk.Frame(body);center.grid(row=0,column=1,sticky='nsew');center.columnconfigure(0,weight=1);center.rowconfigure(1,weight=1)
        self.scene_label=ttk.Label(center,text='Добавь фрагменты из Emergent',font=('Segoe UI',12,'bold'));self.scene_label.grid(row=0,column=0,sticky='w',pady=(0,10))
        self.preview_canvas=tk.Canvas(center,bg='#0a0e11',highlightthickness=1,highlightbackground=LINE)
        self.preview_canvas.grid(row=1,column=0,sticky='nsew');self.preview_canvas.bind('<Configure>',lambda event:self.show_image())
        controls=ttk.Frame(center);controls.grid(row=2,column=0,sticky='ew',pady=8)
        self.play_button=self.button(controls,'▶ Просмотр',self.toggle_play);self.play_button.pack(side='left')
        self.button(controls,'Обновить кадр',self.apply_and_preview).pack(side='left',padx=7)
        self.clock=ttk.Label(controls,text='0.00 / 0.00 с',style='Muted.TLabel');self.clock.pack(side='right')
        self.slider=ttk.Scale(center,from_=0,to=1,command=self.seek_slider);self.slider.grid(row=3,column=0,sticky='ew')
        ttk.Label(center,text='НАДПИСИ · двигай полосу или её края',style='Muted.TLabel').grid(row=4,column=0,sticky='w',pady=(12,5))
        timeline_box=ttk.Frame(center);timeline_box.grid(row=5,column=0,sticky='ew');timeline_box.columnconfigure(0,weight=1)
        self.timeline=tk.Canvas(timeline_box,height=156,bg=PANEL,highlightthickness=0)
        self.timeline.grid(row=0,column=0,sticky='ew')
        timeline_scroll=ttk.Scrollbar(timeline_box,orient='vertical',command=self.timeline.yview);timeline_scroll.grid(row=0,column=1,sticky='ns');self.timeline.configure(yscrollcommand=timeline_scroll.set)
        self.timeline.bind('<Configure>',lambda event:self.draw_timeline())
        self.timeline.bind('<Button-1>',self.timeline_down);self.timeline.bind('<B1-Motion>',self.timeline_drag);self.timeline.bind('<ButtonRelease-1>',self.timeline_up)

        right=ttk.Frame(body,width=300);right.grid(row=0,column=2,sticky='nsew',padx=(16,0));right.grid_propagate(False)
        right.columnconfigure(0,weight=1)
        ttk.Label(right,text='ТЕКСТ И ПОЯВЛЕНИЕ',font=('Segoe UI',10,'bold')).grid(row=0,column=0,sticky='w',pady=(0,10))
        self.text_selector=ttk.Combobox(right,state='readonly');self.text_selector.grid(row=1,column=0,sticky='ew',pady=(0,9));self.text_selector.bind('<<ComboboxSelected>>',self.select_text)
        self.text_input=tk.Text(right,height=4,bg=FIELD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Segoe UI',12),wrap='word',padx=10,pady=9,undo=True)
        self.text_input.grid(row=2,column=0,sticky='ew')
        self.text_input.bind('<FocusOut>',lambda event:self.apply_fields(False))
        ttk.Label(right,text='Шрифт на этом ПК',style='Muted.TLabel').grid(row=3,column=0,sticky='w',pady=(13,4))
        fonts=sorted(set(f for f in tkfont.families(self) if not f.startswith('@')),key=str.casefold)
        self.font_var=tk.StringVar();self.font_box=ttk.Combobox(right,textvariable=self.font_var,values=fonts)
        self.font_box.grid(row=4,column=0,sticky='ew');self.font_box.bind('<<ComboboxSelected>>',lambda event:self.apply_and_preview())
        self.fields={};self.field_widgets=[];grid=ttk.Frame(right);grid.grid(row=5,column=0,sticky='ew',pady=10)
        for col in [0,1]:grid.columnconfigure(col,weight=1)
        for i,(key,label) in enumerate([('size','Размер'),('color','Цвет'),('start','Начало, с'),('end','Конец, с'),('enter','Вход, с'),('exit','Выход, с'),('x','Положение X'),('y','Положение Y')]):
            row,col=divmod(i,2);cell=ttk.Frame(grid);cell.grid(row=row,column=col,sticky='ew',padx=(0,8) if col==0 else (0,0),pady=(0,8))
            ttk.Label(cell,text=label,style='Muted.TLabel').pack(anchor='w')
            var=tk.StringVar();self.fields[key]=var
            entry=ttk.Entry(cell,textvariable=var,width=11);entry.pack(fill='x',pady=(3,0));entry.bind('<Return>',lambda event:self.apply_and_preview());entry.bind('<FocusOut>',lambda event:self.apply_fields(False))
            self.field_widgets.append(entry)
        self.apply_button=self.button(right,'Применить и показать',self.apply_and_preview,True);self.apply_button.grid(row=6,column=0,sticky='ew')
        self.compatibility=ttk.Label(right,text='Правки сохраняются в файле проекта. ZIP остаётся исходником.',style='Muted.TLabel',wraplength=292);self.compatibility.grid(row=7,column=0,sticky='w',pady=14)
        self.button(right,'Инструкция для Emergent',self.copy_emergent).grid(row=8,column=0,sticky='ew')

        footer=ttk.Frame(self,padding=(18,12));footer.pack(fill='x')
        self.render_button=self.button(footer,'Собрать видео',lambda:self.render(False),True);self.render_button.pack(side='right',padx=(8,0))
        self.render_one=self.button(footer,'Рендер фрагмента',lambda:self.render(True));self.render_one.pack(side='right',padx=(8,0))
        self.cancel_button=self.button(footer,'Отмена',self.cancel_job);self.cancel_button.pack(side='right',padx=(8,0));self.cancel_button.state(['disabled'])
        self.progress=ttk.Progressbar(footer,maximum=100,length=170);self.progress.pack(side='left',padx=(0,12))
        self.status=tk.StringVar(value='ZIP можно перетащить прямо в окно');ttk.Label(footer,textvariable=self.status,style='Muted.TLabel',wraplength=460).pack(side='left')

    def clip(self):
        return self.project['clips'][self.selected] if self.selected is not None and self.selected<len(self.project['clips']) else None

    def text_item(self):
        clip=self.clip()
        if clip and clip.get('editor') and self.selected_text is not None:
            items=clip['editor']['texts']
            if self.selected_text<len(items):return items[self.selected_text]
        return None

    def mark_dirty(self):
        self.dirty=True
        self.project_label.configure(text=(self.project_path.name if self.project_path else 'Новый проект')+' · есть несохранённые правки')

    def refresh_clips(self):
        self.suppress=True;self.clip_list.delete(0,'end')
        total=0;paths=set();size=0
        for i,clip in enumerate(self.project['clips']):
            total+=clip['render']['duration']
            missing=not Path(clip['archive']).is_file()
            mark='!' if missing else ('●' if clip.get('editor') is not None else '○')
            self.clip_list.insert('end',f'{i+1:02d}  {mark}  {clip["title"]}  · {clip["render"]["duration"]:g} с')
            if not missing and clip['archive'] not in paths:
                size+=Path(clip['archive']).stat().st_size;paths.add(clip['archive'])
        if self.selected is not None and self.selected<len(self.project['clips']):
            self.clip_list.selection_set(self.selected);self.clip_list.see(self.selected)
        self.storage.configure(text=f'{len(self.project["clips"])} фрагм. · {total:.1f} с\nИсходные ZIP: {human_size(size)}\nКопии архивов не создаются')
        self.suppress=False

    def drop(self,event):
        self.import_paths(self.tk.splitlist(event.data));return event.action

    def add_dialog(self):
        paths=filedialog.askopenfilenames(title='Добавить фрагменты',filetypes=[('Сцены Motion Studio','*.zip')])
        if paths:self.import_paths(paths)

    def import_paths(self,paths):
        if self.rendering or self.importing:return
        paths=[Path(x) for x in paths if Path(x).suffix.lower()=='.zip']
        if not paths:return
        self.importing=True;self.cancel.clear();self.cancel_button.state(['!disabled']);self.add_button.state(['disabled'])
        def work():
            count=0
            try:
                for path in paths:
                    if self.cancel.is_set():break
                    self.output.put(('status',f'Проверка ZIP: {path.name}'))
                    source=read_archive(path,cancel=self.cancel)
                    self.output.put(('imported',source));count+=1
            except InterruptedError:pass
            except Exception as error:self.output.put(('error',str(error)))
            finally:self.output.put(('import_done',count))
        threading.Thread(target=work,daemon=True).start()

    def on_clip_select(self,event=None):
        if self.suppress or not self.clip_list.curselection():return
        if self.rendering:self.refresh_clips();return
        index=self.clip_list.curselection()[0]
        if index==self.selected:return
        if not self.apply_fields():self.refresh_clips();return
        self.select_clip(index)

    def select_clip(self,index):
        self.stop_play();self.selected=index;self.selected_text=None;self.current_time=0
        clip=self.clip();self.scene_label.configure(text=clip['title'] if clip else 'Добавь фрагменты из Emergent')
        items=clip['editor']['texts'] if clip and clip.get('editor') is not None else []
        self.text_selector.configure(values=[item.get('label',item['id']) for item in items]);self.text_selector.set('')
        if items:self.selected_text=0;self.text_selector.current(0)
        self.fill_fields();self.slider.configure(to=clip['render']['duration'] if clip else 1)
        self.suppress=True;self.slider.set(0);self.suppress=False
        self.last_image=None;self.show_image();self.refresh_clips();self.draw_timeline();self.request_preview()
        if clip is None:self.preview_token+=1;self.preview.pause()
        if clip and clip.get('editor') is None:
            self.compatibility.configure(text='Этот ZIP старого формата: доступен просмотр и рендер. Для изменения слов и времени попроси Emergent подготовить сцену по EDITOR_SCENES.md.')
        else:self.compatibility.configure(text='ZIP не изменяется. Сохраняй проект после правок. Шрифт должен быть доступен на этом ПК.')

    def select_text(self,event=None):
        if self.rendering:return
        if not self.apply_fields():
            if self.selected_text is not None:self.text_selector.current(self.selected_text)
            return
        self.selected_text=self.text_selector.current();self.fill_fields();self.draw_timeline()

    def fill_fields(self):
        item=self.text_item();self.suppress=True
        self.text_input.configure(state='normal');self.text_input.delete('1.0','end')
        if item:self.text_input.insert('1.0',item['text'])
        self.font_var.set(item['font'] if item else '')
        for key,var in self.fields.items():
            value=item.get(key,'') if item else ''
            var.set(f'{value:.3f}'.rstrip('0').rstrip('.') if isinstance(value,float) else str(value))
        if not item:self.text_input.configure(state='disabled');self.apply_button.state(['disabled'])
        else:self.apply_button.state(['!disabled'])
        self.suppress=False

    def apply_fields(self,show_error=True):
        if self.suppress or self.rendering:return True
        item=self.text_item();clip=self.clip()
        if item is None:return True
        try:
            candidate=copy.deepcopy(clip['editor']);new=candidate['texts'][self.selected_text]
            new['text']=self.text_input.get('1.0','end-1c')
            family=self.font_var.get().strip()
            if family!=item['font']:
                new['font']=family;new['fontSources']=[family];new['weight']='400'
            for key,var in self.fields.items():
                new[key]=var.get().strip() if key=='color' else float(var.get().replace(',','.'))
            candidate=validate_editor(candidate,clip['render']['duration'])
            if candidate!=clip['editor']:
                clip['editor']=candidate;self.mark_dirty();self.draw_timeline()
            return True
        except Exception as error:
            if show_error:messagebox.showerror('Проверь параметры',str(error),parent=self)
            return False

    def apply_and_preview(self):
        if self.apply_fields():self.stop_play();self.request_preview()

    def request_preview(self):
        clip=self.clip()
        if not clip or self.rendering:return
        self.preview_token+=1;self.preview_busy=True
        self.preview.frame(copy.deepcopy(clip),self.current_time,self.preview_token)
        self.clock.configure(text=f'{self.current_time:.2f} / {clip["render"]["duration"]:.2f} с')

    def show_image(self):
        canvas=self.preview_canvas;w=max(1,canvas.winfo_width());h=max(1,canvas.winfo_height());canvas.delete('all')
        if self.last_image:
            image=self.last_image.copy();image.thumbnail((max(1,w-4),max(1,h-4)),Image.Resampling.LANCZOS)
            self.photo=ImageTk.PhotoImage(image);canvas.create_image(w/2,h/2,image=self.photo)
        else:
            canvas.create_text(w/2,h/2-14,text='Добавь ZIP с редактируемой сценой' if not self.clip() else 'Подготовка кадра…',fill=TEXT,font=('Segoe UI',13),width=max(120,w-50))
            canvas.create_text(w/2,h/2+20,text='Исходники остаются в архиве',fill=MUTED,font=('Segoe UI',10))

    def seek_slider(self,value):
        if self.suppress:return
        self.stop_play();self.current_time=float(value);self.draw_timeline()
        if self.debounce:self.after_cancel(self.debounce)
        self.debounce=self.after(90,self.request_preview)

    def stop_play(self):
        self.playing=False;self.play_button.configure(text='▶ Просмотр')

    def toggle_play(self):
        if self.playing:self.stop_play();return
        if not self.clip() or self.rendering or not self.apply_fields():return
        duration=self.clip()['render']['duration']
        if self.current_time>=duration-.05:self.current_time=0
        self.playing=True;self.play_started=time.monotonic()-self.current_time;self.play_button.configure(text='Ⅱ Пауза');self.play_tick()

    def play_tick(self):
        if not self.playing:return
        self.current_time=min(time.monotonic()-self.play_started,self.clip()['render']['duration'])
        self.suppress=True;self.slider.set(self.current_time);self.suppress=False;self.draw_timeline()
        if not self.preview_busy:self.request_preview()
        if self.current_time>=self.clip()['render']['duration']:self.stop_play();return
        self.after(90,self.play_tick)

    def space(self,event):
        if isinstance(self.focus_get(),(tk.Text,ttk.Entry,ttk.Combobox)):return
        self.toggle_play();return 'break'

    def draw_timeline(self):
        c=self.timeline;c.delete('all');clip=self.clip();width=max(c.winfo_width(),200);left=115;right=width-14
        self.timeline_bounds=(left,right)
        if not clip:
            c.create_text(18,34,anchor='w',text='Здесь появятся надписи выбранного фрагмента',fill=MUTED,font=('Segoe UI',10));return
        duration=clip['render']['duration'];items=clip['editor']['texts'] if clip.get('editor') else []
        height=max(156,36+len(items)*32);c.configure(scrollregion=(0,0,width,height))
        for i in range(6):
            x=left+(right-left)*i/5;c.create_line(x,24,x,height,fill=LINE)
            c.create_text(x,12,text=f'{duration*i/5:.1f}',fill=MUTED,font=('Segoe UI',8))
        for i,item in enumerate(items):
            y=40+i*32;x1=left+(right-left)*item['start']/duration;x2=left+(right-left)*item['end']/duration
            c.create_text(8,y+8,anchor='w',text=item.get('label',item['id'])[:16],fill=TEXT if i==self.selected_text else MUTED,font=('Segoe UI',9))
            color=ACCENT if i==self.selected_text else '#567e72'
            c.create_rectangle(x1,y,x2,y+17,fill=color,outline='')
            c.create_line(x1+3,y+3,x1+3,y+14,fill=BG,width=2);c.create_line(x2-3,y+3,x2-3,y+14,fill=BG,width=2)
        x=left+(right-left)*self.current_time/duration;c.create_line(x,22,x,height,fill='#e5c68c',width=2)

    def timeline_down(self,event):
        if self.rendering or not self.clip() or not self.clip().get('editor'):return
        self.stop_play()
        if not self.apply_fields():return
        y=self.timeline.canvasy(event.y);row=int((y-40)//32);items=self.clip()['editor']['texts']
        left,right=self.timeline_bounds;duration=self.clip()['render']['duration']
        if 0<=row<len(items) and 40+row*32<=y<=57+row*32:
            item=items[row];x1=left+(right-left)*item['start']/duration;x2=left+(right-left)*item['end']/duration
            if x1-7<=event.x<=x2+7:
                self.selected_text=row;self.text_selector.current(row);self.fill_fields()
                mode='start' if abs(event.x-x1)<9 else ('end' if abs(event.x-x2)<9 else 'move')
                self.drag=(mode,event.x,copy.deepcopy(item));self.draw_timeline();return
        self.current_time=max(0,min(duration,(event.x-left)/(right-left)*duration))
        self.suppress=True;self.slider.set(self.current_time);self.suppress=False;self.draw_timeline();self.request_preview()

    def timeline_drag(self,event):
        if not self.drag:return
        mode,x,original=self.drag;item=self.text_item();duration=self.clip()['render']['duration'];left,right=self.timeline_bounds
        delta=(event.x-x)/(right-left)*duration;minimum=1/self.clip()['render']['fps']
        if mode=='move':
            span=original['end']-original['start'];item['start']=max(0,min(duration-span,original['start']+delta));item['end']=item['start']+span
        elif mode=='start':item['start']=max(0,min(item['end']-minimum,original['start']+delta))
        else:item['end']=min(duration,max(item['start']+minimum,original['end']+delta))
        span=item['end']-item['start'];effects=item['enter']+item['exit']
        if effects>span:
            factor=span/effects;item['enter']*=factor;item['exit']*=factor
        self.fill_fields();self.draw_timeline();self.mark_dirty()

    def timeline_up(self,event):
        if self.drag:
            self.drag=None;self.current_time=min(self.clip()['render']['duration']-.01,self.text_item()['start']+self.text_item()['enter']+.05)
            self.suppress=True;self.slider.set(self.current_time);self.suppress=False;self.request_preview()

    def move(self,direction):
        if self.rendering or self.selected is None:return
        if not self.apply_fields():return
        index=self.selected;target=index+direction
        if 0<=target<len(self.project['clips']):
            clips=self.project['clips'];clips[index],clips[target]=clips[target],clips[index];self.selected=target;self.mark_dirty();self.refresh_clips()

    def duplicate(self):
        if self.rendering or not self.clip() or not self.apply_fields():return
        import uuid
        clip=copy.deepcopy(self.clip());clip['id']=uuid.uuid4().hex;clip['title']+=' · копия'
        self.project['clips'].insert(self.selected+1,clip);self.mark_dirty();self.select_clip(self.selected+1)

    def remove(self):
        if self.rendering or self.selected is None:return
        index=self.selected;self.project['clips'].pop(index);self.mark_dirty()
        self.select_clip(min(index,len(self.project['clips'])-1) if self.project['clips'] else None)

    def relink(self):
        clip=self.clip()
        if not clip or self.rendering:return
        path=filedialog.askopenfilename(title='Найти исходный ZIP',filetypes=[('ZIP','*.zip')])
        if not path:return
        try:
            source=read_archive(path)
            if source['sha256']!=clip['sha256']:raise ValueError('Это другая версия ZIP. Добавьте её отдельным фрагментом.')
            clip['archive']=source['path'];self.mark_dirty();self.refresh_clips();self.request_preview()
        except Exception as error:messagebox.showerror('Не удалось подключить ZIP',str(error),parent=self)

    def confirm_unsaved(self):
        if not self.apply_fields():return False
        if not self.dirty:return True
        answer=messagebox.askyesnocancel('Сохранить проект?','В проекте есть несохранённые изменения.',parent=self)
        if answer is None:return False
        if answer:return self.save()
        return True

    def new(self):
        if self.rendering or self.importing or not self.confirm_unsaved():return
        self.project=new_project();self.project_path=None;self.dirty=False;self.project_label.configure(text='Новый проект');self.select_clip(None);self.preview.pause()

    def open(self):
        if self.rendering or self.importing or not self.confirm_unsaved():return
        path=filedialog.askopenfilename(title='Открыть проект',filetypes=[('Проект Motion Studio','*.motion.json'),('JSON','*.json')])
        if path:self.open_path(path)

    def open_path(self,path):
        try:
            self.project=load_project(path);self.project_path=Path(path).resolve();self.dirty=False;self.project_label.configure(text=self.project_path.name)
            self.select_clip(0 if self.project['clips'] else None)
        except Exception as error:messagebox.showerror('Ошибка проекта',str(error),parent=self)

    def save(self,as_new=False):
        if self.rendering:return False
        if not self.apply_fields():return False
        path=None if as_new else self.project_path
        if not path:
            path=filedialog.asksaveasfilename(title='Сохранить проект',defaultextension='.motion.json',filetypes=[('Проект Motion Studio','*.motion.json')],initialdir=ROOT,initialfile='Мой фильм.motion.json')
        if not path:return False
        try:
            save_project(self.project,path);self.project_path=Path(path).resolve();self.dirty=False;self.project_label.configure(text=self.project_path.name);self.status.set('Проект сохранён · ZIP не копировались');return True
        except Exception as error:messagebox.showerror('Не удалось сохранить',str(error),parent=self);return False

    def copy_emergent(self):
        path=ROOT/'EDITOR_EMERGENT_MESSAGE.txt'
        if path.exists():
            self.clipboard_clear();self.clipboard_append(path.read_text(encoding='utf8'));self.status.set('Сообщение для Emergent скопировано')

    def render(self,only_selected):
        if self.rendering or self.importing or not self.project['clips'] or not self.apply_fields():return
        from local_worker import running,DEFAULT_QUEUE
        if DEFAULT_QUEUE.exists() and running(DEFAULT_QUEUE):
            messagebox.showinfo('Предыдущее задание','Автоматическая очередь ещё завершает текущее видео. Дождитесь окончания и повторите экспорт.',parent=self);return
        if self.dirty and not self.save():return
        clips=[self.clip()] if only_selected and self.clip() else self.project['clips']
        path=filedialog.asksaveasfilename(title='Куда сохранить MP4',defaultextension='.mp4',filetypes=[('Видео MP4','*.mp4')],initialdir=self.project_path.parent if self.project_path else ROOT,initialfile='Фрагмент.mp4' if only_selected else 'Мой фильм.mp4')
        if not path:return
        self.stop_play();self.rendering=True;self.cancel.clear();self.cancel_button.state(['!disabled']);self.render_button.state(['disabled']);self.render_one.state(['disabled']);self.add_button.state(['disabled'])
        self.editing_enabled(False)
        self.status.set('Подготовка рендера');snapshot=copy.deepcopy(clips);closed=self.preview.pause()
        def work():
            try:
                if not closed.wait(40):raise RuntimeError('Предпросмотр не успел закрыться. Повторите экспорт.')
                output=render_project(snapshot,path,self.cancel,lambda *event:self.output.put(event))
                self.output.put(('render_done',str(output)))
            except Cancelled:self.output.put(('render_cancelled',))
            except Exception as error:self.output.put(('render_error',str(error)))
        threading.Thread(target=work,daemon=True).start()

    def cancel_job(self):
        if self.rendering or self.importing:self.cancel.set();self.status.set('Отмена и очистка временных файлов…')

    def editing_enabled(self,enabled):
        self.text_input.configure(state='normal' if enabled and self.text_item() else 'disabled')
        self.text_selector.configure(state='readonly' if enabled else 'disabled')
        self.font_box.configure(state='normal' if enabled else 'disabled')
        for widget in self.field_widgets:widget.state(['!disabled' if enabled else 'disabled'])
        self.apply_button.state(['!disabled' if enabled and self.text_item() else 'disabled'])

    def poll(self):
        try:
            while True:
                event=self.output.get_nowait();kind=event[0]
                if kind=='preview' and event[1]==self.preview_token:
                    self.preview_busy=False;self.last_image=Image.open(io.BytesIO(event[2])).convert('RGB');self.show_image()
                    self.clock.configure(text=f'{event[3]:.2f} / {self.clip()["render"]["duration"]:.2f} с' if self.clip() else '')
                elif kind=='preview_error' and event[1]==self.preview_token:
                    self.last_image=None;self.preview_busy=False;self.stop_play();self.status.set('Предпросмотр: '+event[2].split('\n')[0]);self.preview_canvas.delete('all')
                    self.preview_canvas.create_text(max(150,self.preview_canvas.winfo_width()/2),max(80,self.preview_canvas.winfo_height()/2),text=event[2].split('\n')[0],fill='#efbdab',font=('Segoe UI',11),width=max(200,self.preview_canvas.winfo_width()-50))
                elif kind=='fatal_preview':self.preview_busy=False;self.status.set('Не запущен предпросмотр: '+event[1])
                elif kind=='status':self.status.set(event[1])
                elif kind=='imported':
                    source=event[1]
                    if not any(c['sha256']==source['sha256'] for c in self.project['clips']):
                        self.project['clips'].append(new_clip(source));self.mark_dirty();self.refresh_clips()
                        if self.selected is None:self.select_clip(0)
                elif kind=='import_done':
                    self.importing=False;self.cancel_button.state(['disabled']);self.add_button.state(['!disabled']);self.status.set('Архивы добавлены. Правки сохраняй в проекте; исходные ZIP сохраняй рядом.')
                elif kind=='error':messagebox.showerror('Ошибка',event[1],parent=self)
                elif kind=='render_progress':self.progress['value']=event[1];self.status.set(event[2])
                elif kind in ('render_done','render_cancelled','render_error'):
                    self.rendering=False;self.cancel_button.state(['disabled']);self.render_button.state(['!disabled']);self.render_one.state(['!disabled']);self.add_button.state(['!disabled'])
                    self.editing_enabled(True)
                    if kind=='render_done':
                        self.progress['value']=100;self.status.set('Готово: '+event[1]);messagebox.showinfo('Видео готово','Сохранено:\n'+event[1]+'\n\nВременные распаковки и промежуточные клипы удалены. Посмотри готовый MP4.',parent=self)
                    elif kind=='render_cancelled':self.progress['value']=0;self.status.set('Рендер отменён, временные файлы удалены')
                    else:self.status.set('Ошибка рендера');messagebox.showerror('Рендер не завершён',event[1][-3500:],parent=self)
        except queue.Empty:pass
        self.after(70,self.poll)

    def switch_queue_mode(self):
        from local_worker import running,DEFAULT_QUEUE
        if DEFAULT_QUEUE.exists() and running(DEFAULT_QUEUE):
            (DEFAULT_QUEUE/'STOP').write_text('Editor mode: stop automatic Downloads rendering after current job\n',encoding='utf8')
            self.status.set('Режим редактора: автозапуск из «Загрузок» остановлен после текущего задания')

    def close(self):
        if self.rendering or self.importing:
            messagebox.showinfo('Задание выполняется','Сначала дождись окончания или нажми «Отмена».',parent=self);return
        if not self.confirm_unsaved():return
        self.stop_play();self.preview.stop();self.withdraw()
        deadline=time.monotonic()+35
        def finish():
            if self.preview.is_alive() and time.monotonic()<deadline:self.after(100,finish)
            else:self.destroy()
        finish()


def main():
    import sys
    from local_worker import worker_lock
    state=ROOT/'EDITOR_WORK';state.mkdir(exist_ok=True)
    try:
        with worker_lock(state):
            app=MotionEditor()
            if len(sys.argv)>1:app.after(300,lambda:app.open_path(sys.argv[1]))
            app.mainloop()
    except RuntimeError as error:
        root=tk.Tk();root.withdraw();messagebox.showerror('Motion Studio',str(error));root.destroy()


if __name__=='__main__':main()
