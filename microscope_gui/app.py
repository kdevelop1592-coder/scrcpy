"""
대물렌즈 / 현미경 전용 scrcpy 제어 GUI 프로그램
CustomTkinter 기반 모던 UI
"""
import os
import sys
import json
import customtkinter as ctk
from tkinter import messagebox
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


class MicroscopeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🔬 스마트폰 대물렌즈 / 현미경 모니터 컨트롤러")
        self.geometry("740x720")
        self.minsize(680, 650)

        self.manager = ScrcpyManager(DEFAULT_SCRCPY_DIR)

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

        # 4. 수동 초점 제어 안내 섹션
        focus_frame = ctk.CTkFrame(self, corner_radius=10)
        focus_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(focus_frame, text="🔍 수동 초점(Manual Focus) 미세 조절", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3B8ED0").grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 5), sticky="w")

        info_focus = (
            "• [Alt + Shift + O]: 초점 가까이 당기기 (Focus Nearer, 접사 방향)\n"
            "• [Alt + O]: 초점 멀리 밀기 (Focus Farther, 원경 방향)\n"
            "• [Alt + R]: 자동 초점(AF) 복원 및 리셋\n"
            "※ 초점 조절 키를 누르면 자동 초점(AF)이 즉시 비활성화되어 렌즈 떨림이 사라집니다."
        )
        focus_lbl = ctk.CTkLabel(focus_frame, text=info_focus, justify="left", font=ctk.CTkFont(size=12))
        focus_lbl.grid(row=1, column=0, columnspan=4, padx=15, pady=(0, 10), sticky="w")

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

    def stop_stream(self):
        self.manager.stop()
        self.start_btn.configure(text="🔬 대물렌즈 모니터링 시작", state="normal", fg_color="#2EA043")
        self.stop_btn.configure(state="disabled")
        self.log("스트림이 중지되었습니다.")

    def on_process_exit(self, code):
        self.start_btn.configure(text="🔬 대물렌즈 모니터링 시작", state="normal", fg_color="#2EA043")
        self.stop_btn.configure(state="disabled")
        self.log(f"scrcpy 프로세스가 종료되었습니다 (종료 코드: {code}).")


if __name__ == "__main__":
    app = MicroscopeApp()
    app.mainloop()
