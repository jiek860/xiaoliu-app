# -*- coding: utf-8 -*-
"""Windows Job Object wrapper for child-process containment.

A Job Object is what makes "kill the whole process tree" and basic memory/CPU/
process-count limits reliable on Windows. On non-Windows this module returns a
no-op object; callers must still use shell=False, timeouts and process-group
cleanup from their transport layer.
"""
from __future__ import annotations

import ctypes
import os
import sys

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class WindowsJob:
    def __init__(self, *, max_memory_mb=1024, max_cpu_seconds=0,
                 max_processes=8, kill_on_close=True):
        self.handle = None
        self.error = ""
        self.max_memory_mb = int(max_memory_mb or 0)
        self.max_cpu_seconds = int(max_cpu_seconds or 0)
        self.max_processes = int(max_processes or 0)
        self.kill_on_close = bool(kill_on_close)
        if IS_WINDOWS:
            self._create()

    @property
    def active(self):
        return bool(self.handle)

    def _create(self):
        try:
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                self.error = "CreateJobObject failed: %s" % ctypes.get_last_error()
                return
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            flags = 0
            if self.kill_on_close:
                flags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if self.max_memory_mb > 0:
                flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
                info.ProcessMemoryLimit = self.max_memory_mb * 1024 * 1024
                info.JobMemoryLimit = self.max_memory_mb * 1024 * 1024
            if self.max_cpu_seconds > 0:
                flags |= JOB_OBJECT_LIMIT_PROCESS_TIME
                info.BasicLimitInformation.PerProcessUserTimeLimit = (
                    self.max_cpu_seconds * 10_000_000)
                info.BasicLimitInformation.PerJobUserTimeLimit = (
                    self.max_cpu_seconds * 10_000_000)
            if self.max_processes > 0:
                flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                info.BasicLimitInformation.ActiveProcessLimit = self.max_processes
            info.BasicLimitInformation.LimitFlags = flags
            ok = _kernel32.SetInformationJobObject(
                self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info))
            if not ok:
                self.error = "SetInformationJobObject failed: %s" % ctypes.get_last_error()
        except Exception as exc:  # pragma: no cover - Windows API failure path
            self.error = str(exc)[:200]
            self.handle = None

    def attach(self, pid):
        if not IS_WINDOWS:
            return {"ok": True, "active": False, "error": "not windows"}
        if not self.handle:
            return {"ok": False, "active": False, "error": self.error or "no job handle"}
        process = None
        try:
            process = _kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
            if not process:
                return {"ok": False, "active": True,
                        "error": "OpenProcess failed: %s" % ctypes.get_last_error()}
            ok = _kernel32.AssignProcessToJobObject(self.handle, process)
            if not ok:
                return {"ok": False, "active": True,
                        "error": "AssignProcessToJobObject failed: %s"
                                 % ctypes.get_last_error()}
            return {"ok": True, "active": True, "error": ""}
        finally:
            if process:
                _kernel32.CloseHandle(process)

    def terminate(self, exit_code=1):
        if not IS_WINDOWS or not self.handle:
            return False
        try:
            return bool(_kernel32.TerminateJobObject(self.handle, int(exit_code)))
        except Exception:
            return False

    def close(self):
        if IS_WINDOWS and self.handle:
            try:
                _kernel32.CloseHandle(self.handle)
            except Exception:  # 静默是故意的
                pass
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def available():
    return IS_WINDOWS
