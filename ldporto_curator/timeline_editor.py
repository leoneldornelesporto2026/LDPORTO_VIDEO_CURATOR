"""Canonical-time timeline geometry and Tk editing, without media processing."""
from bisect import bisect_left
from dataclasses import dataclass,field
import math
import tkinter as tk
from tkinter import ttk


def timestamp(seconds):
    millis=round(float(seconds)*1000)
    return f'{millis//3600000:02d}:{millis//60000%60:02d}:{millis//1000%60:02d}.{millis%1000:03d}'


@dataclass
class TimelineRange:
    duration: float
    start: float=0
    end: float|None=None
    view_start: float=0
    view_end: float|None=None
    boundaries:list=field(default_factory=list)

    def __post_init__(self):
        if not math.isfinite(self.duration) or self.duration<=0:
            raise ValueError('Duração da fonte inválida')
        self.view_end=self.duration if self.view_end is None else self.view_end
        self.boundaries=sorted(set(float(v) for v in self.boundaries if math.isfinite(v) and 0<=v<=self.duration))
        self.select(self.start,self.duration if self.end is None else self.end)

    def select(self,start,end):
        if not all(math.isfinite(v) for v in (start,end)) or not 0<=start<end<=self.duration:
            raise ValueError('Limites devem estar dentro da fonte')
        self.start,self.end=float(start),float(end)

    def to_pixel(self,seconds,width):
        return (seconds-self.view_start)/(self.view_end-self.view_start)*max(1,width)

    def from_pixel(self,x,width):
        return max(0,min(self.duration,self.view_start+max(0,min(width,x))/max(1,width)*(self.view_end-self.view_start)))

    def drag(self,edge,x,width,snap=True):
        seconds=self.from_pixel(x,width)
        if snap and self.boundaries:
            at=bisect_left(self.boundaries,seconds)
            options=self.boundaries[max(0,at-1):at+1]
            nearest=min(options,key=lambda v:abs(v-seconds))
            tolerance=min(.5,(self.view_end-self.view_start)/max(1,width)*8)
            if abs(nearest-seconds)<=tolerance:seconds=nearest
        if edge=='start':self.start=max(0,min(self.end-.001,seconds))
        elif edge=='end':self.end=min(self.duration,max(self.start+.001,seconds))
        else:raise ValueError('Handle desconhecido')
        return self.start,self.end

    def zoom(self,factor,center=None):
        if not math.isfinite(factor) or factor<=0:raise ValueError('Zoom inválido')
        center=(self.start+self.end)/2 if center is None else max(0,min(self.duration,center))
        span=min(self.duration,max(.05,(self.view_end-self.view_start)/factor))
        self.view_start=max(0,min(self.duration-span,center-span/2))
        self.view_end=self.view_start+span

    def pan(self,fraction):
        span=self.view_end-self.view_start
        self.view_start=max(0,min(self.duration-span,self.view_start+span*fraction))
        self.view_end=self.view_start+span


