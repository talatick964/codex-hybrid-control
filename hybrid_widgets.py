"""Small native Tk components for the rounded desktop theme."""
import ctypes
import os
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk


def rgb(color):
    return tuple(int(color[i:i+2],16) for i in (1,3,5))


def mix(first,last,ratio):
    a,b=rgb(first),rgb(last)
    return '#%02x%02x%02x'%tuple(round(x+(y-x)*ratio) for x,y in zip(a,b))


def gradient_ancestor(widget):
    current=widget.master
    while current is not None:
        if isinstance(current,GradientFrame):return current
        current=getattr(current,'master',None)
    return None


def gradient_patch(gradient,widget,width,height,scale=1):
    im=Image.new('RGB',(width*scale,height*scale))
    draw=ImageDraw.Draw(im)
    horizontal=gradient.horizontal
    origin=(widget.winfo_rootx()-gradient.winfo_rootx()) if horizontal else (widget.winfo_rooty()-gradient.winfo_rooty())
    extent=gradient.winfo_width() if horizontal else gradient.winfo_height()
    for index in range((width if horizontal else height)*scale):
        color=mix(*gradient.colors,min(1,max(0,(origin+index/scale)/max(1,extent))))
        draw.line((index,0,index,height*scale) if horizontal else (0,index,width*scale,index),fill=color)
    return im


class GradientFrame(tk.Frame):
    def __init__(self,parent,colors=('#252b30','#1b1d20'),horizontal=False,**kwargs):
        kwargs.setdefault('bg',colors[0])
        super().__init__(parent,**kwargs)
        self.colors=colors;self.horizontal=horizontal
        self._back=tk.Label(self,bd=0,highlightthickness=0)
        self._back.place(x=0,y=0,relwidth=1,relheight=1)
        self._back.lower()
        self.bind('<Configure>',self._paint,add='+')

    def sample(self,y):
        return mix(*self.colors,min(1,max(0,y/max(1,self.winfo_height()))))

    def _paint(self,event=None):
        if event and event.widget is not self:return
        width,height=max(1,self.winfo_width()),max(1,self.winfo_height())
        key=(width,height,self.colors,self.horizontal)
        if getattr(self,'_paint_key',None)==key:return
        self._paint_key=key
        strip=Image.new('RGB',(width if self.horizontal else 1,1 if self.horizontal else height))
        draw=ImageDraw.Draw(strip)
        count=width if self.horizontal else height
        for index in range(count):
            color=mix(*self.colors,index/max(1,count-1))
            draw.point((index,0) if self.horizontal else (0,index),fill=color)
        self._photo=ImageTk.PhotoImage(strip.resize((width,height)),master=self)
        self._back.configure(image=self._photo)
        # Embedded text and layout frames use the local gradient colour. Rounded
        # controls paint their own surfaces and keep their selected/hover states.
        def tint(parent):
            for child in parent.winfo_children():
                if child is self._back:continue
                if isinstance(child,RoundButton):
                    child.repaint();continue
                if isinstance(child,GradientLabel):
                    child.repaint();continue
                if isinstance(child,GradientFrame):continue
                if isinstance(child,(tk.Frame,tk.Label)):
                    if child.winfo_height()<=2:continue
                    y=child.winfo_rooty()-self.winfo_rooty()+child.winfo_height()/2
                    child.configure(bg=self.sample(y))
                    tint(child)
        tint(self)


class GradientLabel(tk.Label):
    def __init__(self,parent,**kwargs):
        kwargs.update(bd=0,padx=0,pady=0,highlightthickness=0,compound='center')
        super().__init__(parent,**kwargs)
        self.bind('<Configure>',lambda e:self.repaint(),add='+')
    def repaint(self):
        gradient=gradient_ancestor(self)
        if gradient is None:return
        font=tkfont.Font(root=self,font=self.cget('font'))
        width=max(1,self.winfo_width(),font.measure(self.cget('text')))
        height=max(1,self.winfo_height(),font.metrics('linespace'))
        key=(width,height,gradient.colors,gradient.horizontal,gradient.winfo_width(),gradient.winfo_height(),
             self.winfo_rootx()-gradient.winfo_rootx(),self.winfo_rooty()-gradient.winfo_rooty())
        if getattr(self,'_paint_key',None)==key:return
        self._paint_key=key
        image=gradient_patch(gradient,self,width,height)
        self._photo=ImageTk.PhotoImage(image,master=self)
        self.configure(image=self._photo)


