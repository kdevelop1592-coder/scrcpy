package com.genymobile.scrcpy.video;

import com.genymobile.scrcpy.AndroidVersions;
import com.genymobile.scrcpy.Options;
import com.genymobile.scrcpy.model.ConfigurationException;
import com.genymobile.scrcpy.model.Orientation;
import com.genymobile.scrcpy.model.Size;
import com.genymobile.scrcpy.opengl.AffineOpenGLFilter;
import com.genymobile.scrcpy.opengl.OpenGLFilter;
import com.genymobile.scrcpy.opengl.OpenGLRunner;
import com.genymobile.scrcpy.util.AffineMatrix;
import com.genymobile.scrcpy.util.HandlerExecutor;
import com.genymobile.scrcpy.util.Ln;
import com.genymobile.scrcpy.util.LogUtils;
import com.genymobile.scrcpy.wrappers.ServiceManager;

import android.annotation.SuppressLint;
import android.annotation.TargetApi;
import android.graphics.Rect;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraConstrainedHighSpeedCaptureSession;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.MeteringRectangle;
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.camera2.params.SessionConfiguration;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodec;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Range;
import android.view.Surface;

import java.io.IOException;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.stream.Stream;

public class CameraCapture extends SurfaceCapture {

    public static final float[] VFLIP_MATRIX = {
            1, 0, 0, 0, // column 1
            0, -1, 0, 0, // column 2
            0, 0, 1, 0, // column 3
            0, 1, 0, 1, // column 4
    };

    private static final float ZOOM_FACTOR = 1 + 1 / 16f;

    private final String explicitCameraId;
    private final CameraFacing cameraFacing;
    private final Size explicitSize;
    private final CameraAspectRatio aspectRatio;
    private final int fps;
    private final boolean highSpeed;
    private final Rect crop;
    private final Orientation captureOrientation;
    private final float angle;
    private final boolean initialTorch;
    private float zoom;

    private VideoConstraints videoConstraints;

    private String cameraId;
    private Size captureSize;
    private Size videoSize; // after OpenGL transforms
    private Range<Float> zoomRange;
    private Float minFocusDistance;
    private Rect activeArraySize;
    private Float maxDigitalZoom;
    private float currentFocusDistance = 0.0f; // 0.0f = infinity (diopters)
    private float targetZoomLevel = 1.0f;
    private Rect currentCrop; // 현재 적용된 크롭 영역 (null = 전체 센서)
    private String lastFocusCmd;
    private float targetCenterXRatio = 0.5f;
    private float targetCenterYRatio = 0.5f;

    private AffineMatrix transform;
    private OpenGLRunner glRunner;

    private HandlerThread cameraThread;
    private Handler cameraHandler;
    private CameraDevice cameraDevice;
    private Executor cameraExecutor;

    private final AtomicBoolean disconnected = new AtomicBoolean();

    // The following fields must be accessed only from the camera thread
    private boolean started;
    private CaptureRequest.Builder requestBuilder;
    private CameraCaptureSession currentSession;

    public CameraCapture(Options options) {
        this.explicitCameraId = options.getCameraId();
        this.cameraFacing = options.getCameraFacing();
        this.explicitSize = options.getCameraSize();
        this.aspectRatio = options.getCameraAspectRatio();
        this.fps = options.getCameraFps();
        this.highSpeed = options.getCameraHighSpeed();
        this.crop = options.getCrop();
        this.captureOrientation = options.getCaptureOrientation();
        assert captureOrientation != null;
        this.angle = options.getAngle();
        this.initialTorch = options.getCameraTorch();
        this.zoom = options.getCameraZoom();
    }

