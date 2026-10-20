# -*- coding: utf-8 -*-
"""RAG and team management dialog construction tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"workspace_id": "default"}


def test_rag_dialog_constructs_and_reports_stats(tmp_path, qapp):
    from gui.rag_dialog import RAGDialog
    d = RAGDialog(_Trunk(tmp_path))
    try:
        assert "来源" in d.stats.text()
        assert d._kb().stats()["chunks"] == 0
    finally:
        d.close()


def test_team_dialog_constructs_and_lists_owner(tmp_path, qapp):
    from gui.team_dialog import TeamDialog
    d = TeamDialog(_Trunk(tmp_path))
    try:
        assert d.table.rowCount() >= 1
        assert d.table.item(0, 2).text() == "owner"
    finally:
        d.close()
