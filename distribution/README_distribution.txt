Microscope Controller 1.00
=============================
Smartphone-as-microscope controller built on scrcpy (camera mode).
스마트폰 카메라를 대물렌즈/현미경처럼 쓰기 위한 scrcpy 기반 컨트롤러입니다.

[Requirements / 준비물]
1. Android phone + USB cable / 안드로이드 폰과 USB 케이블
2. Enable USB debugging on the phone / 폰에서 USB 디버깅 켜기
   (Settings > About phone > tap "Build number" 7 times > Developer options > USB debugging)
   (설정 > 휴대전화 정보 > 빌드 번호 7번 터치 > 개발자 옵션 > USB 디버깅)
3. LG phones: install the LG USB driver if the device is not detected.
   LG 폰: 기기가 인식되지 않으면 LG USB 드라이버를 설치하세요.
4. Allow the "USB debugging" prompt on the phone when first connected.
   처음 연결할 때 폰의 "USB 디버깅 허용" 팝업을 허용하세요.

[Usage / 사용법]
1. Connect the phone, click "새로고침" (Refresh) to find the device.
2. Choose the camera ID (use "카메라 스캔" to list cameras), resolution and FPS.
3. Click "대물렌즈 모니터링 시작".

[Controls on the stream window / 스트림 창 조작]
- Mouse wheel      : zoom in / out  (휠: 줌 인/아웃)
- Left click       : tap-to-focus   (클릭: 해당 지점 초점)
- Middle click     : reset zoom     (휠 클릭: 줌 복원)
- Alt+Shift+O / Alt+O : manual focus nearer / farther
- Alt+R            : reset auto focus
- Alt+T / Alt+Shift+T : torch on / off

[Notes / 참고]
- Tap-to-focus works by writing a small file to the phone:
  /data/local/tmp/mic_focus.txt (via adb). It can be deleted safely.
  탭 포커스는 adb로 폰에 /data/local/tmp/mic_focus.txt 파일을 기록하는 방식입니다.
- A global mouse hook is used only while the stream window is under the cursor,
  to capture wheel/middle-click events. 스트림 창 위의 휠/휠클릭 입력을 가로채기 위해 사용합니다.
- Windows SmartScreen may warn about an unknown publisher because the installer is
  not code-signed. Click "More info" > "Run anyway".
  설치 파일에 코드 서명이 없어 "알 수 없는 게시자" 경고가 나올 수 있습니다. "추가 정보" > "실행"을 누르세요.
- Settings are stored in %APPDATA%\MicroscopeController.

[License / 라이선스]
This package bundles a MODIFIED version of scrcpy (Apache License 2.0).
See LICENSE-scrcpy.txt and MODIFICATIONS.txt.
수정된 scrcpy(Apache 2.0)가 포함되어 있습니다. LICENSE-scrcpy.txt, MODIFICATIONS.txt 참고.