class RoundFrame(tk.Frame):
    def __init__(self,parent,bg='#222325',border='#303236',radius=14,**kwargs):
        kwargs.pop('highlightbackground',None);kwargs.pop('highlightthickness',None)
        super().__init__(parent,bg=bg,highlightbackground=border,highlightthickness=1,**kwargs)
        self.radius=radius;self.border=border;self._corners=[]
        outside=parent.cget('bg')
        scale=3;side=radius*2
        image=Image.new('RGB',(side*scale,side*scale),outside)
        draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((0,0,side*scale-1,side*scale-1),radius=radius*scale,fill=bg,outline=border,width=scale)
        image=image.resize((side,side),Image.Resampling.LANCZOS)
        for box,anchor,relx,rely,x,y in [
            ((0,0,radius,radius),'nw',0,0,-1,-1),
            ((radius,0,side,radius),'ne',1,0,1,-1),
            ((0,radius,radius,side),'sw',0,1,-1,1),
            ((radius,radius,side,side),'se',1,1,1,1)]:
            photo=ImageTk.PhotoImage(image.crop(box),master=self)
            corner=tk.Label(self,image=photo,bd=0,highlightthickness=0,bg=outside)
            corner._photo=photo
            corner.place(relx=relx,rely=rely,x=x,y=y,anchor=anchor)
            self._corners.append(corner)
        self.bind('<Configure>',lambda e:[corner.lift() for corner in self._corners] if e.widget is self else None,add='+')


class RoundButton(tk.Button):
    """Keeps Tk's keyboard, invoke and disabled semantics; draws only its skin."""
    def __init__(self,parent,**kwargs):
        self._label_text=kwargs.get('text','')
        self._fill=kwargs.pop('bg',kwargs.pop('background','#303236'))
        self._hover=kwargs.pop('activebackground','#3c4045')
        self._foreground=kwargs.get('fg','#eeeeee')
        self._padx=kwargs.pop('padx',16);self._pady=kwargs.pop('pady',10)
        self._radius=kwargs.pop('radius',9)
        self._transparent=kwargs.pop('transparent',False)
        self._over=False;self._focused=False;self._ready=False
        kwargs.update(bg=parent.cget('bg'),activebackground=parent.cget('bg'),bd=0,relief='flat',
                      highlightthickness=0,padx=0,pady=0,compound='center',cursor='hand2')
        super().__init__(parent,**kwargs)
        self._ready=True
        self.bind('<Configure>',lambda e:self.repaint(),add='+')
        self.bind('<Enter>',lambda e:self._interaction(True),add='+')
        self.bind('<Leave>',lambda e:self._interaction(False),add='+')
        self.bind('<FocusIn>',lambda e:self._focus(True),add='+')
        self.bind('<FocusOut>',lambda e:self._focus(False),add='+')
        self.repaint()

    def _interaction(self,over):
        self._over=over;self.repaint()

    def _focus(self,focused):
        self._focused=focused;self.repaint()

    def configure(self,cnf=None,**kwargs):
        if cnf and not isinstance(cnf,dict):return super().configure(cnf,**kwargs)
        options=dict(cnf or {});options.update(kwargs)
        if not options:return super().configure()
        for key in ('bg','background'):
            if key in options:self._fill=options.pop(key)
        if 'activebackground' in options:self._hover=options.pop('activebackground')
        if 'fg' in options:self._foreground=options['fg']
        if 'padx' in options:self._padx=options.pop('padx')
        if 'pady' in options:self._pady=options.pop('pady')
        if 'transparent' in options:self._transparent=options.pop('transparent')
        if 'text' in options:self._label_text=options['text']
        result=super().configure(**options) if options else None
        if getattr(self,'_ready',False):self.repaint()
        return result

    config=configure

    def cget(self,key):
        if key=='text':return self._label_text
        return super().cget(key)

    def repaint(self):
        if not self._ready or not self.winfo_exists():return
        font=tkfont.Font(root=self,font=super().cget('font'))
        text=self._label_text
        width=max(font.measure(text)+int(self._padx)*2,1)
        height=font.metrics('linespace')+int(self._pady)*2
        # Fill layouts can make a button wider than its requested text size.
        if self.winfo_width()>1:width=max(width,self.winfo_width())
        scale=3
        parent=self.master
        gradient=gradient_ancestor(self)
        bg=parent.cget('bg')
        disabled=super().cget('state')=='disabled'
        key=(width,height,text,str(super().cget('font')),self._fill,self._hover,self._radius,self._padx,self._pady,
             self._transparent,self._over,self._focused,disabled,bg,super().cget('anchor'),
             (gradient.colors,gradient.horizontal,gradient.winfo_width(),gradient.winfo_height(),
              self.winfo_rootx()-gradient.winfo_rootx(),self.winfo_rooty()-gradient.winfo_rooty()) if gradient else None)
        if getattr(self,'_paint_key',None)==key:return
        self._paint_key=key
        if gradient is not None:
            im=gradient_patch(gradient,self,width,height,scale)
            bg='#%02x%02x%02x'%im.getpixel((0,0))
        else:im=Image.new('RGB',(width*scale,height*scale),bg)
        fill=self._hover if self._over and not disabled else self._fill
        if disabled:fill=mix(fill,bg,.5)
        if not self._transparent or self._over or self._focused:
            draw=ImageDraw.Draw(im)
            draw.rounded_rectangle((0,0,width*scale-1,height*scale-1),radius=self._radius*scale,fill=fill,
                                   outline='#8298ad' if self._focused else fill,width=scale)
        image=im.resize((width,height),Image.Resampling.LANCZOS)
        self._photo=ImageTk.PhotoImage(image,master=self)
        if super().cget('anchor')=='w':
            padding=max(0,int((width-2*self._padx-font.measure(text))/max(1,font.measure(' '))))
            text=text+' '*padding
        super().configure(image=self._photo,text=text,bg=bg,activebackground=bg)


