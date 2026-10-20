# -*- coding: utf-8 -*-
"""Minimal isolated plugin example.

The plugin receives only this restricted context:
  ctx.files, ctx.network, ctx.process, ctx.config, ctx.audit
There is no trunk, os, subprocess or raw file-system access.
"""


class HelloPlugin:
    VERSION = "1.0.0"
    CAPABILITIES = {
        "filesystem": {"read": ["data/plugin_data/hello/notes"],
                       "write": ["data/plugin_data/hello/notes"]},
        "config": {"public_keys": ["theme"]},
    }

    def run(self, ctx):
        ctx.files.write("notes/hello.txt", "hello from an isolated plugin")
        text = ctx.files.read("notes/hello.txt")
        ctx.audit.record("hello plugin ran")
        return {"ok": True, "text": text, "theme": ctx.config.get_public("theme")}
