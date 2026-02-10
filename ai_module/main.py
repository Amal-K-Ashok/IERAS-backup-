import time
import cv2
import multiprocessing
import os
import uuid

from supabase_client import supabase
from engine.object_detection import AccidentDetector
from engine.multithreading_tracker import MultiThreadingTracker


# --------------------------------------------------
# CAMERA MANAGEMENT
# --------------------------------------------------

def fetch_cameras():
    """Fetch all active cameras from Supabase"""
    try:
        result = supabase.table("cameras").select("camera_id, latitude, longitude, cctv_url").execute()
        
        if result.data and len(result.data) > 0:
            print(f"✅ Found {len(result.data)} camera(s) in database:")
            for cam in result.data:
                print(f"   - {cam['camera_id']}: {cam['cctv_url']}")
            return result.data
        else:
            print("⚠️ No cameras found in database")
            return []
    except Exception as e:
        print(f"❌ Failed to fetch cameras: {e}")
        return []


# --------------------------------------------------
# SUPABASE HELPERS
# --------------------------------------------------

def create_accident_event(camera_id, latitude, longitude, severity="medium"):
    """Create accident event with camera-specific location"""
    try:
        res = supabase.table("accidents").insert({
            "camera_id": camera_id,
            "latitude": latitude,
            "longitude": longitude,
            "severity": severity,
            "status": "DETECTED"
        }).execute()
        accident_id = res.data[0]["id"]
        print(f"🆕 Accident created: {accident_id} (Camera: {camera_id})")
        return accident_id
    except Exception as e:
        print(f"❌ Failed to create accident event: {e}")
        return None


def update_accident(accident_id, data):
    try:
        supabase.table("accidents").update(data).eq("id", accident_id).execute()
        print(f"🔄 Accident updated: {data}")
    except Exception as e:
        print(f"❌ Failed to update accident {accident_id}: {e}")


def cleanup_stale_detected_entries():
    """
    Clean up any stale DETECTED entries from previous runs.
    This prevents confusion from entries that were created but never completed.
    """
    try:
        # Find entries that are stuck in DETECTED status for this camera
        # Note: Not checking timestamp since created_at column doesn't exist in your schema
        result = supabase.table("accidents").select("id, camera_id").eq("status", "DETECTED").execute()
        
        if result.data and len(result.data) > 0:
            print(f"\n⚠️ Found {len(result.data)} stale DETECTED entries:")
            for entry in result.data:
                print(f"   - ID: {entry['id']}, Camera: {entry['camera_id']}")
                
                # Mark all as failed since we can't determine age without timestamp
                supabase.table("accidents").update({
                    "status": "FAILED",
                    "clip_path": "Stale entry from previous run - cleaned up on restart"
                }).eq("id", entry['id']).execute()
                print(f"   ✅ Marked entry {entry['id']} as FAILED (stale)")
    except Exception as e:
        print(f"⚠️ Could not check for stale entries: {e}")


def upload_clip_async(clip_path, accident_id):
    """Upload video clip to Supabase with correct MIME type"""
    if not os.path.exists(clip_path):
        print(f"❌ File not found: {clip_path}")
        return

    name = f"accident_{uuid.uuid4()}.mp4"
    
    try:
        print(f"📤 Uploading {clip_path} as {name}...")
        
        with open(clip_path, "rb") as f:
            supabase.storage.from_("videos").upload(
                name, 
                f,
                file_options={
                    "content-type": "video/mp4",
                    "cache-control": "3600",
                    "upsert": "false"
                }
            )

        url = supabase.storage.from_("videos").get_public_url(name)
        
        update_accident(accident_id, {
            "video_url": url,
            "status": "UPLOADED"
        })
        
        print(f"✅ Video uploaded successfully: {name}")
        print(f"🔗 URL: {url}")
        
        try:
            os.remove(clip_path)
            print(f"🗑️ Cleaned up local file: {clip_path}")
        except Exception as e:
            print(f"⚠️ Could not delete local file: {e}")
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        try:
            update_accident(accident_id, {
                "status": "UPLOAD_FAILED",
                "clip_path": clip_path
            })
        except:
            pass


