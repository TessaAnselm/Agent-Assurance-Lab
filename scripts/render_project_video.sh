#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="${1:-$repo_dir/docs/video/agent-assurance-lab-90s.mp4}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

font_file="/System/Library/Fonts/Supplemental/Arial.ttf"
narration_file="$repo_dir/docs/video/narration.txt"
narration_aiff="$work_dir/narration.aiff"
narration_wav="$work_dir/narration.wav"

command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v say >/dev/null
test -f "$font_file"

say -v Samantha -r 160 -f "$narration_file" -o "$narration_aiff"

narration_duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$narration_aiff")"
tempo="$(awk -v duration="$narration_duration" 'BEGIN { printf "%.6f", duration / 85.0 }')"

ffmpeg -y -hide_banner -loglevel error \
  -i "$narration_aiff" \
  -af "atempo=$tempo,adelay=2500,apad,atrim=duration=90" \
  -ar 48000 -ac 2 "$narration_wav"

mkdir -p "$(dirname "$output_path")"

ffmpeg -y -hide_banner -loglevel warning \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/experiment-walkthrough.png" \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/real-agent-canary.png" \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/clickhouse-telemetry.png" \
  -loop 1 -framerate 30 -i "$repo_dir/frontend/monster-celebrate.png" \
  -loop 1 -framerate 30 -i "$repo_dir/frontend/monster-wave.png" \
  -i "$narration_wav" \
  -filter_complex "\
color=c=0x153536:s=1280x720:r=30:d=7[titlebg];\
[3:v]scale=390:-2,format=rgba[titlemonster];\
[titlebg][titlemonster]overlay=820:165:shortest=1,\
drawtext=fontfile='$font_file':text='AGENT ASSURANCE LAB':fontcolor=white:fontsize=58:x=70:y=185,\
drawtext=fontfile='$font_file':text='Turn security claims into evidence':fontcolor=0xCDEBE5:fontsize=30:x=74:y=270,\
drawtext=fontfile='$font_file':text='MCP EGRESS  /  EXPERIMENT 001':fontcolor=0xF1A2C6:fontsize=20:x=75:y=145,\
trim=duration=7,setpts=PTS-STARTPTS[v0];\
[0:v]scale=1280:-2,crop=1280:720:0:0,setsar=1,\
drawbox=x=0:y=625:w=1280:h=95:color=0x153536@0.92:t=fill,\
drawtext=fontfile='$font_file':text='1  VALIDATE THE CASE':fontcolor=white:fontsize=34:x=54:y=649,\
trim=duration=16,setpts=PTS-STARTPTS[v1];\
[0:v]scale=1280:-2,crop=1280:720:0:300,setsar=1,\
drawbox=x=0:y=0:w=1280:h=98:color=0x153536@0.92:t=fill,\
drawtext=fontfile='$font_file':text='2  FOLLOW THE BYPASS':fontcolor=white:fontsize=34:x=54:y=30,\
trim=duration=17,setpts=PTS-STARTPTS[v2];\
[0:v]scale=1280:-2,crop=1280:720:0:145,setsar=1,\
drawbox=x=0:y=0:w=1280:h=98:color=0x153536@0.92:t=fill,\
drawtext=fontfile='$font_file':text='3  DETECT, FIX, VERIFY':fontcolor=white:fontsize=34:x=54:y=30,\
trim=duration=15,setpts=PTS-STARTPTS[v3];\
[1:v]scale=1160:-2,pad=1280:720:(ow-iw)/2:225:color=0xF3F5F6,setsar=1,\
drawtext=fontfile='$font_file':text='RUN IT AGAINST YOUR OWN AGENT':fontcolor=0x153536:fontsize=38:x=60:y=70,\
drawtext=fontfile='$font_file':text='A unique canary URL makes the verdict observable.':fontcolor=0x52636C:fontsize=25:x=62:y=125,\
trim=duration=14,setpts=PTS-STARTPTS[v4];\
[2:v]scale=1280:-2,crop=1280:720:0:0,setsar=1,\
drawbox=x=0:y=625:w=1280:h=95:color=0x153536@0.92:t=fill,\
drawtext=fontfile='$font_file':text='LIVE, APPEND-ONLY TELEMETRY':fontcolor=white:fontsize=34:x=54:y=649,\
trim=duration=14,setpts=PTS-STARTPTS[v5];\
color=c=0x153536:s=1280x720:r=30:d=7[outbg];\
[4:v]scale=360:-2,format=rgba[outmonster];\
[outbg][outmonster]overlay=845:170:shortest=1,\
drawtext=fontfile='$font_file':text='TEST THE CLAIM.':fontcolor=white:fontsize=49:x=74:y=185,\
drawtext=fontfile='$font_file':text='CAPTURE THE EVIDENCE.':fontcolor=0xF1A2C6:fontsize=49:x=74:y=250,\
drawtext=fontfile='$font_file':text='MAKE SECURITY MEASURABLE.':fontcolor=0xCDEBE5:fontsize=37:x=77:y=325,\
drawtext=fontfile='$font_file':text='Agent Assurance Lab':fontcolor=white:fontsize=25:x=78:y=415,\
trim=duration=7,setpts=PTS-STARTPTS[v6];\
[v0][v1][v2][v3][v4][v5][v6]concat=n=7:v=1:a=0,format=yuv420p[v]" \
  -map "[v]" -map 5:a \
  -t 90 -r 30 \
  -c:v libx264 -preset medium -crf 20 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$output_path"

printf 'Rendered %s\n' "$output_path"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$output_path"
