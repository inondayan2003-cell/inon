"""Download Hebrew captions for every video in a YouTube playlist.

Run on a home computer (YouTube blocks cloud servers):
    pip install -U yt-dlp
    python fetch_transcripts.py            # Academy playlist by default
    python fetch_transcripts.py <playlist_url> <out_dir>

Writes one clean .txt per video: "<index> - <video_id>.txt" with the title
and URL on top, and a timestamp ("[mm:ss]") at the start of each caption line.
Already-downloaded videos are skipped, so it can be stopped and re-run.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ACADEMY = "https://www.youtube.com/playlist?list=PLrNmo94geFHYKEZnHR6nDkPTtLWNG61a8"


def list_playlist(url):
    out = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "%(playlist_index)s\t%(id)s\t%(title)s", url],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line.split("\t", 2) for line in out.splitlines() if line.count("\t") == 2]


def vtt_to_text(vtt):
    lines, last = [], None
    for block in vtt.split("\n\n"):
        m = re.search(r"(\d+):(\d+):(\d+)\.\d+ -->", block)
        if not m:
            continue
        text = " ".join(
            re.sub(r"<[^>]+>", "", l).strip()
            for l in block.splitlines()
            if "-->" not in l and l.strip()
        ).strip()
        if not text or text == last:
            continue
        last = text
        h, mi, s = map(int, m.groups())
        lines.append(f"[{h * 60 + mi:02d}:{s:02d}] {text}")
    return "\n".join(lines)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ACADEMY
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "transcripts")
    tmp = out / "_vtt"
    tmp.mkdir(parents=True, exist_ok=True)
    videos = list_playlist(url)
    print(f"{len(videos)} videos")
    missing = []
    for idx, vid, title in videos:
        dest = out / f"{int(idx):03d} - {vid}.txt"
        if dest.exists():
            continue
        subprocess.run(
            ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", "iw.*,he.*", "--sub-format", "vtt",
             "-o", str(tmp / vid), f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True,
        )
        subs = sorted(tmp.glob(f"{vid}*.vtt"))
        if not subs:
            missing.append(f"{idx}\t{vid}\t{title}")
            print(f"[{idx}] no Hebrew captions: {title}")
            continue
        body = vtt_to_text(subs[0].read_text(encoding="utf-8"))
        dest.write_text(f"{title}\nhttps://youtu.be/{vid}\n\n{body}\n", encoding="utf-8")
        print(f"[{idx}] ok: {title}")
        time.sleep(2)  # be gentle with YouTube
    (out / "missing.tsv").write_text("\n".join(missing), encoding="utf-8")
    print(f"done; {len(missing)} without captions (see missing.tsv)")


if __name__ == "__main__":
    main()
