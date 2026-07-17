#!/bin/bash
set -uo pipefail
# Icecast source password: .stubenv is chmod 600 + gitignored. Never inline SRCPW here.
source /opt/writ-fm/.stubenv
PLAYLIST=/opt/writ-fm/music_playlist.txt
# No pkill here: systemd owns each ffmpeg via its unit cgroup and arbitrates
# the mount via Conflicts=, so a broad `pkill ffmpeg.*icecast` would be a
# footgun that kills the block player's sink during a handoff. The short
# sleep lets Icecast release the mount from the source we're replacing.
sleep 1
exec ffmpeg -hide_banner -loglevel warning -nostdin -re -stream_loop -1 \
  -protocol_whitelist file,http,https,tcp,tls,crypto \
  -f concat -safe 0 -i "$PLAYLIST" \
  -c:a libvorbis -q:a 4 -content_type audio/ogg -f ogg \
  "icecast://source:${SRCPW}@127.0.0.1:8000/stream"
