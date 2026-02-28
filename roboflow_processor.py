import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import av
import cv2
import numpy as np
from inference_sdk import InferenceHTTPClient
from vision_agents.core.processors.base_processor import VideoProcessorPublisher
from vision_agents.core.utils.video_forwarder import VideoForwarder
from vision_agents.core.utils.video_track import QueuedVideoTrack

logger = logging.getLogger(__name__)

# Colors per detection class (BGR for cv2)
CLASS_COLORS = {
    "Mask": (0, 255, 0),          # Bright green
    "NO-Mask": (0, 0, 255),       # Bright red
    "Safety Vest": (0, 255, 255), # Bright yellow
    "NO-Safety Vest": (0, 0, 255), # Bright red
    "Hardhat": (255, 0, 0),       # Bright blue
    "NO-Hardhat": (0, 0, 255),    # Bright red
    "Person": (255, 180, 0),      # Orange
    "Safety Cone": (0, 255, 255), # Yellow
    "machinery": (128, 128, 128), # Gray
    "vehicle": (128, 128, 128),   # Gray
}

DEFAULT_COLOR = (255, 255, 0)     # Bright cyan


class RoboflowProcessor(VideoProcessorPublisher):
    """
    Object detection processor using the Roboflow hosted inference API.

    Receives video frames, sends them to Roboflow for detection,
    annotates the frames with bounding boxes, and publishes annotated video.
    Also exposes ``latest_detections`` for the agent to query.
    """

    name = "roboflow_detector"

    # After this many consecutive failures, stop calling the API entirely.
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(
        self,
        api_key: str,
        model_id: str = "personal-protective-equipment-combined-model/14",
        conf_threshold: float = 0.4,
        fps: int = 1,
        max_workers: int = 4,
    ):
        self.model_id = model_id
        self.conf_threshold = conf_threshold
        self.fps = fps
        self._disabled = False
        self._consecutive_failures = 0

        self._client = InferenceHTTPClient(
            api_url="https://detect.roboflow.com",
            api_key=api_key,
        )

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="roboflow_processor"
        )
        self._shutdown = False
        self._video_forwarder: Optional[VideoForwarder] = None
        self._video_track = QueuedVideoTrack()

        # Accessible by the agent to read current detections
        self.latest_detections: dict[str, Any] = {}
        
        # Track recent detections to avoid duplicates
        self._recent_detections: dict = {}
        self._duplicate_threshold = 0.9  # Minimum IoU threshold to consider detections as duplicates
        self._detection_timeout = 5.0    # Time in seconds before a detection can be reported again

        logger.info(
            f"Roboflow processor initialized  model={model_id}  conf={conf_threshold}  fps={fps}"
        )

    # ------------------------------------------------------------------
    # VideoProcessor interface
    # ------------------------------------------------------------------

    async def process_video(
        self,
        incoming_track,
        participant_id: Optional[str],
        shared_forwarder: Optional[VideoForwarder] = None,
    ) -> None:
        if self._video_forwarder is not None:
            logger.info("Stopping ongoing Roboflow processing for new track")
            await self._video_forwarder.remove_frame_handler(self._on_frame)

        logger.info(f"Starting Roboflow video processing at {self.fps} FPS")
        self._video_forwarder = (
            shared_forwarder
            if shared_forwarder
            else VideoForwarder(
                incoming_track,
                max_buffer=self.fps,
                fps=self.fps,
                name="roboflow_forwarder",
            )
        )
        self._video_forwarder.add_frame_handler(
            self._on_frame, fps=float(self.fps), name="roboflow"
        )

    async def stop_processing(self) -> None:
        if self._video_forwarder is not None:
            await self._video_forwarder.remove_frame_handler(self._on_frame)
            self._video_forwarder = None
            logger.info("Stopped Roboflow video processing")

    # ------------------------------------------------------------------
    # VideoPublisher interface
    # ------------------------------------------------------------------

    def publish_video_track(self):
        return self._video_track

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        self._shutdown = True
        await self.stop_processing()
        self.executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Internal: frame handler
    # ------------------------------------------------------------------

    async def _on_frame(self, frame: av.VideoFrame) -> None:
        if self._shutdown or self._disabled:
            await self._video_track.add_frame(frame)
            return

        try:
            frame_array = frame.to_ndarray(format="rgb24")

            loop = asyncio.get_event_loop()
            start = time.perf_counter()
            detections = await asyncio.wait_for(
                loop.run_in_executor(self.executor, self._detect_sync, frame_array),
                timeout=5.0,
            )
            elapsed = time.perf_counter() - start
            logger.debug(f"Roboflow inference took {elapsed:.3f}s  detections={len(detections)}")

            # Reset failure counter on success
            self._consecutive_failures = 0

            # Filter out duplicate detections
            filtered_detections = self._filter_duplicate_detections(detections)

            # Store latest results for the agent
            self.latest_detections = {
                "timestamp": time.time(),
                "objects": filtered_detections,
                "summary": ", ".join(
                    f"{d['class']} ({d['confidence']:.0%})" for d in filtered_detections
                )
                if filtered_detections
                else "nothing detected",
            }

            annotated = self._annotate_frame(frame_array, filtered_detections)
            out_frame = av.VideoFrame.from_ndarray(annotated)
            await self._video_track.add_frame(out_frame)

        except asyncio.TimeoutError:
            logger.warning("Roboflow API call timed out, forwarding original frame")
            await self._video_track.add_frame(frame)
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                self._disabled = True
                logger.warning(
                    "Roboflow disabled after %d consecutive failures (last: %s). "
                    "Frames will pass through without detection.",
                    self._consecutive_failures,
                    exc,
                )
            else:
                logger.warning("Roboflow error (%d/%d): %s",
                               self._consecutive_failures,
                               self.MAX_CONSECUTIVE_FAILURES,
                               exc)
            await self._video_track.add_frame(frame)

    # ------------------------------------------------------------------
    # Synchronous detection (runs in thread pool)
    # ------------------------------------------------------------------

    def _detect_sync(self, frame_array: np.ndarray) -> list[dict[str, Any]]:
        if self._shutdown:
            return []

        # inference-sdk expects BGR or RGB numpy arrays
        result = self._client.infer(frame_array, model_id=self.model_id)

        predictions = result.get("predictions", []) if isinstance(result, dict) else []
        detections: list[dict[str, Any]] = []

        for pred in predictions:
            conf = pred.get("confidence", 0)
            if conf < self.conf_threshold:
                continue

            cx = pred.get("x", 0)
            cy = pred.get("y", 0)
            w = pred.get("width", 0)
            h = pred.get("height", 0)

            detections.append(
                {
                    "class": pred.get("class", "unknown"),
                    "confidence": round(conf, 3),
                    "bbox": {
                        "xmin": int(cx - w / 2),
                        "ymin": int(cy - h / 2),
                        "xmax": int(cx + w / 2),
                        "ymax": int(cy + h / 2),
                    },
                }
            )

        return detections

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------

    def _calculate_iou(self, bbox1: dict, bbox2: dict) -> float:
        """Calculate Intersection over Union between two bounding boxes."""
        x1_1, y1_1, x2_1, y2_1 = bbox1["xmin"], bbox1["ymin"], bbox1["xmax"], bbox1["ymax"]
        x1_2, y1_2, x2_2, y2_2 = bbox2["xmin"], bbox2["ymin"], bbox2["xmax"], bbox2["ymax"]

        # Calculate intersection coordinates
        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)

        # Calculate intersection area
        inter_width = max(0, xi2 - xi1)
        inter_height = max(0, yi2 - yi1)
        inter_area = inter_width * inter_height

        # Calculate union area
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = area1 + area2 - inter_area

        # Return IoU
        return inter_area / union_area if union_area > 0 else 0

    def _filter_duplicate_detections(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter out duplicate detections based on spatial overlap and time since last detection."""
        current_time = time.time()
        filtered_detections = []
        
        for det in detections:
            label = det["class"]
            bbox = det["bbox"]
            conf = det["confidence"]
            
            # Create a key for this detection type
            detection_key = label
            
            # Check if we have recent detections of this type
            if detection_key in self._recent_detections:
                recent_list = self._recent_detections[detection_key]
                
                # Filter out recent detections that are too old
                recent_list = [
                    old_det for old_det in recent_list 
                    if current_time - old_det.get("timestamp", 0) <= self._detection_timeout
                ]
                
                # Check if any recent detection overlaps significantly with this one
                is_duplicate = False
                for old_det in recent_list:
                    iou = self._calculate_iou(bbox, old_det["bbox"])
                    if iou >= self._duplicate_threshold:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    filtered_detections.append(det)
                    # Add this detection to recent list
                    recent_list.append({
                        "bbox": bbox,
                        "confidence": conf,
                        "timestamp": current_time
                    })
                    self._recent_detections[detection_key] = recent_list
                else:
                    # Update timestamp of the existing detection
                    for i, old_det in enumerate(recent_list):
                        iou = self._calculate_iou(bbox, old_det["bbox"])
                        if iou >= self._duplicate_threshold:
                            recent_list[i]["timestamp"] = current_time
                            break
                    self._recent_detections[detection_key] = recent_list
            else:
                # First detection of this type
                filtered_detections.append(det)
                self._recent_detections[detection_key] = [{
                    "bbox": bbox,
                    "confidence": conf,
                    "timestamp": current_time
                }]
        
        return filtered_detections

    @staticmethod
    def _annotate_frame(
        frame_array: np.ndarray, detections: list[dict[str, Any]]
    ) -> np.ndarray:
        annotated = frame_array.copy()

        for det in detections:
            bbox = det["bbox"]
            label = det["class"]
            conf = det["confidence"]
            color = CLASS_COLORS.get(label, DEFAULT_COLOR)

            x1, y1, x2, y2 = bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]

            # Bounding box with increased thickness for better visibility
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)

            # Label background
            text = f"{label} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(annotated, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)

            # Label text
            cv2.putText(
                annotated,
                text,
                (x1 + 3, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        return annotated
