#!/usr/bin/env python3
"""Analyze the WRIT-FM library's AUDIO with Essentia-TensorFlow and emit
AcousticBrainz-style high-level features that overlay.py ingests. Runs on the
GPU box (rac-wsl). Metadata-free, so it covers the whole library including
untagged tracks (the reason the AcousticBrainz/LLM passes can't).

Design: SEQUENTIAL per process. essentia's Python bindings hold the GIL for the
whole of compute(), so a ThreadPoolExecutor gives no real parallelism and, worse,
one thread's ~1s BPM compute starves the main thread and the downloads -> the
pipeline stalls at 0 done (observed via py-spy). Parallelism instead comes from
running N sharded processes that share the GPU (TF_FORCE_GPU_ALLOW_GROWTH=true so
they don't each grab all VRAM). Each process is a plain loop -> can't deadlock.

GPU: the bundled TF 2.5 drives the RTX 5070 (sm_120) via the pip CUDA-11 runtime
+ cuDNN 8 libs and driver PTX-JIT (first track pays a one-time ptxas warmup).

SETUP (rac-wsl):  pip install essentia-tensorflow ; bash essentia_models.sh
INPUT   tracklist.json  {tracks:{jid:url}}   <- `python3 overlay.py tracklist`
OUTPUT  features.json   {jid:{highlevel:{...},rhythm:{bpm}}}
RUN     python3 essentia_rac.py tracklist.json out.json [models_dir] [shard] [nshard]
Idempotent: re-run resumes (skips done, retries errored).
"""
import json
import os
import sys
import tempfile
import urllib.request

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # silence TF's per-call spam

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
    import essentia
    essentia.log.warningActive = False
    essentia.log.infoActive = False
    from essentia.standard import TensorflowPredictEffnetDiscogs, TensorflowPredict2D
    embed = TensorflowPredictEffnetDiscogs(
        graphFilename=os.path.join(models_dir, EMBED_MODEL), output="PartitionedCall:1")
    heads = {ab: TensorflowPredict2D(
        graphFilename=os.path.join(models_dir, pb + ".pb"), output="model/Softmax")
        for ab, pb, _c in HEADS}
    return embed, heads


def analyze(url, embed, heads):
    """Download + decode@16k + BPM (CPU) then Discogs-EffNet embed + heads (GPU).
    Fresh MonoLoader/RhythmExtractor per call keeps state local to this track."""
    from essentia.standard import MonoLoader, RhythmExtractor2013
    tmp = tempfile.mktemp(suffix=".mp3")
    try:
        urllib.request.urlretrieve(url, tmp)
        a16 = MonoLoader(filename=tmp, sampleRate=16000, resampleQuality=4)()
        bpm = float(RhythmExtractor2013(method="degara")(MonoLoader(filename=tmp)())[0])
        emb = embed(a16)
        hl = {}
        for ab, _pb, classes in HEADS:
            preds = heads[ab](emb)
            mean = [float(sum(col) / len(col)) for col in zip(*preds)]
            hl[ab] = {"all": {classes[0]: round(mean[0], 4), classes[1]: round(mean[1], 4)}}
        return {"highlevel": hl, "rhythm": {"bpm": round(bpm, 1)}}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _checkpoint(out, out_path):
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, out_path)


def main():
    tl_path = sys.argv[1] if len(sys.argv) > 1 else "tracklist.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "features.json"
    models_dir = sys.argv[3] if len(sys.argv) > 3 else "models"
    shard = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    nshard = int(sys.argv[5]) if len(sys.argv) > 5 else 1

    with open(tl_path) as f:
        urls = json.load(f)["tracks"]
    out = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            out = json.load(f)
    # shard by position so N independent processes split the library and share
    # the GPU; each writes its own out file (no concurrent-write clobbering).
    items = [x for i, x in enumerate(urls.items()) if i % nshard == shard]
    todo = [(j, u) for j, u in items if j not in out or "error" in out.get(j, {})]
    print("shard %d/%d: analyzing %d tracks (%d done)"
          % (shard, nshard, len(todo), len(out)), flush=True)

    embed, heads = _load_models(models_dir)
    done = fails = 0
    total = len(todo)
    for jid, url in todo:
        try:
            out[jid] = analyze(url, embed, heads)
        except Exception as e:
            out[jid] = {"error": str(e)[:140]}
            fails += 1
        done += 1
        if done % 50 == 0:
            _checkpoint(out, out_path)
            print("  %d/%d (%d failed)" % (done, total, fails), flush=True)
    _checkpoint(out, out_path)
    print("wrote %s (%d total, %d failed this run). On the station: overlay.py essentia %s"
          % (out_path, len(out), fails, out_path), flush=True)


if __name__ == "__main__":
    main()
