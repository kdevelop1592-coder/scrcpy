import os
import sys
import shutil
import subprocess
import time
import re

# Windows 기본 터미널(cp949) 이모지 인코딩 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "distribution")
OUTPUT_DIR = os.path.join(DIST_DIR, "output")
BUILD_DIR = os.path.join(DIST_DIR, "build")
APP_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "MicroscopeController")
SCRCPY_SRC = os.path.join(BASE_DIR, "release", "scrcpy-win64-v5.0.1", "scrcpy-win64-v5.0.1")
ISCC_PATH = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
SPEC_FILE = os.path.join(DIST_DIR, "microscope.spec")
ISS_FILE = os.path.join(DIST_DIR, "installer.iss")
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
APP_PY_FILE = os.path.join(BASE_DIR, "microscope_gui", "app.py")
README_DIST_FILE = os.path.join(DIST_DIR, "README_distribution.txt")


def print_step(step_num: int, total_steps: int, title: str):
    print(f"\n{'='*60}")
    print(f"[{step_num}/{total_steps}] {title}")
    print(f"{'='*60}")


def get_current_version() -> str:
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    return "1.00"


def bump_version(current_ver: str, bump_type: str = "patch") -> str:
    """
    버전 증가 함수 (예: 1.00 -> 1.01 -> 1.02, 또는 1.10)
    """
    parts = current_ver.split(".")
    if len(parts) == 2:
        major, minor = int(parts[0]), int(parts[1])
        if bump_type == "major":
            return f"{major + 1}.00"
        else:
            return f"{major}.{minor + 1:02d}"
    elif len(parts) == 3:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"
    return current_ver


