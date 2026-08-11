"""One-off standalone Scene Detection run for ww_vs_pf, independent of OCR.

Purpose: real-data investigation found that OCR-anchored event timestamps
can correctly match team/score/over.ball yet still land during a replay or
scoreboard-hold period, nowhere near the actual live delivery -- a
different failure mode than anything the metadata-alignment or
innings-transition fixes address. Scene Detection's cut boundaries are a
visual signal, independent of scoreboard OCR legibility entirely, and can
be used to snap a clip's start to the nearest real camera cut before its
OCR anchor instead of a fixed offset.

No existing `scenes` table in the Event Database schema (Scene Detection's
output has never been persisted before -- Module 2's boundaries are
normally consumed in-memory by Replay Detection within the same `analyze()`
run and then discarded). This script persists them to a JSON side-file
instead of extending the schema, since this is an investigation, not yet a
committed feature.
"""

import json
import time

from cvip.video.loader import load_video
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_models import SceneDetectionRequest

VIDEO_PATH = r"D:\Mullai-20231003T001727Z-001\WW\WW Matches\WW_VS_PF_h264.mp4"
OUTPUT_PATH = "data/matches/ww_vs_pf_scene_boundaries.json"

print(f"Loading video: {VIDEO_PATH}")
load_result = load_video(VIDEO_PATH)
if load_result.status.value != "SUCCESS":
    raise SystemExit(f"Video load failed: {load_result.failure_detail}")
print(f"Loaded OK. Duration: {load_result.source.duration_seconds}s")

request = SceneDetectionRequest(load_result=load_result, scene_threshold=8.0)

start = time.time()
with detect_scenes(request) as detector:
    result = detector.run()
elapsed = time.time() - start

print(f"Scene detection complete in {elapsed:.1f}s ({elapsed/3600:.2f}h)")
print(f"Total boundaries: {result.total_boundaries}")
print(f"Replay transitions: {result.replay_transition_count}")

payload = {
    "source_video_id": result.source_video_id,
    "total_boundaries": result.total_boundaries,
    "replay_transition_count": result.replay_transition_count,
    "processing_duration": result.processing_duration,
    "boundaries": [
        {
            "boundary_id": b.boundary_id,
            "timestamp_seconds": b.timestamp_seconds,
            "boundary_type": b.boundary_type.value,
            "confidence": b.confidence,
        }
        for b in result.boundaries
    ],
}
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)

print(f"Written to {OUTPUT_PATH}")