    @Override
    protected void init(VideoConstraints videoConstraints) throws ConfigurationException, IOException {
        this.videoConstraints = videoConstraints;

        cameraThread = new HandlerThread("camera");
        cameraThread.start();
        cameraHandler = new Handler(cameraThread.getLooper());
        cameraExecutor = new HandlerExecutor(cameraHandler);

        try {
            cameraId = selectCamera(explicitCameraId, cameraFacing);
            if (cameraId == null) {
                throw new ConfigurationException("No matching camera found");
            }

            Ln.i("Using camera '" + cameraId + "'");
            cameraDevice = openCamera(cameraId);
        } catch (CameraAccessException | InterruptedException e) {
            throw new IOException(e);
        }
    }

    @Override
    public void prepare() throws IOException {
        try {
            int maxSize = videoConstraints.getMaxSize();
            captureSize = selectSize(cameraId, explicitSize, maxSize, aspectRatio, highSpeed);
            if (captureSize == null) {
                throw new IOException("Could not select camera size");
            }
        } catch (CameraAccessException e) {
            throw new IOException(e);
        }

        VideoFilter filter = new VideoFilter(captureSize);

        if (crop != null) {
            filter.addCrop(crop, false);
        }

        if (captureOrientation != Orientation.Orient0) {
            filter.addOrientation(captureOrientation);
        }

        filter.addAngle(angle);

        transform = filter.getInverseTransform();
        videoSize = filter.getOutputSize().align(videoConstraints.getAlignment());

        if (!videoSize.equals(captureSize) && transform == null) {
            // The camera stream can only be rendered on a surface matching the input size.
            // If the video constraints change the size, an intermediate OpenGL filter is required.
            transform = AffineMatrix.IDENTITY;
        }
    }

    private static String selectCamera(String explicitCameraId, CameraFacing cameraFacing) throws CameraAccessException, ConfigurationException {
        CameraManager cameraManager = ServiceManager.getCameraManager();

        String[] cameraIds = cameraManager.getCameraIdList();
        if (explicitCameraId != null) {
            if (!Arrays.asList(cameraIds).contains(explicitCameraId)) {
                Ln.e("Camera with id " + explicitCameraId + " not found\n" + LogUtils.buildCameraListMessage(false));
                throw new ConfigurationException("Camera id not found");
            }
            return explicitCameraId;
        }

        if (cameraFacing == null) {
            // Use the first one
            return cameraIds.length > 0 ? cameraIds[0] : null;
        }

        for (String cameraId : cameraIds) {
            CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);

            int facing = characteristics.get(CameraCharacteristics.LENS_FACING);
            if (cameraFacing.value() == facing) {
                return cameraId;
            }
        }

