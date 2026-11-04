"""
scrcpy 실행 및 프로세스 제어 모듈
"""
import subprocess
import os
import sys
import threading
from typing import List, Optional, Callable

class ScrcpyManager:
    def __init__(self, scrcpy_dir: str):
        self.scrcpy_dir = scrcpy_dir
        self.scrcpy_exe = os.path.join(scrcpy_dir, "scrcpy.exe")
        self.adb_exe = os.path.join(scrcpy_dir, "adb.exe")
        self.process: Optional[subprocess.Popen] = None
        self.monitor_thread: Optional[threading.Thread] = None

    def get_devices(self) -> List[str]:
        """연결된 ADB 디바이스 목록 반환"""
        if not os.path.exists(self.adb_exe):
            return []
        try:
            res = subprocess.run(
                [self.adb_exe, "devices"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            devices = []
            for line in res.stdout.strip().splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return devices
        except Exception as e:
            print(f"Error checking devices: {e}")
            return []

    def get_camera_list(self, device_serial: Optional[str] = None) -> List[str]:
        """--list-cameras 결과 반환"""
        if not os.path.exists(self.scrcpy_exe):
            return []
        cmd = [self.scrcpy_exe, "--video-source=camera", "--list-cameras"]
        if device_serial:
            cmd.extend(["-s", device_serial])
        
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.scrcpy_dir,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            # scrcpy는 목록 출력을 stderr 또는 stdout으로 보냄
            output = (res.stdout or "") + "\n" + (res.stderr or "")
            lines = [l.strip() for l in output.splitlines() if l.strip()]
            return lines
        except Exception as e:
            return [f"Error listing cameras: {e}"]

    def cleanup_device_server(self, device_serial: Optional[str] = None):
        """기기(Android)에 남아 있는 scrcpy-server 잔여 프로세스 및 포트 정리"""
        if not os.path.exists(self.adb_exe):
            return
        base_cmd = [self.adb_exe]
        if device_serial:
            base_cmd.extend(["-s", device_serial])

        try:
            # 1. scrcpy-server 프로세스 강제 종료
            pkill_cmd = base_cmd + ["shell", "pkill -f app_process.*scrcpy || killall scrcpy-server || true"]
            subprocess.run(
                pkill_cmd,
                capture_output=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
        except Exception:
            pass

    def start_microscope(
        self,
        camera_id: str = "0",
        orientation: str = "0",
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
        camera_size: Optional[str] = None,
        camera_fps: Optional[int] = 30,
        video_bit_rate: Optional[str] = "12M",
        turn_screen_off: bool = False,
        no_audio: bool = True,
        stay_awake: bool = True,
        device_serial: Optional[str] = None,
        custom_args: Optional[List[str]] = None,
        on_exit_callback: Optional[Callable[[int], None]] = None,
        on_log_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """대물렌즈 모니터링 실행"""
        if self.is_running():
            self.stop(device_serial=device_serial)
        else:
            self.cleanup_device_server(device_serial=device_serial)

        # 회전 및 반전 처리
        # scrcpy capture-orientation은 0, 90, 180, 270 또는 flip0, flip90, flip180, flip270 (수평 반전 + 회전)
        # 만약 flip_vertical(상하 반전)이 체크되면: flip180(상하반전 효과)와 결합
        # 세부 매핑:
        deg = int(orientation) % 360
        # 기본 flip은 가로반전(H)
        # 상하반전(V)은 가로반전(H) + 180도 회전과 동치
        is_flipped_h = flip_horizontal ^ flip_vertical
        if flip_vertical:
            deg = (deg + 180) % 360

        prefix = "flip" if is_flipped_h else ""
        capture_orient = f"{prefix}{deg}"

        cmd = [
            self.scrcpy_exe,
            "--video-source=camera",
            f"--camera-id={camera_id}",
            f"--capture-orientation={capture_orient}",
            "--window-title=Microscope Camera Stream",
            "--mouse=sdk",
            "--video-buffer=0"  # 지연 최소화
        ]

        if no_audio:
            cmd.append("--no-audio")
        if camera_size:
            cmd.append(f"--camera-size={camera_size}")
        if camera_fps and camera_fps > 0:
            cmd.append(f"--camera-fps={camera_fps}")
        if video_bit_rate:
            cmd.append(f"--video-bit-rate={video_bit_rate}")
        if turn_screen_off:
            cmd.append("--turn-screen-off")
        if stay_awake:
            cmd.append("--stay-awake")
        if device_serial:
            cmd.extend(["-s", device_serial])
        if custom_args:
            cmd.extend(custom_args)

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=self.scrcpy_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            proc = self.process

            def _watch():
                try:
                    for line in iter(proc.stdout.readline, ''):
                        if line:
                            text = line.rstrip()
                            if on_log_callback:
                                on_log_callback(text)
                    proc.stdout.close()
                    proc.wait()
                    code = proc.returncode
                except Exception:
                    code = -1
                if self.process is proc:
                    self.process = None
                self.cleanup_device_server(device_serial=device_serial)
                if on_exit_callback:
                    on_exit_callback(code)

            self.monitor_thread = threading.Thread(target=_watch, daemon=True)
            self.monitor_thread.start()
            return True
        except Exception as e:
            print(f"Failed to start scrcpy: {e}")
            return False

    def stop(self, device_serial: Optional[str] = None):
        """실행 중인 scrcpy 종료 및 정리"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        # 기기 내부의 scrcpy-server 데몬도 함께 강제 정리
        self.cleanup_device_server(device_serial=device_serial)

        # 남은 좀비 scrcpy 프로세스가 있다면 정리
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "scrcpy.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None