# --------------------------------------------------
# MULTITHREADED VIDEO TRACKING
# --------------------------------------------------

def track_videos_multithreaded(cameras_data, model_path):
    """
    Process multiple video streams simultaneously using multithreading.
    Each camera gets its own detector instance.
    
    Args:
        cameras_data: List of camera dictionaries from database
        model_path: Path to YOLO model weights
    """
    if not cameras_data:
        print("❌ No cameras to process")
        return
    
    print(f"🚀 Starting multithreaded tracking for {len(cameras_data)} camera(s)")
    
    # Validate cameras and their video sources
    validated_cameras = []
    for cam in cameras_data:
        video_source = cam['cctv_url']
        
        # Try to open the video source
        test_cap = cv2.VideoCapture(video_source)
        if test_cap.isOpened():
            validated_cameras.append(cam)
            test_cap.release()
            print(f"✅ Validated camera: {cam['camera_id']} ({video_source})")
        else:
            print(f"❌ Cannot open video source for camera: {cam['camera_id']} ({video_source})")
    
    if not validated_cameras:
        print("❌ No valid cameras found. Exiting.")
        return
    
    print(f"\n✅ Processing {len(validated_cameras)} valid camera(s)")
    
    # Initialize the multithreading tracker
    tracker = MultiThreadingTracker(queue_size=20)
    
    # Create a detector and state for each camera
    detectors = {}
    accident_states = {}
    camera_metadata = {}  # Store camera metadata for later use
    
    for cam in validated_cameras:
        video_source = cam['cctv_url']
        
        # Get FPS from video
        cap = cv2.VideoCapture(video_source)
        if cap.isOpened():
            fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)))
            cap.release()
        else:
            fps = 30  # Default fallback
            print(f"⚠️ Could not open {video_source} for FPS detection, using default")
        
        detectors[video_source] = AccidentDetector(model_path, fps=fps)
        accident_states[video_source] = {
            "active": False,
            "accident_id": None,
            "last_event_time": 0,
            "camera_id": cam['camera_id'],
            "latitude": cam['latitude'],
            "longitude": cam['longitude']
        }
        camera_metadata[video_source] = cam
        print(f"✅ Initialized detector for {cam['camera_id']} (FPS: {fps})")
    
    # Start capture threads
    video_sources = [cam['cctv_url'] for cam in validated_cameras]
    tracker.start_cap_thread(video_sources)
    
    print("🎬 Processing frames from all cameras...")
    
    try:
        frame_count = 0
        active_cameras = set()  # Track which cameras are actually sending frames
        
        while True:
            # Get frame from any available camera
            ret, cam_id, frame, timestamp = tracker.get_frame()
            
            if not ret:
                # No frames available
                # If no cameras have been active for a while, exit
                if frame_count > 0 and len(active_cameras) == 0:
                    time.sleep(0.1)
                    # Double check - if still no frames after sleep, exit
                    ret2, _, _, _ = tracker.get_frame()
                    if not ret2:
                        print("⚠️ No more frames from any camera - ending session")
                        break
                time.sleep(0.01)
                continue
            
            # Mark this camera as active
            active_cameras.add(cam_id)
            frame_count += 1
            
            # Get detector and state for this camera
            detector = detectors.get(cam_id)
            state = accident_states.get(cam_id)
            
            if not detector or not state:
                continue
            
            # Process frame through detector
            events = detector.process_frame(frame)
            detector.draw_debug(frame)
            
            # Debug: Log events for troubleshooting
            if events and frame_count % 50 == 0:  # Log every 50 frames if there are events
                event_types = [ev["type"] for ev in events]
                if event_types:
                    print(f"🔍 {state['camera_id']} events: {event_types}")
            
            # 1️⃣ Create DB row ONCE when accident detected
            if not state["active"]:
                for ev in events:
                    # Check cooldown to prevent rapid re-detections
                    time_since_last = time.time() - state["last_event_time"]
                    if ev["type"] == "ACCIDENT" and time_since_last > 45:  # Increased from 30 to 45 seconds
                        accident_id = create_accident_event(
                            state["camera_id"],
                            state["latitude"],
                            state["longitude"]
                        )
                        if accident_id:  # Only proceed if DB insert succeeded
                            state["accident_id"] = accident_id
                            state["active"] = True
                            state["last_event_time"] = time.time()
                            print(f"🚨 ACCIDENT DETECTED on {state['camera_id']} (cooldown: {time_since_last:.0f}s)")
                        else:
                            print(f"⚠️ Failed to create accident entry for {state['camera_id']}")
                        break
            
            # 2️⃣ Check for trimmed clip
            ready_clips = detector.handle_clip()
            
            # Debug: Log when handle_clip is called for active accidents
            if state["active"] and state["accident_id"] and frame_count % 100 == 0:
                time_active = time.time() - state["last_event_time"]
                print(f"🔍 {state['camera_id']} checking for clip (active for {time_active:.0f}s) - clips ready: {len(ready_clips)}")
            
            if state["active"] and state["accident_id"]:
                for ev in ready_clips:
                    clip_path = ev.get("clip_path")
                    if not clip_path:
                        continue
                    
                    print(f"✂️ Clip trimmed for {state['camera_id']}: {clip_path}")
                    update_accident(state["accident_id"], {
                        "status": "TRIMMED",
                        "clip_path": clip_path
                    })
                    
                    # Upload in background process
                    upload_process = multiprocessing.Process(
                        target=upload_clip_async,
                        args=(clip_path, state["accident_id"]),
                        daemon=True
                    )
                    upload_process.start()
                    
                    # Reset state - IMPORTANT: Do this immediately after starting upload
                    print(f"✅ Reset state for {state['camera_id']} - ready for next accident")
                    state["active"] = False
                    state["accident_id"] = None
                    break  # Only process one clip at a time
            
            # 3️⃣ Safety check: Check ALL cameras for stuck accidents (not just current camera)
            # This ensures we catch stuck accidents even if that camera's frames aren't being processed
            for check_cam, check_state in accident_states.items():
                if check_state["active"] and check_state["accident_id"]:
                    time_since_detection = time.time() - check_state["last_event_time"]
                    
                    if time_since_detection > 45:  # Force finalize after 45 seconds
                        check_detector = detectors.get(check_cam)
                        if not check_detector:
                            continue
                            
                        print(f"⚠️ Accident on {check_state['camera_id']} stuck for {time_since_detection:.0f}s, forcing finalization...")
                        forced_clips = check_detector.handle_clip(final=True)
                        
                        if forced_clips:
                            for ev in forced_clips:
                                clip_path = ev.get("clip_path")
                                if clip_path:
                                    print(f"✂️ Force-trimmed clip for {check_state['camera_id']}: {clip_path}")
                                    update_accident(check_state["accident_id"], {
                                        "status": "TRIMMED",
                                        "clip_path": clip_path
                                    })
                                    upload_process = multiprocessing.Process(
                                        target=upload_clip_async,
                                        args=(clip_path, check_state["accident_id"]),
                                        daemon=True
                                    )
                                    upload_process.start()
                                    check_state["active"] = False
                                    check_state["accident_id"] = None
                                    print(f"✅ Force-finalized and reset state for {check_state['camera_id']}")
                                    break
                        else:
                            # If no clip was produced even after forcing, mark as failed
                            print(f"❌ No clip produced for {check_state['camera_id']} even after forcing - marking as failed")
                            update_accident(check_state["accident_id"], {
                                "status": "FAILED",
                                "clip_path": f"No clip generated after {time_since_detection:.0f}s"
                            })
                            check_state["active"] = False
                            check_state["accident_id"] = None
            
            # Display frame (optional - comment out for headless operation)
            window_name = f"Camera: {state['camera_id']}"
            cv2.imshow(window_name, frame)
            
            # Check for ESC key to exit
            if cv2.waitKey(1) & 0xFF == 27:
                print("🛑 ESC pressed - stopping...")
                break
            
            # Optional: Print status every 100 frames
            if frame_count % 100 == 0:
                active_cam_ids = [accident_states[c]["camera_id"] for c in active_cameras if c in accident_states]
                active_cams_str = ", ".join(active_cam_ids)
                
                # Show which cameras have active accidents
                accidents_info = []
                for cam_path, st in accident_states.items():
                    if st["active"]:
                        time_active = time.time() - st["last_event_time"]
                        accidents_info.append(f"{st['camera_id']}({time_active:.0f}s)")
                
                status_msg = f"📊 Processed {frame_count} frames | Active cameras: {active_cams_str}"
                if accidents_info:
                    status_msg += f" | Active accidents: {', '.join(accidents_info)}"
                print(status_msg)
    
    except KeyboardInterrupt:
        print("\n⚠️ Keyboard interrupt received - stopping...")
    
    finally:
        print("🧹 Cleaning up...")
        
        # Stop tracker
        tracker.stop()
        
        # Summary of what's being finalized
        pending_accidents = [(cam, st) for cam, st in accident_states.items() if st["active"] and cam in active_cameras]
        if pending_accidents:
            print(f"\n⚠️ Finalizing {len(pending_accidents)} pending accident(s):")
            for cam, st in pending_accidents:
                time_pending = time.time() - st["last_event_time"]
                print(f"   - {st['camera_id']}: pending for {time_pending:.0f}s")
        
        # Finalize any pending clips
        for cam_id, detector in detectors.items():
            state = accident_states[cam_id]
            
            # Only finalize if this camera was actually active
            if cam_id not in active_cameras:
                continue
                
            final_clips = detector.handle_clip(final=True)
            
            for ev in final_clips:
                if state["accident_id"] and ev.get("clip_path"):
                    print(f"🎬 Finalizing clip for {state['camera_id']}: {ev['clip_path']}")
                    update_accident(state["accident_id"], {
                        "status": "TRIMMED",
                        "clip_path": ev["clip_path"]
                    })
                    upload_clip_async(ev["clip_path"], state["accident_id"])
        
        cv2.destroyAllWindows()
        print("✅ Cleanup complete")


