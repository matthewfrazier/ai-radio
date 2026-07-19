#!/bin/bash
# Download the Essentia-TensorFlow models essentia_rac.py needs, into ./models.
# Run on rac after: pip install essentia-tensorflow
set -euo pipefail
DIR="${1:-models}"
mkdir -p "$DIR"
BASE="https://essentia.upf.edu/models"

# Discogs-EffNet embedding model (shared by all heads).
curl -fSL -o "$DIR/discogs-effnet-bs64-1.pb" \
  "$BASE/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb"

# Two-class classification heads mapped to our axes (see essentia_rac.HEADS).
for h in danceability mood_happy mood_sad mood_aggressive mood_relaxed mood_party mood_acoustic voice_instrumental; do
  curl -fSL -o "$DIR/${h}-discogs-effnet-1.pb" \
    "$BASE/classification-heads/${h}/${h}-discogs-effnet-1.pb"
done

echo "models in $DIR:"
ls -1 "$DIR"
