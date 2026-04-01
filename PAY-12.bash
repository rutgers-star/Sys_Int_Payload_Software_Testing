#!/bin/bash

# Check if input file is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <video_file>"
    exit 1
fi

VIDEO="$1"

# Verify file exists
if [ ! -f "$VIDEO" ]; then
    echo "Error: File '$VIDEO' not found."
    exit 1
fi

echo "============================================"
echo "Analyzing video: $VIDEO"
echo "============================================"

# 1. Use ffprobe to get basic stream info
echo -e "\n[1] General Information"
ffprobe -v quiet -show_format -show_streams "$VIDEO" | grep -E "duration|bit_rate|width|height|r_frame_rate|codec_name|nb_frames"

# 2. Extract resolution and frame rate more cleanly
echo -e "\n[2] Resolution and Frame Rate"
RESOLUTION=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$VIDEO")
FPS=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
echo "Resolution: $RESOLUTION"
echo "Frame Rate (nominal): $FPS fps"

# 3. Get duration and total expected frames (using container duration)
DURATION=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
echo "Duration: $DURATION seconds"
EXPECTED_FRAMES=$(echo "$DURATION * ($FPS)" | bc -l | cut -d. -f1)
echo "Expected frames (approx): $EXPECTED_FRAMES"

# 4. Count actual frames by decoding all frames (ignores errors)
echo -e "\n[3] Counting Frames (decoding all frames)"
FRAME_COUNT=$(ffmpeg -i "$VIDEO" -map 0:v:0 -f null - 2>&1 | grep "frame=" | tail -n1 | awk '{print $2}')
if [ -z "$FRAME_COUNT" ]; then
    echo "Could not determine frame count. Attempting alternative method..."
    FRAME_COUNT=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of default=noprint_wrappers=1 "$VIDEO" | grep nb_read_frames | cut -d= -f2)
fi
echo "Actual frames decoded: $FRAME_COUNT"

# 5. Compare actual vs expected
echo -e "\n[4] Frame Drop Analysis"
if [ -n "$EXPECTED_FRAMES" ] && [ -n "$FRAME_COUNT" ]; then
    DIFF=$((EXPECTED_FRAMES - FRAME_COUNT))
    DROP_RATE=$(echo "scale=2; ($DIFF * 100) / $EXPECTED_FRAMES" | bc -l)
    echo "Expected frames: $EXPECTED_FRAMES"
    echo "Actual frames:   $FRAME_COUNT"
    echo "Missing frames:  $DIFF"
    echo "Drop rate:       ${DROP_RATE}%"
else
    echo "Unable to compute frame drop rate."
fi

# 6. Check for decoding errors
echo -e "\n[5] Decoding Error Detection"
ERROR_COUNT=$(ffmpeg -v error -i "$VIDEO" -f null - 2>&1 | grep -c "error")
if [ $ERROR_COUNT -gt 0 ]; then
    echo "WARNING: $ERROR_COUNT decoding errors detected."
    echo "Detailed errors:"
    ffmpeg -v error -i "$VIDEO" -f null - 2>&1 | grep "error"
else
    echo "No decoding errors detected."
fi

# 7. Bitrate information
echo -e "\n[6] Bitrate"
BITRATE=$(ffprobe -v quiet -show_entries format=bit_rate -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
if [ -n "$BITRATE" ] && [ "$BITRATE" != "N/A" ]; then
    BITRATE_MB=$(echo "scale=2; $BITRATE / 1000000" | bc -l)
    echo "Overall bitrate: ${BITRATE_MB} Mbps"
else
    echo "Overall bitrate not available in container."
fi

# 8. Additional: Show first and last timestamps (to detect corruption)
echo -e "\n[7] Frame Timestamp Check (first 5 frames)"
ffprobe -v quiet -select_streams v:0 -show_frames -show_entries frame=pkt_pts_time -of default=noprint_wrappers=1 "$VIDEO" | head -10

echo -e "\n============================================"
echo "Analysis complete."
echo "============================================"
