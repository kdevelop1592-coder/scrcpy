"""
전용 스레드에서 동작하는 저수준 마우스 훅 (스트림 창 위 휠 / 휠 클릭 가로채기).
Tk 메인 스레드와 분리하여 훅 타임아웃으로 인한 훅 자동 해제를 방지한다.
이벤트는 queue에 넣고 메인 스레드가 처리한다.
"""
import ctypes
import queue
import threading
from ctypes import wintypes

WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
WM_MBUTTONDOWN = 0x0207
WM_QUIT = 0x0012
GA_ROOT = 2

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class WheelHook(threading.Thread):
    def __init__(self, window_title, is_active, events: "queue.Queue", log=None):
        super().__init__(daemon=True)
        self.window_title = window_title
        self.is_active = is_active
        self.events = events
        self.log = log or (lambda m: None)
        self.thread_id = None
        self._hook = None
        self._proc = HOOKPROC(self._handler)

    def _title_under_cursor(self, pt):
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return ""
        root = user32.GetAncestor(hwnd, GA_ROOT)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(root, buf, 256)
        return buf.value

    def _handler(self, nCode, wParam, lParam):
        try:
            if nCode >= 0 and (wParam == WM_MOUSEWHEEL or wParam == WM_MBUTTONDOWN) and self.is_active():
                info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if self.window_title in self._title_under_cursor(info.pt):
                    if wParam == WM_MOUSEWHEEL:
                        delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                        self.events.put(("wheel", delta > 0))
                    else:
                        self.events.put(("reset", True))
                    return 1  # 스트림 창에는 전달하지 않음
        except Exception as e:
            self.log(f"hook error: {e!r}")
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self.log(f"hook installed: {self._hook}")
        if not self._hook:
            self.log(f"hook install failed: {ctypes.get_last_error()}")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