def choose_fonts(root):
    available=set(tkfont.families(root))
    body=next((name for name in ('Segoe UI Variable Text','Segoe UI','Arial') if name in available),'TkDefaultFont')
    heading=next((name for name in ('Segoe UI Variable Display Semib','Segoe UI Semibold',body) if name in available),body)
    return body,heading


def install_chrome(window,title,body_font):
    def cancel_window_timers(event):
        if event.widget is not window:return
        commands=set(getattr(window,'_tclCommands',None) or [])
        for identifier in window.tk.call('after','info'):
            try:
                script=window.tk.call('after','info',identifier)[0]
                if str(script) in commands:window.after_cancel(identifier)
            except tk.TclError:pass
    window.bind('<Destroy>',cancel_window_timers,add='+')
    bar=GradientFrame(window,colors=('#282f36','#1c2025'),horizontal=True,height=36)
    bar.pack(side='top',fill='x');bar.pack_propagate(False)
    caption=GradientLabel(bar,text='  ›_   '+title,bg='#282f36',fg='#c1c7ce',font=(body_font,9),anchor='w')
    caption.pack(side='left',padx=12)
    user32=ctypes.windll.user32 if os.name=='nt' else None
    def hwnd():return user32.GetParent(window.winfo_id())
    def apply_frame(event=None):
        if event and event.widget is not window:return
        if not user32:return
        handle=hwnd()
        style=user32.GetWindowLongW(handle,-16)
        # Retain the native resizable frame, system menu, taskbar and snap support.
        user32.SetWindowLongW(handle,-16,(style & ~0x00C00000)|0x00040000|0x00020000|0x00010000)
        user32.SetWindowPos(handle,0,0,0,0,0,0x27)
        try:
            dark=ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(handle,20,ctypes.byref(dark),4)
        except OSError:pass
    def maximize(event=None):
        # Tk owns the native window. Its wm command enters Tcl with the proper
        # thread state before ShowWindow can dispatch resize/focus callbacks.
        window.state('normal' if window.state()=='zoomed' else 'zoomed')
        window.after_idle(apply_frame)
    def minimize():
        window.iconify()
    def drag(event):
        if user32:
            user32.ReleaseCapture()
            # SendMessage synchronously re-enters Tk from a ctypes callback,
            # outside _tkinter's Tcl/Python thread-state transition. A real
            # native move loop can then abort Python (PyEval_RestoreThread).
            # Let Tk's normal message pump dispatch the move instead.
            position=(event.x_root & 0xffff)|((event.y_root & 0xffff)<<16)
            user32.PostMessageW(hwnd(),0x00A1,2,position)
    for target in (bar,caption,bar._back):
        target.bind('<ButtonPress-1>',drag)
        target.bind('<Double-Button-1>',maximize)
    def close():
        getattr(window,'_request_close',window.destroy)()
    for text,action,color in [('×',close,'#873c42'),('□',maximize,'#39434d'),('−',minimize,'#39434d')]:
        control=RoundButton(bar,text=text,command=action,bg='#232931',fg='#c4cbd3',activeforeground='#ffffff',
                            activebackground=color,font=(body_font,12),padx=16,pady=5,radius=6,transparent=True)
        control.pack(side='right',padx=(0,3),pady=2)
    window.bind('<Map>',lambda e:window.after_idle(apply_frame) if e.widget is window else None,add='+')
    window.after_idle(apply_frame)
    window._custom_chrome=bar
    window._chrome_maximize=maximize
    window._chrome_minimize=minimize
    return bar
