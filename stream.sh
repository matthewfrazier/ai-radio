#!/bin/bash
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/.stubenv" ] && . "$DIR/.stubenv"
SRCPW="${SRCPW:?set SRCPW in .stubenv (icecast source password)}"
PLAYLIST=/opt/writ-fm/music_playlist.txt
pkill -9 -f 'ffmpeg.*icecast' 2>/dev/null || true
sleep 1
exec ffmpeg -hide_banner -loglevel warning -nostdin -re -stream_loop -1 \
  -protocol_whitelist file,http,https,tcp,tls,crypto \
  -f concat -safe 0 -i "$PLAYLIST" \
  -c:a libvorbis -q:a 4 -content_type audio/ogg -f ogg \
  "icecast://source:${SRCPW}@127.0.0.1:8000/stream"
