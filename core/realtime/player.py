# -*- coding: utf-8 -*-
"""播放器：pygame.mixer，可打断"""
import time, threading, queue

class Player:
    def __init__(self, on_start=None, on_end=None, on_error=None):
        self.on_start = on_start or (lambda g,p: None)
        self.on_end = on_end or (lambda g: None)
        self.on_error = on_error or (lambda m: None)
        self._mixer = None
        self._gen = 0
        self._q = queue.Queue()
        self._running = False
        self._lock = threading.Lock()

    def available(self):
        try:
            import pygame; return True
        except ImportError:
            return False

    def start(self):
        try:
            import pygame
            pygame.mixer.init(frequency=24000, size=-16, channels=1)
            self._mixer = pygame.mixer
        except Exception as e:
            self.on_error("pygame初始化失败: %s" % str(e)[:60])
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        try:
            if self._mixer: self._mixer.music.stop()
        except: pass

    def current_gen(self):
        return self._gen

    def bump_gen(self):
        with self._lock:
            self._gen += 1
            try:
                if self._mixer: self._mixer.music.stop()
            except: pass
            while not self._q.empty():
                try: self._q.get_nowait()
                except: break

    def play(self, gen, path):
        self._q.put((gen, path))

    def end_round(self, gen):
        self._q.put((gen, None))

    def _loop(self):
        while self._running:
            try:
                gen, path = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if path is None:
                if gen == self._gen:
                    self.on_end(gen)
                continue
            if gen != self._gen: continue
            if not self._mixer: continue
            try:
                self._mixer.music.load(path)
                self.on_start(gen, path)
                self._mixer.music.play()
                while self._mixer.music.get_busy() and self._running:
                    if self._gen != gen:
                        self._mixer.music.stop(); break
                    time.sleep(0.05)
            except Exception as e:
                self.on_error("播放失败: %s" % str(e)[:60])
