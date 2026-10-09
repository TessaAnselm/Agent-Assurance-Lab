#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="${1:-$repo_dir/.local-video/agent-assurance-lab-real-case-90s.mp4}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

font_file="/System/Library/Fonts/Supplemental/Arial.ttf"
narration_file="$repo_dir/docs/video/narration.txt"
narration_raw="$work_dir/narration-voice1.wav"
narration_fitted="$work_dir/narration-fitted.wav"

command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
test -x "$repo_dir/.venv-coqui/bin/python"
test -f "$repo_dir/voice1.m4a"
test -f "$font_file"

"$repo_dir/.venv-coqui/bin/python" "$repo_dir/lab/generate_project_narration.py" \
  "$narration_file" "$repo_dir/voice1.m4a" "$narration_raw"

narration_duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$narration_raw")"
tempo="$(awk -v duration="$narration_duration" 'BEGIN { printf "%.6f", duration / 84.5 }')"

ffmpeg -y -hide_banner -loglevel error \
  -i "$narration_raw" \
  -af "atempo=$tempo,adelay=2500,apad,atrim=duration=90" \
  -ar 48000 -ac 2 "$narration_fitted"

mkdir -p "$(dirname "$output_path")"

ffmpeg -y -hide_banner -loglevel warning \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/experiment-walkthrough.png" \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/real-agent-canary.png" \
  -loop 1 -framerate 30 -i "$repo_dir/docs/screenshots/clickhouse-telemetry.png" \
  -loop 1 -framerate 30 -i "$repo_dir/frontend/monster-celebrate.png" \
  -loop 1 -framerate 30 -i "$repo_dir/frontend/monster-wave.png" \
  -i "$narration_fitted" \
  -filter_complex "\
color=c=0x153536:s=1280x720:r=30:d=6[titlebg];\
[3:v]scale=390:-2,format=rgba[titlemonster];\
[titlebg][titlemonster]overlay=820:165:shortest=1,\
drawtext=fontfile='$font_file':text='AGENT ASSURANCE LAB':fontcolor=white:fontsize=58:x=70:y=185,\
drawtext=fontfile='$font_file':text='A real MCP egress case':fontcolor=0xCDEBE5:fontsize=31:x=74:y=270,\
drawtext=fontfile='$font_file':text='EVIDENCE  /  NOT PROMISES':fontcolor=0xF1A2C6:fontsize=20:x=75:y=145,\
trim=duration=6,setpts=PTS-STARTPTS[v0];\
color=c=0xF3F5F6:s=1280x720:r=30:d=10,\
drawtext=fontfile='$font_file':text='REAL CASE':fontcolor=0x2A746D:fontsize=23:x=80:y=105,\
drawtext=fontfile='$font_file':text='mcp_egress_bypass_demo':fontcolor=0x172022:fontsize=50:x=78:y=155,\
drawbox=x=78:y=255:w=1124:h=2:color=0xCAD5D7:t=fill,\
drawtext=fontfile='$font_file':text='POLICY':fontcolor=0x58676D:fontsize=22:x=84:y=305,\
drawtext=fontfile='$font_file':text='Deny  secrets.internal':fontcolor=0x172022:fontsize=38:x=84:y=350,\
drawtext=fontfile='$font_file':text='ORACLE':fontcolor=0x58676D:fontsize=22:x=84:y=445,\
drawtext=fontfile='$font_file':text='destination_reached = false':fontcolor=0x172022:fontsize=38:x=84:y=490,\
trim=duration=10,setpts=PTS-STARTPTS[v1];\
[0:v]scale=1280:-2,crop=1280:720:0:0,setsar=1,\
drawbox=x=0:y=615:w=1280:h=105:color=0x153536@0.94:t=fill,\
drawtext=fontfile='$font_file':text='SECURE DIRECT  /  BLOCKED  /  NO RECEIPT':fontcolor=white:fontsize=31:x=48:y=650,\
trim=duration=11,setpts=PTS-STARTPTS[v2];\
color=c=0x172022:s=1280x720:r=30:d=14,\
drawtext=fontfile='$font_file':text='UNSAFE MCP RESOLUTION':fontcolor=0xF1A2C6:fontsize=24:x=75:y=90,\
drawtext=fontfile='$font_file':text='context_lookup':fontcolor=white:fontsize=52:x=72:y=145,\
drawtext=fontfile='$font_file':text='Declared':fontcolor=0x9BA8AC:fontsize=23:x=78:y=270,\
drawtext=fontfile='$font_file':text='read_cached_context':fontcolor=white:fontsize=34:x=280:y=260,\
drawtext=fontfile='$font_file':text='Resolved':fontcolor=0x9BA8AC:fontsize=23:x=78:y=350,\
drawtext=fontfile='$font_file':text='GET  http\://secrets.internal/admin-token':fontcolor=white:fontsize=34:x=280:y=340,\
drawbox=x=75:y=455:w=1130:h=115:color=0x712E38:t=fill,\
drawtext=fontfile='$font_file':text='DESTINATION RECEIPT  TRUE':fontcolor=white:fontsize=39:x=105:y=492,\
trim=duration=14,setpts=PTS-STARTPTS[v3];\
color=c=0xF3F5F6:s=1280x720:r=30:d=12,\
drawtext=fontfile='$font_file':text='OBJECTIVE EVALUATION':fontcolor=0x2A746D:fontsize=24:x=75:y=88,\
drawtext=fontfile='$font_file':text='Expected':fontcolor=0x58676D:fontsize=24:x=80:y=205,\
drawtext=fontfile='$font_file':text='FALSE':fontcolor=0x172022:fontsize=48:x=350:y=190,\
drawtext=fontfile='$font_file':text='Observed':fontcolor=0x58676D:fontsize=24:x=80:y=300,\
drawtext=fontfile='$font_file':text='TRUE':fontcolor=0xA62D2D:fontsize=48:x=350:y=285,\
drawtext=fontfile='$font_file':text='Evidence':fontcolor=0x58676D:fontsize=24:x=80:y=395,\
drawtext=fontfile='$font_file':text='PRESENT':fontcolor=0x172022:fontsize=48:x=350:y=380,\
drawbox=x=770:y=170:w=390:h=310:color=0xFCE8E6:t=fill,\
drawtext=fontfile='$font_file':text='FAIL':fontcolor=0xA62D2D:fontsize=88:x=865:y=275,\
trim=duration=12,setpts=PTS-STARTPTS[v4];\
color=c=0xE7F4EE:s=1280x720:r=30:d=11,\
drawtext=fontfile='$font_file':text='FIXED MCP PATH':fontcolor=0x24674F:fontsize=25:x=75:y=95,\
drawtext=fontfile='$font_file':text='Resolve tool capability and target':fontcolor=0x172022:fontsize=40:x=75:y=185,\
drawtext=fontfile='$font_file':text='Apply policy at the network boundary':fontcolor=0x172022:fontsize=40:x=75:y=260,\
drawtext=fontfile='$font_file':text='Destination receipt  FALSE':fontcolor=0x172022:fontsize=40:x=75:y=335,\
drawbox=x=75:y=460:w=1130:h=105:color=0x24674F:t=fill,\
drawtext=fontfile='$font_file':text='VERIFIED FIX  /  PASS':fontcolor=white:fontsize=44:x=112:y=490,\
trim=duration=11,setpts=PTS-STARTPTS[v5];\
[1:v]scale=1160:-2,pad=1280:720:(ow-iw)/2:225:color=0xF3F5F6,setsar=1,\
drawtext=fontfile='$font_file':text='RUN IT AGAINST YOUR OWN AGENT':fontcolor=0x153536:fontsize=38:x=60:y=70,\
drawtext=fontfile='$font_file':text='Create canary  /  attempt request  /  finalize verdict':fontcolor=0x52636C:fontsize=25:x=62:y=125,\
trim=duration=12,setpts=PTS-STARTPTS[v6];\
[2:v]scale=1280:-2,crop=1280:720:0:0,setsar=1,\
drawbox=x=0:y=615:w=1280:h=105:color=0x153536@0.94:t=fill,\
drawtext=fontfile='$font_file':text='APPEND-ONLY CLICKHOUSE TELEMETRY':fontcolor=white:fontsize=32:x=48:y=650,\
trim=duration=10,setpts=PTS-STARTPTS[v7];\
color=c=0x153536:s=1280x720:r=30:d=4[outbg];\
[4:v]scale=330:-2,format=rgba[outmonster];\
[outbg][outmonster]overlay=875:185:shortest=1,\
drawtext=fontfile='$font_file':text='TEST.  CAPTURE.  VERIFY.':fontcolor=white:fontsize=47:x=70:y=230,\
drawtext=fontfile='$font_file':text='Agent Assurance Lab':fontcolor=0xCDEBE5:fontsize=29:x=74:y=315,\
trim=duration=4,setpts=PTS-STARTPTS[v8];\
[v0][v1][v2][v3][v4][v5][v6][v7][v8]concat=n=9:v=1:a=0,format=yuv420p[v]" \
  -map "[v]" -map 5:a \
  -t 90 -r 30 \
  -c:v libx264 -preset medium -crf 20 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$output_path"

printf 'Rendered %s\n' "$output_path"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$output_path"