def update_source_versions(version: str):
    """VERSION 파일 및 관련 소스코드, 인스톨러 설정 파일의 버전 동기화"""
    # 1. VERSION 파일
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(version + "\n")
    print(f"  - VERSION 파일 업데이트: {version}")

    # 2. microscope_gui/app.py의 APP_VERSION 업데이트
    if os.path.exists(APP_PY_FILE):
        with open(APP_PY_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = re.sub(
            r'APP_VERSION\s*=\s*["\'][^"\']+["\']',
            f'APP_VERSION = "{version}"',
            content
        )
        with open(APP_PY_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  - app.py APP_VERSION 업데이트: {version}")

    # 3. installer.iss의 MyAppVersion 업데이트
    if os.path.exists(ISS_FILE):
        with open(ISS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = re.sub(
            r'#define\s+MyAppVersion\s+["\'][^"\']+["\']',
            f'#define MyAppVersion "{version}"',
            content
        )
        with open(ISS_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  - installer.iss MyAppVersion 업데이트: {version}")

    # 4. README_distribution.txt 첫 줄 업데이트
    if os.path.exists(README_DIST_FILE):
        with open(README_DIST_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if lines:
            lines[0] = f"Microscope Controller {version}\n"
            with open(README_DIST_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"  - README_distribution.txt 업데이트: v{version}")


def select_version_menu() -> str:
    current_ver = get_current_version()
    next_patch = bump_version(current_ver, "patch")
    next_major = bump_version(current_ver, "major")

    print("\n" + "-" * 50)
    print(f"📌 현재 버전: v{current_ver}")
    print(f"  [1] 현재 버전 유지 (v{current_ver})")
    print(f"  [2] 패치 버전 업   (v{next_patch})")
    print(f"  [3] 메이저 버전 업 (v{next_major})")
    print("  [4] 직접 버전 입력")
    print("-" * 50)

    # CLI 인자가 주어졌을 경우 (예: python deploy.py 1.05)
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg in ["1", "keep"]:
            chosen = current_ver
        elif arg in ["2", "patch"]:
            chosen = next_patch
        elif arg in ["3", "major"]:
            chosen = next_major
        else:
            chosen = arg
        print(f"인자로 선택된 버전: v{chosen}")
        return chosen

    if not sys.stdin.isatty():
        return current_ver

    choice = input("선택하세요 [기본값: 1]: ").strip()
    if choice == "2":
        chosen = next_patch
    elif choice == "3":
        chosen = next_major
    elif choice == "4":
        custom = input("새 버전 입력 (예: 1.01): ").strip()
        chosen = custom if custom else current_ver
    else:
        chosen = current_ver

    return chosen


def clean_previous_builds():
    print_step(1, 4, "이전 빌드 출력 디렉토리 정리...")
    for folder in [OUTPUT_DIR, BUILD_DIR]:
        if os.path.exists(folder):
            print(f"  - 삭제 중: {folder}")
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except Exception as e:
                print(f"    [경고] 삭제 실패: {e}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("  -> 정리 완료")


def run_pyinstaller():
    print_step(2, 4, "PyInstaller 실행 (GUI 실행 파일 및 의존성 패키징)...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        SPEC_FILE,
        "--noconfirm",
        f"--distpath={OUTPUT_DIR}",
        f"--workpath={BUILD_DIR}",
    ]
    res = subprocess.run(cmd, cwd=DIST_DIR)
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller 패키징 실패 (코드: {res.returncode})")
    print("  -> PyInstaller 패키징 완료")


def copy_scrcpy_bundle():
    print_step(3, 4, "scrcpy 바이너리 및 라이선스 문서 번들링...")
    if not os.path.exists(os.path.join(SCRCPY_SRC, "scrcpy.exe")):
        raise FileNotFoundError(f"scrcpy 원본 폴더를 찾을 수 없습니다: {SCRCPY_SRC}")

    dest_scrcpy = os.path.join(APP_OUTPUT_DIR, "scrcpy")
    if os.path.exists(dest_scrcpy):
        shutil.rmtree(dest_scrcpy, ignore_errors=True)

    def ignore_patterns(folder, files):
        ignored = []
        for f in files:
            if f.endswith(".bak") or f in ["scrcpy-noconsole.vbs", "open_a_terminal_here.bat"]:
                ignored.append(f)
        return ignored

    print(f"  - scrcpy 번들 복사: {SCRCPY_SRC} -> {dest_scrcpy}")
    shutil.copytree(SCRCPY_SRC, dest_scrcpy, ignore=ignore_patterns)

    docs = [
        (os.path.join(BASE_DIR, "LICENSE"), os.path.join(APP_OUTPUT_DIR, "LICENSE-scrcpy.txt")),
        (os.path.join(DIST_DIR, "README_distribution.txt"), os.path.join(APP_OUTPUT_DIR, "README.txt")),
        (os.path.join(DIST_DIR, "MODIFICATIONS.txt"), os.path.join(APP_OUTPUT_DIR, "MODIFICATIONS.txt")),
    ]
    for src, dst in docs:
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  - 문서 복사: {os.path.basename(dst)}")

    print("  -> 번들 복사 완료")


def run_inno_setup(version: str):
    print_step(4, 4, f"Inno Setup 설치 프로그램 생성 (Setup v{version})...")
    if not os.path.exists(ISCC_PATH):
        raise FileNotFoundError(f"Inno Setup 컴파일러(ISCC.exe)를 찾을 수 없습니다: {ISCC_PATH}")

    # Inno Setup 커맨드라인에서 버전 매크로 오버라이드 지원 (/DMyAppVersion=...)
    cmd = [ISCC_PATH, f"/DMyAppVersion={version}", ISS_FILE]
    res = subprocess.run(cmd, cwd=DIST_DIR)
    if res.returncode != 0:
        raise RuntimeError(f"Inno Setup 빌드 실패 (코드: {res.returncode})")

    setup_exe = os.path.join(OUTPUT_DIR, f"MicroscopeController_Setup_{version}.exe")
    if os.path.exists(setup_exe):
        size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
        print(f"\n  -> [성공] 설치 파일 생성 완료: {setup_exe} ({size_mb:.2f} MB)")
    else:
        print("\n  -> [완료] Inno Setup 프로세스 정상 종료")


def main():
    print("\n" + "#" * 60)
    print("🔬 Microscope Controller 배포 자동화")
    print("#" * 60)

    target_version = select_version_menu()
    print(f"\n🚀 [배포 시작] 대상 버전: v{target_version}")
    update_source_versions(target_version)

    start_time = time.time()
    try:
        clean_previous_builds()
        run_pyinstaller()
        copy_scrcpy_bundle()
        run_inno_setup(target_version)

        elapsed = time.time() - start_time
        print(f"\n✨ v{target_version} 배포 작업이 성공적으로 완료되었습니다! (소요 시간: {elapsed:.1f}초)")
        print(f"📁 결과물 폴더: {OUTPUT_DIR}")

    except Exception as e:
        print(f"\n❌ [오류] 배포 중 문제가 발생했습니다: {e}")
        sys.exit(1)

    print("\nPress Enter to exit...")
    if sys.stdin.isatty():
        input()


if __name__ == "__main__":
    main()
