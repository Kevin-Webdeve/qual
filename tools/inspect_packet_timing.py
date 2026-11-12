"""Summarize an FFmpeg framehash scan and MP4 timing boxes without changing media."""
import argparse
import collections
import json
import re
import struct
from fractions import Fraction
from pathlib import Path


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise ValueError("Invalid MP4 box boundary")
        yield kind.decode("latin1"), data[offset + header:offset + size]
        offset += size


def timing_header(data):
    version = data[0]
    offset = 20 if version == 1 else 12
    scale = struct.unpack_from(">I", data, offset)[0]
    duration = struct.unpack_from(">Q" if version == 1 else ">I", data, offset + 4)[0]
    return {"timescale": scale, "duration_ticks": duration, "duration_seconds": duration / scale}


def movie_timing(path):
    top = []
    moov = None
    with path.open("rb") as stream:
        file_size = path.stat().st_size
        offset = 0
        while offset + 8 <= file_size:
            stream.seek(offset)
            size, kind = struct.unpack(">I4s", stream.read(8))
            header = 8
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
                header = 16
            elif size == 0:
                size = file_size - offset
            if size < header or offset + size > file_size:
                raise ValueError("Invalid top-level MP4 box")
            top.append({"type": kind.decode("latin1"), "offset": offset, "bytes": size})
            if kind == b"moov":
                if size > 64 * 1024**2:
                    raise ValueError("Movie metadata exceeds diagnostic limit")
                moov = stream.read(size - header)
            offset += size
    result = {"top_boxes": top, "tracks": []}
    if moov is None:
        return result
    for kind, data in boxes(moov):
        if kind == "mvhd":
            result["movie_header"] = timing_header(data)
        elif kind == "trak":
            track = {}
            for child, payload in boxes(data):
                if child == "mdia":
                    for name, value in boxes(payload):
                        if name == "hdlr":
                            track["type"] = value[8:12].decode("latin1")
                        elif name == "mdhd":
                            track["media_header"] = timing_header(value)
                elif child == "edts":
                    for name, value in boxes(payload):
                        if name != "elst":
                            continue
                        version = value[0]
                        count = struct.unpack_from(">I", value, 4)[0]
                        edits = []
                        offset = 8
                        for _ in range(count):
                            duration, media_time, rate_integer, rate_fraction = struct.unpack_from(">Qqhh" if version == 1 else ">Iihh", value, offset)
                            edits.append({"segment_duration_movie_ticks": duration, "media_time": media_time,
                                          "rate": rate_integer + rate_fraction / 65536})
                            offset += 20 if version == 1 else 12
                        track["edit_list"] = edits
            result["tracks"].append(track)
    return result


def packet_timing(manifest):
    streams = {}
    with manifest.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#tb "):
                number, ratio = line[4:].split(":", 1)
                streams.setdefault(int(number), {})["time_base"] = Fraction(ratio.strip())
            elif line.startswith("#media_type "):
                number, name = line[12:].split(":", 1)
                streams.setdefault(int(number), {})["type"] = name.strip()
            elif line.strip() and not line.startswith("#"):
                columns = line.split(",")
                number = int(columns[0])
                streams[number].setdefault("packets", []).append(tuple(int(columns[index]) for index in (1, 2, 3, 4)))
    output = {}
    for number, value in streams.items():
        time_base = value["time_base"]
        packets = value["packets"]
        pts = sorted(packet[1] for packet in packets)
        intervals = collections.Counter(second-first for first, second in zip(pts, pts[1:]))
        end = max(packet[1] + packet[2] for packet in packets)
        begin = min(pts)
        duration = (end-begin) * time_base
        output[number] = {"type": value.get("type"), "time_base": str(time_base), "packet_count": len(packets),
                          "first_pts_seconds": float(begin * time_base), "last_end_seconds": float(end * time_base),
                          "presentation_span_seconds": float(duration),
                          "packets_per_second": float(len(packets) / duration),
                          "presentation_intervals": [{"ticks": ticks, "seconds": float(ticks * time_base), "count": count}
                                                     for ticks, count in sorted(intervals.items())],
                          "duplicate_presentation_timestamps": sum(count for ticks, count in intervals.items() if ticks == 0),
                          "dts_backwards_count": sum(second[0] < first[0] for first, second in zip(packets, packets[1:])),
                          "packet_duration_counts": dict(collections.Counter(packet[2] for packet in packets)),
                          "payload_bytes": sum(packet[3] for packet in packets)}
    return output


def inspect(source, manifest, headers):
    header_values = {}
    for name in ("profile_idc", "level_idc", "num_units_in_tick", "time_scale", "fixed_frame_rate_flag", "max_num_ref_frames"):
        found = re.search(rf"\b{name}\s+[01]+\s*=\s*(\d+)", headers)
        if found:
            header_values[name] = int(found[1])
    return {"source": str(source), "file_bytes": source.stat().st_size,
            "packet_timing": packet_timing(manifest), "mp4_timing": movie_timing(source), "h264_header": header_values,
            "limitations": ["Timing metadata checks do not establish perceptual lip-sync or TikTok's delivered playback.",
                            "An unset fixed-frame-rate flag is valid and does not by itself prove that the source file is faulty."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("headers", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = inspect(args.source, args.manifest, args.headers.read_text(encoding="utf-8"))
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
