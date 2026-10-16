"""Bounded local Tk video player. Decode off-thread; audio uses installed ffplay."""
from __future__ import annotations
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk


class LocalPlayer(ttk.Frame):
    def __init__(self, master, width=480, height=270):
        super().__init__(master)
        self.width, self.height = width, height
        self.canvas = tk.Canvas(self, width=width, height=height, bg='#101014', highlightthickness=0)
        self.canvas.pack()
        self.caption = tk.StringVar(value='Selecione a mídia para comparar fonte e preview.')
        ttk.Label(self, textvariable=self.caption).pack()
        self.frames = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.session = 0
        self.audio = None
        self.photo = None
        self.current_timestamp = 0
        self.current_path = None
        self.current_end = None
        self.after(50, self._poll)
        self.bind('<Destroy>', self._destroy)

    def _destroy(self, event):
        if event.widget is self:
            self.stop()

    def stop(self):
        self.session += 1
        self.stop_event.set()
        if self.audio and self.audio.poll() is None:
            self.audio.terminate()
        self.audio = None

    def show(self, path, start=0, end=None, play=False):
        self.stop()
        path = Path(path)
        if not path.is_file():
            self.caption.set('Arquivo de mídia indisponível.')
            return
        self.stop_event = threading.Event()
        self.current_path, self.current_timestamp, self.current_end = path, start, end
        event, session = self.stop_event, self.session
        if play and shutil.which('ffplay'):
            cmd = ['ffplay', '-hide_banner', '-loglevel', 'error', '-nodisp', '-autoexit', '-ss', str(start)]
            if end is not None:
                cmd += ['-t', str(end-start)]
            self.audio = subprocess.Popen([*cmd, '-i', str(path)], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.caption.set(f'{path.name} · {start:.3f}s' + (' · áudio via FFplay' if self.audio else ' · frame/vídeo sem áudio'))
        def decode():
            import cv2
            cap = cv2.VideoCapture(str(path))
            try:
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                cap.set(cv2.CAP_PROP_POS_MSEC, start*1000)
                began = time.monotonic()
                frame_number = 0
                while not event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    timestamp = start + frame_number/fps
                    if end is not None and timestamp >= end:
                        break
                    h, w = frame.shape[:2]
                    scale = min(self.width/w, self.height/h)
                    frame = cv2.cvtColor(cv2.resize(frame, (max(1, int(w*scale)), max(1, int(h*scale)))), cv2.COLOR_BGR2RGB)
                    try:
                        self.frames.put_nowait((session, timestamp, frame))
                    except queue.Full:
                        pass
                    if not play:
                        break
                    frame_number += 1
                    event.wait(max(0, frame_number/fps-(time.monotonic()-began)))
            finally:
                cap.release()
        threading.Thread(target=decode, daemon=True).start()

    def _poll(self):
        try:
            while True:
                session, timestamp, frame = self.frames.get_nowait()
                if session != self.session:
                    continue
                from PIL import Image, ImageTk
                self.current_timestamp = timestamp
                self.photo = ImageTk.PhotoImage(Image.fromarray(frame))
                self.canvas.delete('all')
                self.canvas.create_image(self.width//2, self.height//2, image=self.photo)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50, self._poll)

    def pause(self):
        self.stop()

    def resume(self):
        if self.current_path:
            self.show(self.current_path, self.current_timestamp, self.current_end, play=True)
