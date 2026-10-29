# -*- coding: utf-8 -*-
class Snake:
    def __init__(self):
        self.score = 0
        self.length = 3

    def eat(self):
        self.length += 1

    def status(self):
        return {"score": self.score, "length": self.length}
