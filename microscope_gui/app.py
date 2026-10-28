"""
대물렌즈 / 현미경 전용 scrcpy 제어 GUI 프로그램
CustomTkinter 기반 모던 UI
"""
import os
import sys
import json
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import ctypes
from ctypes import wintypes
from scrcpy_manager import ScrcpyManager

# 테마 설정
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# 기본 scrcpy 경로 (v5.0.1 폴더 탐색)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCRCPY_DIR = os.path.abspath(
    os.path.join(BASE_DIR, "..", "release", "scrcpy-win64-v5.0.1", "scrcpy-win64-v5.0.1")
)
CONFIG_FILE = os.path.join(BASE_DIR, "microscope_config.json")


class ZoomHUD(tk.Toplevel):
    """카메라 스트림 창 우측에 부착되는 반투명 마우스 드래그 줌 HUD 슬라이더"""
    def __init__(self, master=None, on_zoom_step=None):
        super().__init__(master)
        self.on_zoom_step = on_zoom_step
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.88)
        self.config(bg="#161B22")

        # WS_EX_NOACTIVATE 스타일 적용하여 클릭 시에도 scrcpy 창 포커스 유지
        try:
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            hwnd = int(self.winfo_id())
            current_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style | WS_EX_NOACTIVATE)
        except Exception:
            pass

        self.zoom_val = 1.0
        self.min_zoom = 1.0
        self.max_zoom = 8.0

        self.title_lbl = tk.Label(self, text="🔍 ZOOM", font=("Consolas", 8, "bold"), fg="#58A6FF", bg="#161B22")
        self.title_lbl.pack(pady=(6, 2))

        self.val_lbl = tk.Label(self, text="1.0x", font=("Consolas", 10, "bold"), fg="#00FFCC", bg="#161B22")
        self.val_lbl.pack(pady=(0, 4))

        self.c_w = 36
        self.c_h = 150
        self.canvas = tk.Canvas(self, width=self.c_w, height=self.c_h, bg="#0D1117", highlightthickness=1, highlightbackground="#30363D")
        self.canvas.pack(padx=6, pady=(0, 6))

        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Button-1>", self._on_drag)
        self.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        self._draw_slider()

    def _draw_slider(self):
        self.canvas.delete("all")
        mid_x = self.c_w // 2
        # 배경 트랙 라인
        self.canvas.create_line(mid_x, 12, mid_x, self.c_h - 12, fill="#30363D", width=4, capstyle="round")

        # 게이지 채우기
        ratio = (self.zoom_val - self.min_zoom) / (self.max_zoom - self.min_zoom)
        thumb_y = int((self.c_h - 12) - ratio * (self.c_h - 24))

        self.canvas.create_line(mid_x, self.c_h - 12, mid_x, thumb_y, fill="#00FFCC", width=4, capstyle="round")

        # 조절 핸들
        r = 6
        self.canvas.create_oval(mid_x - r, thumb_y - r, mid_x + r, thumb_y + r, fill="#FFFFFF", outline="#00FFCC", width=2)
        self.val_lbl.config(text=f"{self.zoom_val:.1f}x")

    def _on_drag(self, event):
        y = max(12, min(self.c_h - 12, event.y))
        ratio = 1.0 - (y - 12) / (self.c_h - 24)
        target_zoom = self.min_zoom + ratio * (self.max_zoom - self.min_zoom)
        self.apply_zoom_delta(target_zoom)

    def _on_wheel(self, event):
        step = 0.3 if event.delta > 0 else -0.3
        self.apply_zoom_delta(self.zoom_val + step)

    def apply_zoom_delta(self, target_val):
        target_val = max(self.min_zoom, min(self.max_zoom, target_val))
        diff = target_val - self.zoom_val
        if abs(diff) >= 0.15:
            zoom_in = diff > 0
            steps = max(1, int(abs(diff) / 0.2))
            self.zoom_val = target_val
            self._draw_slider()
            if self.on_zoom_step:
                for _ in range(steps):
                    self.on_zoom_step(zoom_in)


class MicroscopeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🔬 스마트폰 대물렌즈 / 현미경 모니터 컨트롤러")
        self.geometry("820x820")
        self.minsize(780, 750)

        self.manager = ScrcpyManager(DEFAULT_SCRCPY_DIR)

        # 포커스 시각 피드백(HUD & 커서) 관리
        self.cursor_cross = ctypes.windll.user32.LoadCursorW(0, 32515) # IDC_CROSS
        self.mouse_was_down = False
        self.mbutton_was_down = False
        self.zoom_hud = None
        self.current_zoom_level = 1.0
        self.hook_handle = None
        import queue
        from wheel_hook import WheelHook
        self._hook_events = queue.Queue()
        self._wheel_hook = WheelHook("Microscope Camera Stream", self.manager.is_running, self._hook_events, self._dbg)
        self._wheel_hook.start()
        self.poll_click_feedback()

        # 설정값 로드
        self.config = self.load_config()

        # UI 생성
        self.create_widgets()
        self.refresh_devices()

    def load_config(self) -> dict:
        default = {
            "camera_id": "0",
            "orientation": "0",
            "flip_v": False,
            "flip_h": False,
            "resolution": "1920x1080",
            "fps": "30",
            "stay_awake": True
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default.update(data)
            except Exception:
                pass
        return default

    def save_config(self):
        data = {
            "camera_id": self.camera_id_entry.get().strip() or "0",
            "orientation": self.orientation_var.get(),
            "flip_v": self.flip_v_var.get(),
            "flip_h": self.flip_h_var.get(),
            "resolution": self.res_combobox.get(),
            "fps": self.fps_combobox.get(),
            "stay_awake": self.stay_awake_var.get()
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def create_widgets(self):
        # 상단 타이틀
        title_frame = ctk.CTkFrame(self, corner_radius=10)
        title_frame.pack(fill="x", padx=15, pady=10)

        title_label = ctk.CTkLabel(
            title_frame,
            text="🔬 Phone Lens Microscope Controller",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(pady=8)

        # 1. 기기 연결 섹션
        dev_frame = ctk.CTkFrame(self, corner_radius=10)
        dev_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(dev_frame, text="연결된 기기 (ADB):", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.device_combo = ctk.CTkComboBox(dev_frame, values=["기기 검색 중..."], width=300)
        self.device_combo.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        refresh_btn = ctk.CTkButton(dev_frame, text="🔄 새로고침", width=90, command=self.refresh_devices)
        refresh_btn.grid(row=0, column=2, padx=10, pady=10)

        # 2. 광학 및 렌즈 설정 (회전 / 반전 / 카메라 선택)
        lens_frame = ctk.CTkFrame(self, corner_radius=10)
        lens_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(lens_frame, text="대물렌즈 광학 보정 & 카메라 설정", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3B8ED0").grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 5), sticky="w")

        # 카메라 ID
        ctk.CTkLabel(lens_frame, text="카메라 ID:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.camera_id_entry = ctk.CTkEntry(lens_frame, width=90)
        self.camera_id_entry.insert(0, self.config.get("camera_id", "0"))
        self.camera_id_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        cam_scan_btn = ctk.CTkButton(lens_frame, text="📋 카메라 스캔", width=120, command=self.scan_cameras)
        cam_scan_btn.grid(row=1, column=2, padx=10, pady=5, sticky="w")

        # 광학 도립상 회전 보정
        ctk.CTkLabel(lens_frame, text="화면 회전 보정:").grid(row=2, column=0, padx=10, pady=8, sticky="w")
        
        self.orientation_var = ctk.StringVar(value=self.config.get("orientation", "0"))
        rot_frame = ctk.CTkFrame(lens_frame, fg_color="transparent")
        rot_frame.grid(row=2, column=1, columnspan=3, padx=10, pady=5, sticky="w")

        for deg in ["0", "90", "180", "270"]:
            rb = ctk.CTkRadioButton(rot_frame, text=f"{deg}°", variable=self.orientation_var, value=deg)
            rb.pack(side="left", padx=8)

        # 상하 / 좌우 반전
        ctk.CTkLabel(lens_frame, text="화면 반전 보정:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        flip_frame = ctk.CTkFrame(lens_frame, fg_color="transparent")
        flip_frame.grid(row=3, column=1, columnspan=3, padx=10, pady=5, sticky="w")

        self.flip_v_var = ctk.BooleanVar(value=self.config.get("flip_v", False))
        self.flip_v_cb = ctk.CTkCheckBox(flip_frame, text="↕ 상하 반전 (Vertical Flip)", variable=self.flip_v_var)
        self.flip_v_cb.pack(side="left", padx=(0, 15))

        self.flip_h_var = ctk.BooleanVar(value=self.config.get("flip_h", False))
        self.flip_h_cb = ctk.CTkCheckBox(flip_frame, text="↔ 좌우 반전 (Horizontal Flip)", variable=self.flip_h_var)
        self.flip_h_cb.pack(side="left")

        # 3. 비디오 해상도 & FPS
        vid_frame = ctk.CTkFrame(self, corner_radius=10)
        vid_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(vid_frame, text="해상도 및 화질 설정", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3B8ED0").grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 5), sticky="w")

        ctk.CTkLabel(vid_frame, text="해상도(Size):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.res_combobox = ctk.CTkComboBox(vid_frame, values=["1920x1080", "2560x1440", "3840x2160", "1280x720", "최대(Max)"], width=140)
        self.res_combobox.set(self.config.get("resolution", "1920x1080"))
        self.res_combobox.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(vid_frame, text="목표 FPS:").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.fps_combobox = ctk.CTkComboBox(vid_frame, values=["30", "24", "20", "15", "60"], width=90)
        self.fps_combobox.set(self.config.get("fps", "30"))
        self.fps_combobox.grid(row=1, column=3, padx=10, pady=5, sticky="w")

        # 편의 옵션
        self.stay_awake_var = ctk.BooleanVar(value=self.config.get("stay_awake", True))
        self.stay_awake_cb = ctk.CTkCheckBox(vid_frame, text="절전 모드 방지 (Stay Awake)", variable=self.stay_awake_var)
        self.stay_awake_cb.grid(row=2, column=0, columnspan=2, padx=10, pady=8, sticky="w")

        tip_lbl = ctk.CTkLabel(vid_frame, text="💡 카메라 스트림 중 단축키 Mod(Alt)+O 로 폰 화면을 끌 수 있습니다.", font=ctk.CTkFont(size=11), text_color="#8B949E")
        tip_lbl.grid(row=2, column=2, columnspan=2, padx=10, pady=8, sticky="w")

        # 4. 실시간 관찰 단축키 가이드 섹션
        shortcut_frame = ctk.CTkFrame(self, corner_radius=10)
        shortcut_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(
            shortcut_frame,
            text="⌨️ 관찰 창 실시간 조작 단축키 가이드",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3B8ED0"
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 8), sticky="w")

        # 2단 그리드로 단축키 카드 배치
        # 좌측: 초점 & 줌
        col1_frame = ctk.CTkFrame(shortcut_frame, fg_color="#1F2428", corner_radius=8)
        col1_frame.grid(row=1, column=0, padx=(12, 6), pady=(0, 10), sticky="nsew")

        ctk.CTkLabel(col1_frame, text="🔍 초점 및 확대 (Focus & Zoom)", font=ctk.CTkFont(weight="bold", size=12), text_color="#58A6FF").pack(anchor="w", padx=10, pady=(6, 4))
        
        shortcuts_left = [
            ("마우스 클릭 (Tap)", "클릭한 지점 중심 원샷 자동 포커스 (AF)"),
            ("마우스 휠 위 / 아래", "마우스 커서 위치 중심 줌인 / 줌아웃 (ROI 줌)"),
            ("휠 클릭 (가운데 버튼)", "1.0x 배율 복원 (기본 전체 화면 리셋)"),
            ("Alt + Shift + O", "수동 초점 가까이 당기기 (초근접 접사)"),
            ("Alt + O", "수동 초점 멀리 밀기 (원경)"),
            ("Alt + R", "자동 초점(AF) 전체 복원 / 리셋"),
            ("Alt + T / Shift+T", "카메라 플래시(토치) 켜기 / 끄기")
        ]
        for key, desc in shortcuts_left:
            row = ctk.CTkFrame(col1_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=key, font=ctk.CTkFont(family="Consolas", weight="bold", size=11), text_color="#F0883E", width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=desc, font=ctk.CTkFont(size=11), anchor="w").pack(side="left")

        # 우측: 화면 회전 & 전체화면 & 유틸
        col2_frame = ctk.CTkFrame(shortcut_frame, fg_color="#1F2428", corner_radius=8)
        col2_frame.grid(row=1, column=1, padx=(6, 12), pady=(0, 10), sticky="nsew")

        ctk.CTkLabel(col2_frame, text="🔄 화면 제어 & 디스플레이", font=ctk.CTkFont(weight="bold", size=12), text_color="#58A6FF").pack(anchor="w", padx=10, pady=(6, 4))

        shortcuts_right = [
            ("Alt + Shift + ↑ / ↓", "실시간 상하 반전 (Vertical Flip)"),
            ("Alt + Shift + ← / →", "실시간 좌우 반전 (Horizontal Flip)"),
            ("Alt + ← / →", "화면 90도 회전 (Rotate)"),
            ("F11  (or Alt + F)", "전체화면(Fullscreen) 토글"),
            ("Alt + G / Alt + W", "1:1 원본 비율 / 창 크기 맞춤")
        ]
        for key, desc in shortcuts_right:
            row = ctk.CTkFrame(col2_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=key, font=ctk.CTkFont(family="Consolas", weight="bold", size=11), text_color="#F0883E", width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=desc, font=ctk.CTkFont(size=11), anchor="w").pack(side="left")

        shortcut_frame.grid_columnconfigure(0, weight=1)
        shortcut_frame.grid_columnconfigure(1, weight=1)

        # 5. 관찰 실행 버튼 섹션
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=15, pady=10)

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="🔬 대물렌즈 모니터링 시작",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=45,
            fg_color="#2EA043",
            hover_color="#238636",
            command=self.toggle_stream
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.stop_btn = ctk.CTkButton(
            action_frame,
            text="⏹ 정지",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=45,
            width=120,
            fg_color="#DA3633",
            hover_color="#B62324",
            command=self.stop_stream,
            state="disabled"
        )
        self.stop_btn.pack(side="right", padx=(5, 0))

        # 5. 상태 / 로그 텍스트 박스
        self.log_box = ctk.CTkTextbox(self, height=120, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self.log("프로그램이 준비되었습니다.")

    def log(self, message: str):
        self.log_box.insert("end", f"> {message}\n")
        self.log_box.see("end")

    def refresh_devices(self):
        devices = self.manager.get_devices()
        if devices:
            self.device_combo.configure(values=devices)
            self.device_combo.set(devices[0])
            self.log(f"연결된 기기 발견: {', '.join(devices)}")
        else:
            self.device_combo.configure(values=["연결된 기기 없음"])
            self.device_combo.set("연결된 기기 없음")
            self.log("연결된 ADB 기기가 없습니다. USB 디버깅을 확인하세요.")

    def scan_cameras(self):
        serial = self.device_combo.get()
        if "연결된 기기 없음" in serial or not serial:
            serial = None
        self.log("기기의 카메라 목록을 검색하는 중...")
        lines = self.manager.get_camera_list(serial)
        for line in lines:
            self.log(f"  {line}")

    def toggle_stream(self):
        if self.manager.is_running():
            self.stop_stream()
            return

        self.save_config()
        cam_id = self.camera_id_entry.get().strip() or "0"
        orientation = self.orientation_var.get()
        flip_v = self.flip_v_var.get()
        flip_h = self.flip_h_var.get()
        res = self.res_combobox.get()
        size_arg = None if res == "최대(Max)" else res
        
        try:
            fps_val = int(self.fps_combobox.get())
        except ValueError:
            fps_val = 30

        serial = self.device_combo.get()
        if "연결된 기기 없음" in serial or not serial:
            serial = None

        flip_info = []
        if flip_v: flip_info.append("상하반전")
        if flip_h: flip_info.append("좌우반전")
        flip_str = f" [{', '.join(flip_info)}]" if flip_info else ""

        self.log(f"대물렌즈 스트림 시작: 카메라 ID={cam_id}, 회전={orientation}°{flip_str}, 해상도={res}, FPS={fps_val}")

        def on_exit(code):
            self.after(0, self.on_process_exit, code)

        success = self.manager.start_microscope(
            camera_id=cam_id,
            orientation=orientation,
            flip_horizontal=flip_h,
            flip_vertical=flip_v,
            camera_size=size_arg,
            camera_fps=fps_val,
            no_audio=True,
            stay_awake=self.stay_awake_var.get(),
            device_serial=serial,
            on_exit_callback=on_exit
        )

        if success:
            self.start_btn.configure(text="모니터링 실행 중...", state="disabled", fg_color="#6E7681")
            self.stop_btn.configure(state="normal")
            self.log("scrcpy 카메라 스트림 창이 실행되었습니다.")
        else:
            self.log("스트림 실행 실패. scrcpy 경로 또는 기기 연결 상태를 확인하세요.")

    def send_scrcpy_zoom(self, zoom_in: bool):
        """scrcpy 카메라 스트림 창에 Alt + UP/DOWN 키 입력 전송 (카메라 센서 디지털 줌)"""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Microscope Camera Stream")
            if hwnd:
                self._focus_window(hwnd)

            KEYEVENTF_KEYUP = 0x0002
            VK_MENU = 0xA4  # Alt (MOD)
            VK_UP = 0x26    # Zoom In
            VK_DOWN = 0x28  # Zoom Out

            vk_arrow = VK_UP if zoom_in else VK_DOWN
            ctypes.windll.user32.keybd_event(VK_MENU, 0x38, 0, 0)
            ctypes.windll.user32.keybd_event(vk_arrow, 0x48 if zoom_in else 0x50, 0x0001, 0)
            ctypes.windll.user32.keybd_event(vk_arrow, 0x48 if zoom_in else 0x50, 0x0001 | KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0x38, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            self._dbg(f"zoom send error: {e!r}")
            self.log(f"줌 전송 오류: {e}")

    def _focus_window(self, hwnd):
        """다른 프로세스의 창으로 확실히 포커스 이동 (키 입력이 scrcpy로 가도록)"""
        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_tid and fg_tid != cur_tid and user32.AttachThreadInput(cur_tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    def _drain_hook_events(self):
        """훅 스레드가 넣은 휠/휠클릭 이벤트를 메인 스레드에서 처리"""
        try:
            handled = 0
            while handled < 5:
                kind, val = self._hook_events.get_nowait()
                handled += 1
                self._dbg(f"event {kind} {val}")
                if kind == "wheel":
                    self.handle_wheel_zoom(val)
                else:
                    self.send_scrcpy_reset_zoom()
        except Exception as e:
            if type(e).__name__ != "Empty":
                self._dbg(f"drain error: {e!r}")

    def _dbg(self, msg):
        """진단 로그 (기본 비활성). 필요하면 아래 return 을 제거하면 hook_debug.log 에 기록됨"""
        return
        try:
            with open(os.path.join(BASE_DIR, "hook_debug.log"), "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def handle_wheel_zoom(self, zoom_in: bool):
        """마우스 휠 → 카메라 줌 (HUD 값과 동기화)"""
        self.log(f"휠 감지 → 줌 {'인' if zoom_in else '아웃'}")
        self._dbg(f"handle_wheel_zoom start in={zoom_in}")
        self.send_scrcpy_zoom(zoom_in)
        self._dbg("handle_wheel_zoom keys sent")
        if self.zoom_hud:
            h = self.zoom_hud
            h.zoom_val = max(h.min_zoom, min(h.max_zoom, h.zoom_val + (0.3 if zoom_in else -0.3)))
            h._draw_slider()

    def send_scrcpy_reset_zoom(self):
        """Alt + R 입력으로 오토포커스 및 줌 초기화"""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Microscope Camera Stream")
            if hwnd:
                self._focus_window(hwnd)

            KEYEVENTF_KEYUP = 0x0002
            VK_MENU = 0xA4  # Alt
            VK_R = 0x52

            ctypes.windll.user32.keybd_event(VK_MENU, 0x38, 0, 0)
            ctypes.windll.user32.keybd_event(VK_R, 0x13, 0, 0)
            ctypes.windll.user32.keybd_event(VK_R, 0x13, KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0x38, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            print(f"Reset zoom error: {e}")

    def _set_hmodule_restype(self):
        """GetModuleHandleW 반환값(64비트 핸들)이 잘리지 않도록 restype 지정"""
        ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return True

    def _install_mouse_hook(self):
        """스트림 창 위에서 휠 스크롤 발생 시 Alt+Up/Down 줌으로 가로채는 로우레벨 훅 설치"""
        WH_MOUSE_LL = 14
        WM_MOUSEWHEEL = 0x020A
        WM_MBUTTONDOWN = 0x0207

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)
            ]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        def low_level_mouse_handler(nCode, wParam, lParam):
            if nCode >= 0 and wParam == WM_MOUSEWHEEL:
                try:
                    _i = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    _h = ctypes.windll.user32.WindowFromPoint(_i.pt)
                    _r = ctypes.windll.user32.GetAncestor(_h, 2)
                    _b = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(_r, _b, 512)
                    with open(os.path.join(BASE_DIR, "hook_debug.log"), "a", encoding="utf-8") as _f:
                        _f.write(f"wheel pt=({_i.pt.x},{_i.pt.y}) root={_r} title={_b.value!r} running={self.manager.is_running()}\n")
                except Exception as _e:
                    with open(os.path.join(BASE_DIR, "hook_debug.log"), "a", encoding="utf-8") as _f:
                        _f.write(f"hook error: {_e!r}\n")
            if nCode >= 0 and self.manager.is_running():
                if wParam == WM_MOUSEWHEEL:
                    info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    hwnd = ctypes.windll.user32.WindowFromPoint(info.pt)
                    root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)
                    if root_hwnd != int(self.winfo_id()):
                        buff = ctypes.create_unicode_buffer(512)
                        ctypes.windll.user32.GetWindowTextW(root_hwnd, buff, 512)
                        if "Microscope Camera Stream" in buff.value:
                            # 휠 방향 판정
                            delta = ctypes.c_short(info.mouseData >> 16).value
                            self.after(0, self.handle_wheel_zoom, delta > 0)
                            return 1
                elif wParam == WM_MBUTTONDOWN:
                    info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    hwnd = ctypes.windll.user32.WindowFromPoint(info.pt)
                    root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)
                    if root_hwnd != int(self.winfo_id()):
                        buff = ctypes.create_unicode_buffer(512)
                        ctypes.windll.user32.GetWindowTextW(root_hwnd, buff, 512)
                        if "Microscope Camera Stream" in buff.value:
                            self.after(0, self.send_scrcpy_reset_zoom)
                            return 1
            return ctypes.windll.user32.CallNextHookEx(self.hook_handle, nCode, wParam, lParam)

        # 64비트 Windows에서 포인터/핸들 값이 잘리지 않도록 시그니처 지정
        user32 = ctypes.windll.user32
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK

        self._hook_proc = HOOKPROC(low_level_mouse_handler)
        self.hook_handle = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            ctypes.windll.kernel32.GetModuleHandleW(None) if self._set_hmodule_restype() else None,
            0
        )

    def stop_stream(self):
        if self.zoom_hud:
            try:
                self.zoom_hud.destroy()
            except Exception:
                pass
            self.zoom_hud = None
        self.manager.stop()
        self.start_btn.configure(text="🔬 대물렌즈 모니터링 시작", state="normal", fg_color="#2EA043")
        self.stop_btn.configure(state="disabled")
        self.log("스트림이 중지되었습니다.")

    def on_process_exit(self, code):
        if self.zoom_hud:
            try:
                self.zoom_hud.destroy()
            except Exception:
                pass
            self.zoom_hud = None
        self.start_btn.configure(text="🔬 대물렌즈 모니터링 시작", state="normal", fg_color="#2EA043")
        self.stop_btn.configure(state="disabled")
        self.log(f"scrcpy 프로세스가 종료되었습니다 (종료 코드: {code}).")

    def poll_click_feedback(self):
        """오직 scrcpy 카메라 스트림 화면(내부)을 클릭했을 때만 포커스 HUD 및 커서 피드백 제공"""
        try:
            if self.manager.is_running():
                VK_LBUTTON = 0x01
                is_pressed = (ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0

                if is_pressed and not self.mouse_was_down:
                    self.mouse_was_down = True
                    pt = wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

                    hwnd = ctypes.windll.user32.WindowFromPoint(pt)
                    root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2) # GA_ROOT

                    # 컨트롤러 GUI 창 자체이거나 다른 프로그램 창이면 무시
                    if root_hwnd != int(self.winfo_id()):
                        buff = ctypes.create_unicode_buffer(512)
                        ctypes.windll.user32.GetWindowTextW(root_hwnd, buff, 512)
                        title = buff.value

                        # scrcpy 카메라 스트림 윈도우 타이틀과 정확히 일치하거나 scrcpy SDL 창일 때만 작동
                        if "Microscope Camera Stream" in title:
                            # 윈도우의 클라이언트 영역(비디오 표시 화면 내부)인지 검사
                            rect = wintypes.RECT()
                            ctypes.windll.user32.GetClientRect(root_hwnd, ctypes.byref(rect))
                            pt_client = wintypes.POINT(pt.x, pt.y)
                            ctypes.windll.user32.ScreenToClient(root_hwnd, ctypes.byref(pt_client))

                            if 0 <= pt_client.x <= rect.right and 0 <= pt_client.y <= rect.bottom:
                                self.trigger_focus_feedback(pt.x, pt.y)
                elif not is_pressed:
                    self.mouse_was_down = False

                # 줌 HUD 슬라이더를 스트림 창 우측에 동기화
                self.sync_zoom_hud()
        except Exception:
            pass

        self._drain_hook_events()
        self.after(20, self.poll_click_feedback)

    def sync_zoom_hud(self):
        """스트림 창의 위치를 추적하여 줌 HUD 슬라이더를 우측에 배치"""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Microscope Camera Stream")
            if hwnd and ctypes.windll.user32.IsWindowVisible(hwnd) and not ctypes.windll.user32.IsIconic(hwnd):
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

                hud_w = 48
                hud_h = 200
                hud_x = rect.right - hud_w - 18
                hud_y = rect.top + (rect.bottom - rect.top) // 2 - hud_h // 2

                if not self.zoom_hud:
                    self.zoom_hud = ZoomHUD(self, on_zoom_step=self.send_scrcpy_zoom)
                
                self.zoom_hud.geometry(f"{hud_w}x{hud_h}+{hud_x}+{hud_y}")
                self.zoom_hud.deiconify()
            else:
                if self.zoom_hud:
                    self.zoom_hud.withdraw()
        except Exception:
            pass

    def trigger_focus_feedback(self, x: int, y: int):
        """클릭한 위치에 정밀 조준선 HUD 링 표시 및 십자선 커서 피드백"""
        try:
            # 1. 일시적 십자선 커서 변경
            ctypes.windll.user32.SetCursor(self.cursor_cross)

            # 2. 투명 오버레이 타겟팅 링 표시
            ring = tk.Toplevel(self)
            ring.overrideredirect(True)
            ring.attributes("-topmost", True)
            ring.attributes("-transparentcolor", "magenta")
            ring.config(bg="magenta")

            size = 72
            ring.geometry(f"{size}x{size}+{x - size//2}+{y - size//2}")

            canvas = tk.Canvas(ring, width=size, height=size, bg="magenta", highlightthickness=0)
            canvas.pack(fill="both", expand=True)

            mid = size // 2
            # 중앙 조준점 (민트그린)
            canvas.create_oval(mid-2, mid-2, mid+2, mid+2, fill="#00FFCC", outline="")
            # 원형 포커스 링
            canvas.create_oval(10, 10, size-10, size-10, outline="#00FFCC", width=2)
            # 4방향 십자 틱 마크
            t_len = 7
            canvas.create_line(mid, 4, mid, 4 + t_len, fill="#00FFCC", width=2)
            canvas.create_line(mid, size-4, mid, size-4 - t_len, fill="#00FFCC", width=2)
            canvas.create_line(4, mid, 4 + t_len, mid, fill="#00FFCC", width=2)
            canvas.create_line(size-4, mid, size-4 - t_len, mid, fill="#00FFCC", width=2)

            ring.after(350, ring.destroy)
        except Exception as e:
            print(f"Feedback error: {e}")


    def destroy(self):
        if self.hook_handle:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self.hook_handle)
            except Exception:
                pass
            self.hook_handle = None
        try:
            self._wheel_hook.stop()
        except Exception:
            pass
        super().destroy()


if __name__ == "__main__":
    app = MicroscopeApp()
    app.mainloop()
