"""Create a verified header-only comparison for a scanned constant-rate H.264 MP4."""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ffmpeg, probe, process_options


def run(arguments, timeout=600):
    result = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *arguments], capture_output=True,
                            timeout=timeout, **process_options())
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-5000:])
    return result


def records(path):
    streams = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#tb "):
                number, ratio = line[4:].split(":", 1)
                streams.setdefault(int(number), {})["time_base"] = Fraction(ratio.strip())
            elif line.strip() and not line.startswith("#"):
                columns = [item.strip() for item in line.split(",")]
                number = int(columns[0])
                streams[number].setdefault("packets", []).append((int(columns[1]), int(columns[2]), int(columns[3]), int(columns[4]), columns[5]))
    return streams


def compare(original, prepared):
    before, after = records(original), records(prepared)
    if set(before) != set(after):
        raise ValueError("The prepared file changed its stream count.")
    result = {}
    for number, source in before.items():
        output = after[number]
        if len(source["packets"]) != len(output["packets"]):
            raise ValueError("The prepared file changed its packet count.")
        maximum_difference = Fraction(0)
        for first, second in zip(source["packets"], output["packets"]):
            if first[3:] != second[3:]:
                raise ValueError(f"Stream {number} packet data changed unexpectedly.")
            for index in (0, 1, 2):
                maximum_difference = max(maximum_difference, abs(first[index] * source["time_base"] - second[index] * output["time_base"]))
        if maximum_difference > Fraction(1, 100_000):
            raise ValueError("The prepared file changed packet timing by more than 10 microseconds.")
        result[number] = {"packet_count": len(source["packets"]), "all_packet_payload_hashes_unchanged": True,
                          "maximum_timing_difference_seconds": float(maximum_difference)}
    return result


def sample_hashes(path, moment):
    text = run(["-loglevel", "error", "-ss", str(moment), "-i", str(path), "-t", "0.25", "-map", "0:v:0", "-an",
                "-vf", "scale=320:180", "-fps_mode", "passthrough", "-f", "framemd5", "-"], timeout=180).stdout.decode()
    return [line.split(",")[-1].strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if source == destination or destination.exists():
        raise ValueError("Use a new output filename; original and existing files are preserved.")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    if Path(audit["source"]).resolve() != source or audit["file_bytes"] != source.stat().st_size:
        raise ValueError("The audit does not match the selected source.")
    video = audit["packet_timing"]["0"]
    if len(video["presentation_intervals"]) != 1 or video["presentation_intervals"][0]["ticks"] <= 0:
        raise ValueError("Only a verified constant-rate source can receive this comparison header.")
    rate = 1 / (Fraction(video["time_base"]) * video["presentation_intervals"][0]["ticks"])
    tick_rate = rate * 2
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.partial.mp4")
    work = args.audit.parent
    try:
        print(f"Copying media with an H.264 clock matching {rate} fps; no encoding...", flush=True)
        run(["-loglevel", "error", "-n", "-copyts", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
             "-bsf:v", f"h264_metadata=tick_rate={tick_rate.numerator}/{tick_rate.denominator}",
             "-video_track_timescale", "240000", "-avoid_negative_ts", "disabled", "-movflags", "+faststart", str(temporary)])
        print("Verifying every video/audio packet hash, timestamp, and duration...", flush=True)
        manifest = work / "comparison.framehash"
        if manifest.exists():
            raise ValueError("Comparison diagnostic already exists; choose a fresh audit directory.")
        run(["-loglevel", "error", "-n", "-i", str(temporary), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
             "-f", "framehash", "-hash", "sha256", str(manifest)])
        verification = compare(args.source_manifest, manifest)
        headers = run(["-loglevel", "trace", "-i", str(temporary), "-map", "0:v:0", "-c:v", "copy",
                       "-bsf:v", "trace_headers", "-frames:v", "1", "-f", "null", "-"]).stderr.decode(errors="replace")
        (work / "comparison-headers.txt").write_text(headers, encoding="utf-8")
        header_values = {}
        for name in ("time_scale", "num_units_in_tick", "fixed_frame_rate_flag"):
            found = re.search(rf"\b{name}\s+[01]+\s*=\s*(\d+)", headers)
            if not found:
                raise ValueError("The rewritten H.264 header could not be verified.")
            header_values[name] = int(found[1])
        if Fraction(header_values["time_scale"], header_values["num_units_in_tick"]) != tick_rate:
            raise ValueError("Unexpected timing header in output.")
        print("Comparing decoded frames near the beginning, middle, and end...", flush=True)
        samples = []
        for moment in (2.0, 85.0, 170.0):
            if moment + 0.25 >= video["presentation_span_seconds"]:
                continue
            first, second = sample_hashes(source, moment), sample_hashes(temporary, moment)
            if not first or first != second:
                raise ValueError("Decoded comparison frames changed unexpectedly.")
            samples.append({"start_seconds": moment, "decoded_frames_compared": len(first), "decoded_hashes_equal": True})
        info = probe(temporary)
        os.replace(temporary, destination)
        report = {"source": str(source), "comparison": str(destination), "video_reencoded": False,
                  "audio_reencoded": False, "picture_packet_payloads_unchanged": True,
                  "width": info.width, "height": info.height, "fps": info.fps, "duration_seconds": info.duration,
                  "header": header_values, "packet_verification": verification, "decoded_sample_verification": samples,
                  "note": "Header-only compatibility comparison. No claim of fixing TikTok playback or bypassing compression."}
        destination.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
