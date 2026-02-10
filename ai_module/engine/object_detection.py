import os
import time
import cv2
import numpy as np
from collections import deque
from ultralytics import YOLO


class AccidentDetector:
    def __init__(self, model_path, fps=25):
        self.model = YOLO(model_path)
        self.fps = fps
        self.frame_id = 0
        self.frame_buffer = deque(maxlen=fps * 20)

        self.pending = []
        self.global_last = 0
        self.GLOBAL_COOLDOWN = 12

        self.active_clip = None

    # ---------------- FRAME PROCESS ----------------

    def process_frame(self, frame):
        self.frame_id += 1
        self.frame_buffer.append((frame.copy(), self.frame_id))
        now = time.time()

        results = self.model(frame, verbose=False)[0]
        detections = []

        for box in results.boxes:
            if float(box.conf[0]) > 0.4:
                detections.append(box)

        events = []

        if detections and now - self.global_last > self.GLOBAL_COOLDOWN:
            self.pending.append(now)
            if len(self.pending) >= 3:
                self.global_last = now
                self.pending.clear()
                events.append({"type": "ACCIDENT", "time": now})
                self.start_clip(now)

        return events

    # ---------------- CLIP HANDLING ----------------

    def start_clip(self, event_time):
        start = self.frame_id - self.fps * 5
        end = self.frame_id + self.fps * 5
        self.active_clip = {
            "start": start,
            "end": end,
            "frames": [],
            "last": 0
        }

    def handle_clip(self, final=False):
        if not self.active_clip:
            return []

        clip = self.active_clip
        ready = []

        for frame, fid in self.frame_buffer:
            if clip["start"] <= fid <= clip["end"] and fid > clip["last"]:
                clip["frames"].append(frame)
                clip["last"] = fid

        if final or self.frame_id > clip["end"]:
            path = self.write_clip(clip)
            if path:
                ready.append({"type": "ACCIDENT", "clip_path": path})
            self.active_clip = None

        return ready

    def write_clip(self, clip):
        if not clip["frames"]:
            return None

        os.makedirs("events", exist_ok=True)
        h, w = clip["frames"][0].shape[:2]
        temp_name = f"events/ACCIDENT_{int(time.time())}_temp.avi"
        final_name = f"events/ACCIDENT_{int(time.time())}.mp4"

        # Step 1: Write to AVI with XVID (fast, reliable with OpenCV)
        out = cv2.VideoWriter(
            temp_name,
            cv2.VideoWriter_fourcc(*"XVID"),
            self.fps,
            (w, h)
        )

        for f in clip["frames"]:
            out.write(f)
        out.release()

        print("✅ Temp clip written:", temp_name)

        # Step 2: Convert to browser-compatible MP4 using FFmpeg
        try:
            import subprocess
            
            subprocess.run([
                'ffmpeg',
                '-i', temp_name,
                '-c:v', 'libx264',           # H.264 codec
                '-profile:v', 'baseline',     # Baseline profile (most compatible)
                '-level', '3.0',              # Level 3.0
                '-pix_fmt', 'yuv420p',        # Standard pixel format
                '-movflags', '+faststart',    # Enable streaming (moov atom at start)
                '-preset', 'ultrafast',       # Fast encoding
                '-crf', '23',                 # Quality (lower = better, 23 is good)
                '-y',                         # Overwrite output
                final_name
            ], check=True, capture_output=True, timeout=30)
            
            print("✅ Browser-compatible MP4 created:", final_name)
            
            # Clean up temp file
            if os.path.exists(temp_name):
                os.remove(temp_name)
            
            return final_name
            
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg conversion failed: {e.stderr.decode() if e.stderr else 'Unknown error'}")
            print("⚠️ Falling back to temp AVI file")
            # If FFmpeg fails, rename temp file and return it
            if os.path.exists(temp_name):
                os.rename(temp_name, final_name.replace('.mp4', '.avi'))
                return final_name.replace('.mp4', '.avi')
            return None
            
        except FileNotFoundError:
            print("❌ FFmpeg not found! Please install FFmpeg:")
            print("   Windows: choco install ffmpeg")
            print("   Linux: sudo apt install ffmpeg")
            print("   Mac: brew install ffmpeg")
            print("⚠️ Falling back to temp AVI file")
            if os.path.exists(temp_name):
                os.rename(temp_name, final_name.replace('.mp4', '.avi'))
                return final_name.replace('.mp4', '.avi')
            return None
            
        except Exception as e:
            print(f"❌ Unexpected error during conversion: {e}")
            if os.path.exists(temp_name):
                os.rename(temp_name, final_name.replace('.mp4', '.avi'))
                return final_name.replace('.mp4', '.avi')
            return None

    # ---------------- DEBUG ----------------

    def draw_debug(self, frame):
        cv2.putText(frame, "Accident Detector Running",
                    (20, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 255, 0), 2)