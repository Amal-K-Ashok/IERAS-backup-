import cv2
import threading
import queue
import time




class MultiThreadingTracker:
    def __init__(self, queue_size=10):
        self.captures = []
        self.threads = []
        self.running = False
        self.frame_queue = queue.Queue(maxsize=queue_size)

    # ------------------ Frame Capture Thread ------------------

    def _capture_loop(self, cap, source_id):
        fps = cap.get(cv2.CAP_PROP_FPS)
        delay = 1 / fps if fps and fps > 0 else 0.04  # fallback 25 FPS

        print(f"🎞 FPS for {source_id}: {fps}")

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            if not self.frame_queue.full():
                self.frame_queue.put((True, source_id, frame, time.time()))

            time.sleep(delay)   # ✅ FPS-respecting delay

        cap.release()



    # ------------------ Public API ------------------

    def start_cap_thread(self, video_paths):
        """
        video_paths : list[str]
        """
        self.running = True

        for path in video_paths:
            cap = cv2.VideoCapture(path)

            print("📹 Opening:", path)
            print("   Opened:", cap.isOpened())

            if not cap.isOpened():
                print(f"❌ Failed to open video: {path}")
                continue

            self.captures.append(cap)
            t = threading.Thread(
                target=self._capture_loop,
                args=(cap, path),
                daemon=True
            )
            t.start()
            self.threads.append(t)

    def get_frame(self):
        """
        Returns (ret, cam_id, frame, timestamp)
        """
        if not self.running:
            return False, None, None, None

        try:
            ret, cam_id, frame, ts = self.frame_queue.get(timeout=1)
            return ret, cam_id, frame, ts
        except queue.Empty:
            return False, None, None, None

    def stop(self):
        self.running = False
        for t in self.threads:
            t.join(timeout=1)

        while not self.frame_queue.empty():
            self.frame_queue.get()