        // Not found
        return null;
    }

    @TargetApi(AndroidVersions.API_24_ANDROID_7_0)
    private static Size selectSize(String cameraId, Size explicitSize, int maxSize, CameraAspectRatio aspectRatio, boolean highSpeed)
            throws CameraAccessException {
        if (explicitSize != null) {
            return explicitSize;
        }

        CameraManager cameraManager = ServiceManager.getCameraManager();
        CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);

        StreamConfigurationMap configs = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        android.util.Size[] sizes = highSpeed ? configs.getHighSpeedVideoSizes() : configs.getOutputSizes(MediaCodec.class);
        if (sizes == null) {
            return null;
        }

        Stream<android.util.Size> stream = Arrays.stream(sizes);
        if (maxSize > 0) {
            stream = stream.filter(it -> it.getWidth() <= maxSize && it.getHeight() <= maxSize);
        }

        Float targetAspectRatio = resolveAspectRatio(aspectRatio, characteristics);
        if (targetAspectRatio != null) {
            stream = stream.filter(it -> {
                float ar = ((float) it.getWidth() / it.getHeight());
                float arRatio = ar / targetAspectRatio;
                // Accept if the aspect ratio is the target aspect ratio + or - 10%
                return arRatio >= 0.9f && arRatio <= 1.1f;
            });
        }

        Optional<android.util.Size> selected = stream.max((s1, s2) -> {
            // Greater width is better
            int cmp = Integer.compare(s1.getWidth(), s2.getWidth());
            if (cmp != 0) {
                return cmp;
            }

            if (targetAspectRatio != null) {
                // Closer to the target aspect ratio is better
                float ar1 = ((float) s1.getWidth() / s1.getHeight());
                float arRatio1 = ar1 / targetAspectRatio;
                float distance1 = Math.abs(1 - arRatio1);

                float ar2 = ((float) s2.getWidth() / s2.getHeight());
                float arRatio2 = ar2 / targetAspectRatio;
                float distance2 = Math.abs(1 - arRatio2);

                // Reverse the order because lower distance is better
                cmp = Float.compare(distance2, distance1);
                if (cmp != 0) {
                    return cmp;
                }
            }

            // Greater height is better
            return Integer.compare(s1.getHeight(), s2.getHeight());
        });

        if (selected.isPresent()) {
            android.util.Size size = selected.get();
            return new Size(size.getWidth(), size.getHeight());
        }

        // Not found
        return null;
    }

    private static Float resolveAspectRatio(CameraAspectRatio ratio, CameraCharacteristics characteristics) {
        if (ratio == null) {
            return null;
        }

        if (ratio.isSensor()) {
            Rect activeSize = characteristics.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            return (float) activeSize.width() / activeSize.height();
        }

        return ratio.getAspectRatio();
    }

    @TargetApi(AndroidVersions.API_30_ANDROID_11)
    @Override
    public void start(Surface surface) throws IOException {
        if (transform != null) {
            assert glRunner == null;
            OpenGLFilter glFilter = new AffineOpenGLFilter(transform);
            // The transform matrix returned by SurfaceTexture is incorrect for camera capture (it often contains an additional unexpected 90°
            // rotation). Use a vertical flip transform matrix instead.
            glRunner = new OpenGLRunner(glFilter, VFLIP_MATRIX);
            surface = glRunner.start(captureSize, videoSize, surface);
        }

        cameraHandler.post(() -> {
            assertCameraThread();
            started = true;
        });

        Surface captureSurface = surface;
        OutputConfiguration outputConfig = new OutputConfiguration(captureSurface);
        List<OutputConfiguration> outputs = Collections.singletonList(outputConfig);
        int sessionType = highSpeed ? SessionConfiguration.SESSION_HIGH_SPEED : SessionConfiguration.SESSION_REGULAR;
        SessionConfiguration sessionConfig = new SessionConfiguration(sessionType, outputs, cameraExecutor, new CameraCaptureSession.StateCallback() {
            @Override
            public void onConfigured(CameraCaptureSession session) {
                assertCameraThread();
                if (!started) {
                    // Stopped on the encoder thread between the call to start() and this callback
                    return;
                }

                CameraManager cameraManager = ServiceManager.getCameraManager();
                try {
                    CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);
                    zoomRange = characteristics.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE);
                    minFocusDistance = characteristics.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE);
                    activeArraySize = characteristics.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
                    maxDigitalZoom = characteristics.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM);
                    Ln.i("Camera characteristics - focusDist: " + minFocusDistance + ", activeArray: " + activeArraySize + ", maxDigitalZoom: " + maxDigitalZoom);
                } catch (CameraAccessException e) {
                    Ln.w("Could not get camera characteristics");
                }

                try {
                    requestBuilder = cameraDevice.createCaptureRequest(CameraDevice.TEMPLATE_RECORD);
                    requestBuilder.addTarget(captureSurface);

                    if (fps > 0) {
                        requestBuilder.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(fps, fps));
                    }
                    if (initialTorch) {
                        Ln.i("Turn camera torch on");
                        requestBuilder.set(CaptureRequest.FLASH_MODE, CaptureRequest.FLASH_MODE_TORCH);
                    }
                    if (zoom != 1) {
                        zoom = clampZoom(zoom);
                        Ln.i("Set camera zoom: " + zoom);
                        requestBuilder.set(CaptureRequest.CONTROL_ZOOM_RATIO, zoom);
                    }

                    CaptureRequest request = requestBuilder.build();
                    setRepeatingRequest(session, request);
                    currentSession = session;
                    startFocusFilePoll();
                } catch (CameraAccessException e) {
                    Ln.e("Camera error", e);
                    disconnected.set(true);
                    getCaptureControl().reset(CaptureControl.RESET_REASON_TERMINATED);
                }
            }

            @Override
            public void onConfigureFailed(CameraCaptureSession session) {
                Ln.e("Camera configuration error");
                disconnected.set(true);
                getCaptureControl().reset(CaptureControl.RESET_REASON_TERMINATED);
            }
        });

        try {
            cameraDevice.createCaptureSession(sessionConfig);
        } catch (CameraAccessException e) {
            stop();
            throw new IOException(e);
        }
    }

    @Override
    public void stop() {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null) {
                try {
                    currentSession.stopRepeating();
                } catch (CameraAccessException | IllegalStateException e) {
                    // The session may already be closed (for example if the camera has been disconnected)
                    Ln.d("Could not stop repeating capture request: " + e.getMessage());
                }
            }
            currentSession = null;
            requestBuilder = null;
            started = false;
        });

        if (glRunner != null) {
            glRunner.stopAndRelease();
            glRunner = null;
        }
    }

    @Override
    public void release() {
        if (cameraDevice != null) {
            cameraDevice.close();
        }
        if (cameraThread != null) {
            cameraThread.quitSafely();
        }
    }

    @Override
    public Size getSize() {
        return videoSize;
    }

    @Override
    protected boolean applyNewVideoConstraints(VideoConstraints videoConstraints) {
        if (explicitSize != null) {
            return false;
        }

        this.videoConstraints = videoConstraints;
        return true;
    }

    @SuppressLint("MissingPermission")
    @TargetApi(AndroidVersions.API_31_ANDROID_12)
    private CameraDevice openCamera(String id) throws CameraAccessException, InterruptedException {
        CompletableFuture<CameraDevice> future = new CompletableFuture<>();
        ServiceManager.getCameraManager().openCamera(id, new CameraDevice.StateCallback() {
            @Override
            public void onOpened(CameraDevice camera) {
                Ln.d("Camera opened successfully");
                future.complete(camera);
            }

            @Override
            public void onDisconnected(CameraDevice camera) {
                Ln.w("Camera disconnected");
                disconnected.set(true);
                getCaptureControl().reset(CaptureControl.RESET_REASON_TERMINATED);
            }

            @Override
            public void onError(CameraDevice camera, int error) {
                int cameraAccessExceptionErrorCode;
                switch (error) {
                    case CameraDevice.StateCallback.ERROR_CAMERA_IN_USE:
                        cameraAccessExceptionErrorCode = CameraAccessException.CAMERA_IN_USE;
                        break;
                    case CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE:
                        cameraAccessExceptionErrorCode = CameraAccessException.MAX_CAMERAS_IN_USE;
                        break;
                    case CameraDevice.StateCallback.ERROR_CAMERA_DISABLED:
                        cameraAccessExceptionErrorCode = CameraAccessException.CAMERA_DISABLED;
                        break;
                    case CameraDevice.StateCallback.ERROR_CAMERA_DEVICE:
                    case CameraDevice.StateCallback.ERROR_CAMERA_SERVICE:
                    default:
                        cameraAccessExceptionErrorCode = CameraAccessException.CAMERA_ERROR;
                        break;
                }
                future.completeExceptionally(new CameraAccessException(cameraAccessExceptionErrorCode));
            }
        }, cameraHandler);

        try {
            return future.get();
        } catch (ExecutionException e) {
            throw (CameraAccessException) e.getCause();
        }
    }

    @TargetApi(AndroidVersions.API_31_ANDROID_12)
    private void setRepeatingRequest(CameraCaptureSession session, CaptureRequest request) throws CameraAccessException {
        CameraCaptureSession.CaptureCallback callback = new CameraCaptureSession.CaptureCallback() {
            @Override
            public void onCaptureStarted(CameraCaptureSession session, CaptureRequest request, long timestamp, long frameNumber) {
                // Called for each frame captured, do nothing
            }

            @Override
            public void onCaptureFailed(CameraCaptureSession session, CaptureRequest request, CaptureFailure failure) {
                Ln.w("Camera capture failed: frame " + failure.getFrameNumber());
            }
        };

        if (highSpeed) {
            CameraConstrainedHighSpeedCaptureSession highSpeedSession = (CameraConstrainedHighSpeedCaptureSession) session;
            List<CaptureRequest> requests = highSpeedSession.createHighSpeedRequestList(request);
            highSpeedSession.setRepeatingBurst(requests, callback, cameraHandler);
        } else {
            session.setRepeatingRequest(request, callback, cameraHandler);
        }
    }

    @Override
    public boolean isClosed() {
        return disconnected.get();
    }

    public void setTorchEnabled(boolean enabled) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                try {
                    Ln.i("Turn camera torch " + (enabled ? "on" : "off"));
                    requestBuilder.set(CaptureRequest.FLASH_MODE, enabled ? CaptureRequest.FLASH_MODE_TORCH : CaptureRequest.FLASH_MODE_OFF);
                    CaptureRequest request = requestBuilder.build();
                    setRepeatingRequest(currentSession, request);
                } catch (CameraAccessException e) {
                    Ln.e("Camera error", e);
                }
            }
        });
    }

    @TargetApi(AndroidVersions.API_30_ANDROID_11)
    private void zoom(boolean in) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                // Always align to log values
                double z = Math.round(Math.log(zoom) / Math.log(ZOOM_FACTOR));
                double dir = in ? 1 : -1;
                zoom = (float) Math.pow(ZOOM_FACTOR, z + dir);

                try {
                    zoom = clampZoom(zoom);
                    Ln.i("Set camera zoom: " + zoom);
                    requestBuilder.set(CaptureRequest.CONTROL_ZOOM_RATIO, zoom);
                    CaptureRequest request = requestBuilder.build();
                    setRepeatingRequest(currentSession, request);
                } catch (CameraAccessException e) {
                    Ln.e("Camera error", e);
                }
            }
        });
    }

    public void zoomAt(com.genymobile.scrcpy.model.Position position, float scrollDelta) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                // 특정 지점 비율 업데이트
                if (position != null) {
                    com.genymobile.scrcpy.model.Point pt = position.getPoint();
                    com.genymobile.scrcpy.model.Size screenSize = position.getScreenSize();
                    if (screenSize.getWidth() > 0 && screenSize.getHeight() > 0) {
                        targetCenterXRatio = Math.max(0.05f, Math.min(0.95f, (float) pt.getX() / screenSize.getWidth()));
                        targetCenterYRatio = Math.max(0.05f, Math.min(0.95f, (float) pt.getY() / screenSize.getHeight()));
                    }
                }

                float factor = scrollDelta > 0 ? 1.15f : 0.87f;
                float newZoom = targetZoomLevel * factor;
                float maxZ = 10.0f;
                if (maxDigitalZoom != null && maxDigitalZoom > 1.0f) {
                    maxZ = maxDigitalZoom;
                } else if (zoomRange != null && zoomRange.getUpper() != null) {
                    maxZ = zoomRange.getUpper();
                }

                targetZoomLevel = Math.max(1.0f, Math.min(maxZ, newZoom));
                applyCropZoom();
            }
        });
    }

    public void pan(float deltaXRatio, float deltaYRatio) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                targetCenterXRatio = Math.max(0.05f, Math.min(0.95f, targetCenterXRatio + deltaXRatio));
                targetCenterYRatio = Math.max(0.05f, Math.min(0.95f, targetCenterYRatio + deltaYRatio));
                applyCropZoom();
            }
        });
    }

    public void resetZoom() {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                targetZoomLevel = 1.0f;
                targetCenterXRatio = 0.5f;
                targetCenterYRatio = 0.5f;
                applyCropZoom();
            }
        });
    }

    private void applyCropZoom() {
        assertCameraThread();
        Rect sensorRect = activeArraySize;
        if (sensorRect == null) {
            sensorRect = new Rect(0, 0, captureSize.getWidth(), captureSize.getHeight());
        }

        int origW = sensorRect.width();
        int origH = sensorRect.height();

        if (targetZoomLevel <= 1.02f) {
            // 1.0x 배율 복원: 전체 센서 영역으로 리셋
            try {
                Ln.i("Reset zoom to 1.0x (full frame)");
                currentCrop = null;
                requestBuilder.set(CaptureRequest.SCALER_CROP_REGION, sensorRect);
                CaptureRequest request = requestBuilder.build();
                setRepeatingRequest(currentSession, request);
            } catch (CameraAccessException e) {
                Ln.e("Reset zoom error", e);
            }
            return;
        }

        // 지점 중심의 크롭 사각형 계산
        int cropW = (int) (origW / targetZoomLevel);
        int cropH = (int) (origH / targetZoomLevel);

        int centerX = sensorRect.left + (int) (targetCenterXRatio * origW);
        int centerY = sensorRect.top + (int) (targetCenterYRatio * origH);

        int cropLeft = centerX - cropW / 2;
        int cropTop = centerY - cropH / 2;

        // 센서 경계 클램핑
        if (cropLeft < sensorRect.left) {
            cropLeft = sensorRect.left;
        } else if (cropLeft + cropW > sensorRect.right) {
            cropLeft = sensorRect.right - cropW;
        }

        if (cropTop < sensorRect.top) {
            cropTop = sensorRect.top;
        } else if (cropTop + cropH > sensorRect.bottom) {
            cropTop = sensorRect.bottom - cropH;
        }

        Rect cropRect = new Rect(cropLeft, cropTop, cropLeft + cropW, cropTop + cropH);
        currentCrop = cropRect;
        try {
            Ln.i(String.format("Apply point-centered zoom: %.2fx at (%.2f, %.2f) -> crop: %s", targetZoomLevel, targetCenterXRatio, targetCenterYRatio, cropRect));
            requestBuilder.set(CaptureRequest.SCALER_CROP_REGION, cropRect);
            CaptureRequest request = requestBuilder.build();
            setRepeatingRequest(currentSession, request);
        } catch (CameraAccessException e) {
            Ln.e("Apply point-centered zoom error", e);
        }
    }

    public void zoomIn() {
        zoomAt(null, 1f); // crop 기반 줌 (구형 기기 / CONTROL_ZOOM_RATIO 미지원 대응)
    }

    public void zoomOut() {
        zoomAt(null, -1f);
    }

    private float clampZoom(float value) {
        assertCameraThread();
        if (zoomRange == null) {
            return value;
        }

        return zoomRange.clamp(value);
    }

    public void adjustFocus(boolean nearer) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                float maxDist = (minFocusDistance != null && minFocusDistance > 0) ? minFocusDistance : 10.0f;
                float step = Math.max(0.1f, maxDist / 40.0f); // 40단계 미세조절

                if (nearer) {
                    currentFocusDistance += step;
                } else {
                    currentFocusDistance -= step;
                }

                if (currentFocusDistance < 0.0f) {
                    currentFocusDistance = 0.0f; // 무한대
                } else if (currentFocusDistance > maxDist) {
                    currentFocusDistance = maxDist; // 최접사
                }

                try {
                    Ln.i(String.format("Set manual focus distance: %.2f / %.2f (AF OFF)", currentFocusDistance, maxDist));
                    requestBuilder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF);
                    requestBuilder.set(CaptureRequest.LENS_FOCUS_DISTANCE, currentFocusDistance);
                    CaptureRequest request = requestBuilder.build();
                    setRepeatingRequest(currentSession, request);
                } catch (CameraAccessException e) {
                    Ln.e("Camera manual focus error", e);
                }
            }
        });
    }

    public void resetAutoFocus() {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null) {
                try {
                    Ln.i("Reset to Auto Focus (CONTINUOUS_PICTURE)");
                    requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_CANCEL);
                    requestBuilder.set(CaptureRequest.CONTROL_AF_REGIONS, null);
                    requestBuilder.set(CaptureRequest.CONTROL_AE_REGIONS, null);
                    requestBuilder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
                    CaptureRequest request = requestBuilder.build();
                    setRepeatingRequest(currentSession, request);
                } catch (CameraAccessException e) {
                    Ln.e("Camera auto focus reset error", e);
                }
            }
        });
    }

    public void setFocusPoint(com.genymobile.scrcpy.model.Position position) {
        cameraHandler.post(() -> {
            assertCameraThread();
            if (currentSession != null && requestBuilder != null && position != null) {
                try {
                    com.genymobile.scrcpy.model.Point pt = position.getPoint();
                    com.genymobile.scrcpy.model.Size screenSize = position.getScreenSize();

                    if (screenSize.getWidth() <= 0 || screenSize.getHeight() <= 0) {
                        return;
                    }

                    // 0.0 ~ 1.0 비율 좌표 계산
                    float rx = Math.max(0f, Math.min(1f, (float) pt.getX() / screenSize.getWidth()));
                    float ry = Math.max(0f, Math.min(1f, (float) pt.getY() / screenSize.getHeight()));

                    Rect sensorRect = activeArraySize;
                    if (sensorRect == null) {
                        sensorRect = new Rect(0, 0, captureSize.getWidth(), captureSize.getHeight());
                    }

                    int centerX = sensorRect.left + (int) (rx * sensorRect.width());
                    int centerY = sensorRect.top + (int) (ry * sensorRect.height());

                    // 포커스 측광 박스 크기 (센서 기준 약 12% 크기)
                    int boxHalfW = Math.max(20, sensorRect.width() / 16);
                    int boxHalfH = Math.max(20, sensorRect.height() / 16);

                    int left = Math.max(sensorRect.left, centerX - boxHalfW);
                    int top = Math.max(sensorRect.top, centerY - boxHalfH);
                    int right = Math.min(sensorRect.right, centerX + boxHalfW);
                    int bottom = Math.min(sensorRect.bottom, centerY + boxHalfH);

                    Rect focusRect = new Rect(left, top, right, bottom);
                    MeteringRectangle meteringRect = new MeteringRectangle(focusRect, MeteringRectangle.METERING_WEIGHT_MAX);
                    MeteringRectangle[] afRegions = new MeteringRectangle[]{meteringRect};

                    Ln.i(String.format("Tap-to-Focus trigger at (%d, %d) -> region: %s", pt.getX(), pt.getY(), focusRect));

                    // 1. 수동 모드 잠금 해제: AF 취소 및 수동 초점 거리 해제
                    requestBuilder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO);
                    requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_CANCEL);
                    requestBuilder.set(CaptureRequest.CONTROL_AF_REGIONS, afRegions);
                    requestBuilder.set(CaptureRequest.CONTROL_AE_REGIONS, afRegions);
                    currentSession.capture(requestBuilder.build(), null, cameraHandler);

                    // 2. AF 트리거 시작 (원샷 포커싱 가동)
                    requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_START);
                    currentSession.capture(requestBuilder.build(), null, cameraHandler);

                    // 3. 트리거 상태 IDLE로 복귀 후 반복 캡처 유지
                    requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_IDLE);
                    setRepeatingRequest(currentSession, requestBuilder.build());
                    setRepeatingRequest(currentSession, requestBuilder.build());
                } catch (CameraAccessException e) {
                    Ln.e("Camera tap-to-focus error", e);
                }
            }
        });
    }

    private static final String FOCUS_FILE = "/data/local/tmp/mic_focus.txt";

    private final Runnable focusPoller = new Runnable() {
        @Override
        public void run() {
            if (!started || cameraHandler == null) {
                return;
            }
            try {
                String cmd = readFocusFile();
                if (cmd != null && !cmd.equals(lastFocusCmd)) {
                    boolean first = lastFocusCmd == null;
                    lastFocusCmd = cmd;
                    if (!first) {
                        // 형식: "seq rx ry" (rx, ry: 표시 화면 기준 0~1 비율)
                        String[] p = cmd.split("\\s+");
                        if (p.length >= 3) {
                            focusAtRatio(Float.parseFloat(p[1]), Float.parseFloat(p[2]));
                        }
                    }
                } else if (lastFocusCmd == null) {
                    lastFocusCmd = "";
                }
            } catch (Exception e) {
                Ln.w("Focus poll error: " + e);
            }
            cameraHandler.postDelayed(this, 80);
        }
    };

    private static String readFocusFile() {
        java.io.File f = new java.io.File(FOCUS_FILE);
        if (!f.exists()) {
            return null;
        }
        try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.FileReader(f))) {
            String line = r.readLine();
            return line != null ? line.trim() : null;
        } catch (IOException e) {
            return null;
        }
    }

    /** 클라이언트가 카메라 모드에서 마우스 클릭을 전달하지 않으므로, 파일 기반으로 탭 포커스 좌표를 받는다. */
    private void startFocusFilePoll() {
        lastFocusCmd = readFocusFile(); // 이전 실행의 오래된 좌표는 무시
        if (lastFocusCmd == null) {
            lastFocusCmd = "";
        }
        cameraHandler.postDelayed(focusPoller, 80);
    }

    /** 표시 화면(현재 줌 크롭 영역 기준) 비율 좌표를 센서 좌표로 변환하여 원샷 AF 수행 (카메라 스레드에서 호출) */
    private void focusAtRatio(float rx, float ry) {
        assertCameraThread();
        if (currentSession == null || requestBuilder == null) {
            return;
        }
        try {
            rx = Math.max(0f, Math.min(1f, rx));
            ry = Math.max(0f, Math.min(1f, ry));

            Rect sensorRect = activeArraySize;
            if (sensorRect == null) {
                sensorRect = new Rect(0, 0, captureSize.getWidth(), captureSize.getHeight());
            }
            Rect view = currentCrop != null ? currentCrop : sensorRect;

            int centerX = view.left + (int) (rx * view.width());
            int centerY = view.top + (int) (ry * view.height());

            int boxHalfW = Math.max(20, view.width() / 12);
            int boxHalfH = Math.max(20, view.height() / 12);

            Rect focusRect = new Rect(
                    Math.max(sensorRect.left, centerX - boxHalfW),
                    Math.max(sensorRect.top, centerY - boxHalfH),
                    Math.min(sensorRect.right, centerX + boxHalfW),
                    Math.min(sensorRect.bottom, centerY + boxHalfH));
            MeteringRectangle[] regions = new MeteringRectangle[]{new MeteringRectangle(focusRect, MeteringRectangle.METERING_WEIGHT_MAX)};

            Ln.i(String.format("Tap-to-Focus at ratio (%.3f, %.3f) -> region: %s", rx, ry, focusRect));

            requestBuilder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO);
            requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_CANCEL);
            requestBuilder.set(CaptureRequest.CONTROL_AF_REGIONS, regions);
            requestBuilder.set(CaptureRequest.CONTROL_AE_REGIONS, regions);
            currentSession.capture(requestBuilder.build(), null, cameraHandler);

            requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_START);
            currentSession.capture(requestBuilder.build(), null, cameraHandler);

            requestBuilder.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_IDLE);
            setRepeatingRequest(currentSession, requestBuilder.build());
        } catch (CameraAccessException e) {
            Ln.e("Camera tap-to-focus error", e);
        }
    }

    private void assertCameraThread() {
        assert Thread.currentThread() == cameraThread;
    }
}
