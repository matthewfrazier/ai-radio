#!/usr/bin/env python3
"""Analyze the WRIT-FM library's AUDIO with Essentia-TensorFlow and emit
AcousticBrainz-style high-level features that overlay.py ingests. Runs on a
compute host (rac) -- not the station box -- because it's heavy. Metadata-free,
so it covers the whole library including untagged tracks (the reason the
AcousticBrainz/LLM passes can't).

Pipeline per track: MonoLoader@16kHz -> Discogs-EffNet embedding -> a
classification head per attribute (danceability, mood_happy/sad/aggressive/
relaxed/party, mood_acoustic, voice_instrumental) -> probabilities; plus
RhythmExtractor2013 for BPM. Output shape matches Essentia/AcousticBrainz so
`overlay.py essentia features.json` maps it through axes_from_features().

SETUP (on rac):
  pip install essentia-tensorflow
  bash essentia_models.sh              # downloads the .pb models into ./models
INPUT   tracklist.json  {tracks:{jid:url}}   <- `python3 overlay.py tracklist`
OUTPUT  features.json   {jid:{highlevel:{...},rhythm:{bpm}}}
RUN     python3 essentia_rac.py tracklist.json features.json [models_dir] [workers]

Note: the Jellyfin stream URLs in tracklist.json must be reachable from rac.
Idempotent: re-run resumes, skipping jids already in features.json.
"""
import json
import os
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# The eight Discogs-EffNet classification heads we map to our axes. Each head
# .pb outputs [p(class), p(not-class)] for the two-class model named in the
# tuple; we store it under the AcousticBrainz model name so overlay.py's
# axes_from_features() reads it unchanged.
HEADS = [
    ("danceability", "danceability-discogs-effnet-1", ["danceable", "not_danceable"]),
    ("mood_happy", "mood_happy-discogs-effnet-1", ["happy", "not_happy"]),
    ("mood_sad", "mood_sad-discogs-effnet-1", ["sad", "not_sad"]),
    ("mood_aggressive", "mood_aggressive-discogs-effnet-1", ["aggressive", "not_aggressive"]),
    ("mood_relaxed", "mood_relaxed-discogs-effnet-1", ["relaxed", "not_relaxed"]),
    ("mood_party", "mood_party-discogs-effnet-1", ["party", "not_party"]),
    ("mood_acoustic", "mood_acoustic-discogs-effnet-1", ["acoustic", "not_acoustic"]),
    ("voice_instrumental", "voice_instrumental-discogs-effnet-1", ["instrumental", "voice"]),
]
EMBED_MODEL = "discogs-effnet-bs64-1.pb"


def _load_models(models_dir):
    from essentia.standard import TensorflowPredictEffnetDiscogs, TensorflowPredict2D
    embed = TensorflowPredictEffnetDiscogs(
        graphFilename=os.path.join(models_dir, EMBED_MODEL), output="PartitionedCall:1")
    heads = {}
    for ab_name, pb, _classes in HEADS:
        heads[ab_name] = TensorflowPredict2D(
            graphFilename=os.path.join(models_dir, pb + ".pb"), output="model/Softmax")
    return embed, heads


def analyze(url, embed, heads):
    from essentia.standard import MonoLoader, RhythmExtractor2013
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tmp = tf.name
    try:
        urllib.request.urlretrieve(url, tmp)
        emb = embed(MonoLoader(filename=tmp, sampleRate=16000, resampleQuality=4)())
        hl = {}
        for ab_name, _pb, classes in HEADS:
            preds = heads[ab_name](emb)          # frames x 2
            mean = [sum(col) / len(col) for col in zip(*preds)]
            hl[ab_name] = {"all": {classes[0]: round(mean[0], 4), classes[1]: round(mean[1], 4)}}
        # BPM at 44.1k (RhythmExtractor wants the full-rate signal)
        bpm = float(RhythmExtractor2013(method="multifeature")(MonoLoader(filename=tmp)())[0])
        return {"highlevel": hl, "rhythm": {"bpm": round(bpm, 1)}}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main():
    tl_path = sys.argv[1] if len(sys.argv) > 1 else "tracklist.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "features.json"
    models_dir = sys.argv[3] if len(sys.argv) > 3 else "models"
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4

    urls = json.load(open(tl_path))["tracks"]
    out = json.load(open(out_path)) if os.path.exists(out_path) else {}
    todo = [(jid, u) for jid, u in urls.items() if jid not in out]
    print("analyzing %d tracks (%d already done), %d workers" % (len(todo), len(out), workers))
    embed, heads = _load_models(models_dir)

    done = [0]

    def work(item):
        jid, url = item
        try:
            out[jid] = analyze(url, embed, heads)
        except Exception as e:
            print("  fail %s: %s" % (jid, str(e)[:80]))
        done[0] += 1
        if done[0] % 100 == 0:
            tmp = out_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(out, f)
            os.replace(tmp, out_path)
            print("  %d/%d" % (done[0], len(todo)))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    with open(out_path, "w") as f:
        json.dump(out, f)
    print("wrote %s (%d tracks). Pull it to the station and run: overlay.py essentia %s"
          % (out_path, len(out), out_path))


if __name__ == "__main__":
    main()
