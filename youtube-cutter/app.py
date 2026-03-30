import os
import re
import subprocess
import uuid
import glob
import json
import sys
import traceback
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# yt-dlp কে python module হিসেবে call করব — এতে venv এর latest version ব্যবহার হবে
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]


def is_valid_youtube_url(url):
    pattern = r'(https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/|v/|shorts/)|youtu\.be/)[\w-]+'
    return re.match(pattern, url) is not None


def time_to_seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


def run_ytdlp(args, timeout=60):
    cmd = YTDLP_CMD + [
        "--no-check-certificates",
        "--no-cache-dir",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player_client=web",
        "--format", "best[ext=mp4]",
    ] + args

    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/video-info", methods=["POST"])
def video_info():
    data = request.json
    url = data.get("url", "").strip()

    if not url or not is_valid_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    try:
        result = run_ytdlp(["--dump-json", "--no-download", url], timeout=45)

        if result.returncode != 0:
            error_msg = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown error"
            return jsonify({"error": f"yt-dlp error: {error_msg}"}), 400

        info = json.loads(result.stdout)
        video_id = info.get("id", "")

        return jsonify({
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "video_id": video_id,
            "embed_url": f"https://www.youtube.com/embed/{video_id}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cut-download", methods=["POST"])
def cut_download():
    data = request.json
    url = data.get("url", "").strip()
    start_h = int(data.get("start_h", 0))
    start_m = int(data.get("start_m", 0))
    start_s = int(data.get("start_s", 0))
    end_h = int(data.get("end_h", 0))
    end_m = int(data.get("end_m", 0))
    end_s = int(data.get("end_s", 0))

    if not url or not is_valid_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    start_sec = time_to_seconds(start_h, start_m, start_s)
    end_sec = time_to_seconds(end_h, end_m, end_s)

    if end_sec <= start_sec:
        return jsonify({"error": "End time must be greater than start time"}), 400

    duration = end_sec - start_sec
    if duration <= 0:
        return jsonify({"error": "Duration cannot be zero"}), 400

    uid = str(uuid.uuid4())[:8]
    output_path = os.path.join(DOWNLOAD_DIR, f"cut_{uid}.mp4")

    start_ts = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
    duration_ts = f"{(duration // 3600):02d}:{((duration % 3600) // 60):02d}:{(duration % 60):02d}"

    try:
        # yt-dlp দিয়ে direct stream URL বের করা
        result = run_ytdlp([
            "-f", "best[ext=mp4]",
            "-g", url
        ], timeout=45)

        if result.returncode != 0:
            error_msg = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown"
            return jsonify({"error": f"Could not get stream URL: {error_msg}"}), 500

        stream_url = result.stdout.strip().split("\n")[0]

        # ffmpeg দিয়ে cut করা
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", start_ts,
            "-i", stream_url,
            "-t", duration_ts,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]

        proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)

        if proc.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            if os.path.exists(output_path):
                os.remove(output_path)

            # Fallback: re-encode
            ffmpeg_cmd2 = [
                "ffmpeg", "-y",
                "-ss", start_ts,
                "-i", stream_url,
                "-t", duration_ts,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]

            proc2 = subprocess.run(ffmpeg_cmd2, capture_output=True, text=True, timeout=600)
            if proc2.returncode != 0:
                stderr_last = proc2.stderr.strip().split('\n')[-1] if proc2.stderr else "Unknown"
                return jsonify({"error": f"FFmpeg failed: {stderr_last}"}), 500

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 500:
            return jsonify({"error": "Output file is empty or not created"}), 500

        # Get title for filename
        title_result = run_ytdlp(["--get-title", url], timeout=15)
        title = title_result.stdout.strip() if title_result.returncode == 0 else "video"
        safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
        if not safe_title:
            safe_title = "video"

        return jsonify({
            "success": True,
            "file_id": uid,
            "filename": f"{safe_title}_{start_ts.replace(':', '')}-{duration_ts.replace(':', '')}.mp4",
            "file_size": os.path.getsize(output_path)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<file_id>/<filename>")
def download_file(file_id, filename):
    # sanitize file_id
    file_id = re.sub(r'[^a-zA-Z0-9-]', '', file_id)
    filepath = os.path.join(DOWNLOAD_DIR, f"cut_{file_id}.mp4")
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    # cleanup old files on start
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.mp4")):
        try:
            os.remove(f)
        except:
            pass

    print("=" * 50, flush=True)
    print("  YT Cutter Pro - Flask Server Starting", flush=True)
    print(f"  Python: {sys.version}", flush=True)
    print(f"  Download dir: {DOWNLOAD_DIR}", flush=True)
    print("=" * 50, flush=True)

    app.run(host="0.0.0.0", port=8080, debug=False)
