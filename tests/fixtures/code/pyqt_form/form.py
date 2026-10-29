# -*- coding: utf-8 -*-
class Form:
    def __init__(self):
        self.handler = None
        self.saved = 0

    def submit(self):
        self.saved += 1