class EpisodeTimeline(ttk.Frame):
    def __init__(self,master,on_seek=None,on_select=None,on_apply=None):
        super().__init__(master)
        self.model=TimelineRange(1)
        self.plan,self.evidence={},{}
        self.episode_id=None
        self.drag_edge=None
        self.playhead=0
        self.on_seek=on_seek or (lambda t:None)
        self.on_select=on_select or (lambda key:None)
        self.on_apply=on_apply or (lambda start,end:None)
        self.snap=tk.BooleanVar(value=True)
        self.info=tk.StringVar(value='Selecione um episódio; arraste os limites e clique Aplicar.')
        controls=ttk.Frame(self);controls.pack(fill='x')
        ttk.Checkbutton(controls,text='Snap fala/cena',variable=self.snap).pack(side='left')
        for label,command in [('−',lambda:self._zoom(.5)),('+',lambda:self._zoom(2)),('←',lambda:self._pan(-.4)),('→',lambda:self._pan(.4))]:
            ttk.Button(controls,text=label,width=3,command=command).pack(side='left',padx=2)
        ttk.Button(controls,text='Aplicar limites',command=lambda:self.on_apply(self.model.start,self.model.end)).pack(side='left',padx=6)
        ttk.Label(controls,textvariable=self.info).pack(side='left',padx=8)
        self.canvas=tk.Canvas(self,height=172,bg='#f3f4f6',highlightthickness=0)
        self.canvas.pack(fill='x',expand=True)
        self.canvas.bind('<Configure>',lambda event:self.draw())
        self.canvas.bind('<ButtonPress-1>',self._press)
        self.canvas.bind('<B1-Motion>',self._drag)
        self.canvas.bind('<ButtonRelease-1>',lambda event:setattr(self,'drag_edge',None))

    def set_project(self,plan,evidence):
        self.plan,self.evidence=plan,evidence
        total=evidence['source']['duration']
        bounds=[row[k] for component in ('segments','scenes') for row in evidence.get(component,[]) for k in ('start','end') if isinstance(row.get(k),(int,float))]
        selected=next(iter(plan.get('episodes') or plan.get('extras') or []),None)
        start,end=(selected['source_start'],selected['source_end']) if selected else (0,total)
        if self.model.duration!=total:self.model=TimelineRange(total,start,end,boundaries=bounds)
        else:self.model.boundaries=sorted(set(bounds))
        self.draw()

    def select_episode(self,episode):
        self.episode_id=episode['episode_id']
        self.model.select(episode['source_start'],episode['source_end'])
        self._info(False)
        self.draw()

    def set_playhead(self,seconds):
        self.playhead=max(0,min(self.model.duration,seconds))
        self.canvas.delete('playhead')
        x=110+self.model.to_pixel(self.playhead,self._width())
        self.canvas.create_line(x,19,x,161,fill='#136c86',width=2,tags='playhead')

    def _width(self):return max(100,self.canvas.winfo_width()-125)
    def _zoom(self,factor):self.model.zoom(factor,self.playhead);self.draw()
    def _pan(self,fraction):self.model.pan(fraction);self.draw()

    def _info(self,dirty):
        self.info.set(f'{timestamp(self.model.start)} → {timestamp(self.model.end)} · {self.model.end-self.model.start:.3f}s'+(' · prévia do ajuste, não salvo' if dirty else ''))

    def draw(self):
        c=self.canvas;c.delete('all');width=self._width()
        lanes=[('Capítulos',self.evidence.get('chapters',[]),'#b8c4d0',29),
               ('Fala / cenas',self.evidence.get('segments',[]),'#c4ccd2',53),
               ('Série',self.plan.get('episodes',[]),'#7394a5',77),
               ('Extras',self.plan.get('extras',[]),'#ab9fb5',101),
               ('Lacunas',self.plan.get('story_map',{}).get('gaps',[]),'#ddc9aa',125)]
        for label,rows,color,y in lanes:
            c.create_text(8,y+7,anchor='w',text=label,fill='#25333d')
            c.create_line(110,y+15,110+width,y+15,fill='#d8dde2')
            for row in rows:
                start=row.get('source_start',row.get('start'));end=row.get('source_end',row.get('end'))
                if start is None or end is None or end<=self.model.view_start or start>=self.model.view_end:continue
                x1=110+self.model.to_pixel(max(start,self.model.view_start),width)
                x2=110+self.model.to_pixel(min(end,self.model.view_end),width)
                key=row.get('episode_id')
                c.create_rectangle(x1,y,x2,y+14,fill=color,outline='#f3f4f6',tags=('episode:'+key,) if key else ())
                if key and x2-x1>28:c.create_text((x1+x2)/2,y+7,text=str(row.get('order','')),fill='white',tags=('episode:'+key,))
        for row in self.plan.get('story_map',{}).get('excluded_intervals',[]):
            if row.get('end',0)<=self.model.view_start or row.get('start',self.model.duration)>=self.model.view_end:continue
            x1=110+self.model.to_pixel(max(row['start'],self.model.view_start),width)
            x2=110+self.model.to_pixel(min(row['end'],self.model.view_end),width)
            c.create_rectangle(x1,125,x2,139,fill='#c8b5b5',outline='')
        for i in range(6):
            t=self.model.view_start+(self.model.view_end-self.model.view_start)*i/5
            c.create_text(110+width*i/5,9,text=timestamp(t),font=('Segoe UI',8))
        if self.episode_id:
            for edge,t in [('start',self.model.start),('end',self.model.end)]:
                x=110+self.model.to_pixel(t,width)
                if 110<=x<=110+width:
                    c.create_line(x,22,x,151,fill='#b34d46',width=3,tags='handle:'+edge)
                    c.create_polygon(x-6,146,x+6,146,x,155,fill='#b34d46',tags='handle:'+edge)
        self.set_playhead(self.playhead)

    def _press(self,event):
        width=self._width()
        for edge,t in [('start',self.model.start),('end',self.model.end)]:
            if self.episode_id and abs(event.x-(110+self.model.to_pixel(t,width)))<8:
                self.drag_edge=edge;return
        items=self.canvas.find_overlapping(event.x,event.y,event.x,event.y)
        for item in reversed(items):
            key=next((tag[8:] for tag in self.canvas.gettags(item) if tag.startswith('episode:')),None)
            if key:self.on_select(key);break
        seconds=self.model.from_pixel(event.x-110,width)
        self.set_playhead(seconds);self.on_seek(seconds)

    def _drag(self,event):
        if self.drag_edge:
            self.model.drag(self.drag_edge,event.x-110,self._width(),self.snap.get())
            self._info(True);self.draw()
