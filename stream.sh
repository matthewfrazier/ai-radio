#!/bin/bash
set -uo pipefail
# Icecast source password: .stubenv is chmod 600 + gitignored. Never inline SRCPW here.
source /opt/writ-fm/.stubenv
PLAYLIST=/opt/writ-fm/music_playlist.txt
pkill -9 -f 'ffmpeg.*icecast' 2>/dev/null || true
sleep 1
exec ffmpeg -hide_banner -loglevel warning -nostdin -re -stream_loop -1 \
  -protocol_whitelist file,http,https,tcp,tls,crypto \
  -f concat -safe 0 -i "$PLAYLIST" \
  -c:a libvorbis -q:a 4 -content_type audio/ogg -f ogg \
  "icecast://source:${SRCPW}@127.0.0.1:8000/stream"