# --------------------------------------------------
# MAIN ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Print current working directory for debugging
    print(f"📂 Current directory: {os.getcwd()}")
    print(f"📂 Script directory: {script_dir}")
    
    # Clean up any stale DETECTED entries from previous runs
    cleanup_stale_detected_entries()
    
    print("\n" + "="*60)
    print("🎥 FETCHING CAMERAS FROM DATABASE")
    print("="*60)
    
    # Fetch cameras from database
    cameras = fetch_cameras()
    
    if not cameras:
        print("\n❌ No cameras found. Please add cameras to the 'cameras' table in Supabase.")
        print("\nExample SQL:")
        print("INSERT INTO cameras (camera_id, latitude, longitude, cctv_url)")
        print("VALUES ('CAM001', 11.7480, 75.4938, 'path/to/video.mp4');")
        exit(1)
    
    # Model path
    model_path = os.path.join(script_dir, "models", "yolov8n.pt")
    
    print(f"\n🔍 Checking model:")
    print(f"  {'✅' if os.path.exists(model_path) else '❌'} {model_path}")
    
    if not os.path.exists(model_path):
        print("\n❌ Model file not found!")
        exit(1)
    
    print("\n" + "="*50)
    print(" STARTING ACCIDENT DETECTION SYSTEM")
    print("="*50 + "\n")
    
    track_videos_multithreaded(cameras, model_path)
    
    # Legacy modes (kept for reference)
    # 
    # Mode 2: Manual video paths (for testing without database)
    # video_paths = [
    #     os.path.join(script_dir, "input", "Video1.mp4"),
    #     os.path.join(script_dir, "input", "Video2.mp4"),
    # ]
    # cameras_data = [
    #     {"camera_id": "CAM001", "latitude": 11.7480, "longitude": 75.4938, "cctv_url": video_paths[0]},
    #     {"camera_id": "CAM002", "latitude": 11.7490, "longitude": 75.4948, "cctv_url": video_paths[1]},
    # ]
    # track_videos_multithreaded(cameras_data, model_path)
    #
    # Mode 3: Multiprocessing - Each camera in separate process (advanced)
    # multiprocessing.set_start_method("spawn", force=True)
    # jobs = [
    #     ([cameras[0]], model_path),
    #     ([cameras[1]], model_path)
    # ]
    # with multiprocessing.Pool(processes=2) as pool:
    #     pool.starmap(track_videos_multithreaded, jobs)