# -*- coding: utf-8 -*-
"""MCP-like server that floods stdout; used by containment tests."""
import sys
import time

sys.stdout.write("X" * (2 * 1024 * 1024) + "\n")
sys.stdout.flush()
time.sleep(5)
