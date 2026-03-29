import os
import re
import subprocess
import uuid
import glob
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def is_valid_youtube_url(url):
    pattern = r'(https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/|v/|shorts/)|youtu\.be/)[\w-]+'
    return re.match(pattern, url) is not None


def time_to_seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


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
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": "Could not fetch video info"}), 400

        import json
        info = json.loads(result.stdout)
        return jsonify({
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "video_id": info.get("id", ""),
            "embed_url": f"https://www.youtube.com/embed/{info.get('id', '')}"
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
        # Step 1: yt-dlp দিয়ে best format URL বের করা
        result = subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4]/best", "-g", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": "Could not get video stream URL"}), 500

        stream_url = result.stdout.strip().split("\n")[0]

        # Step 2: ffmpeg দিয়ে cut করা
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", start_ts,
            "-i", stream_url,
            "-t", duration_ts,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]

        proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)

        if proc.returncode != 0 or not os.path.exists(output_path):
            # fallback: re-encode
            ffmpeg_cmd2 = [
                "ffmpeg", "-y",
                "-ss", start_ts,
                "-i", stream_url,
                "-t", duration_ts,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac",
                output_path
            ]
            proc2 = subprocess.run(ffmpeg_cmd2, capture_output=True, text=True, timeout=300)
            if proc2.returncode != 0:
                return jsonify({"error": "FFmpeg processing failed"}), 500

        # Get title for filename
        title_result = subprocess.run(
            ["yt-dlp", "--get-title", url],
            capture_output=True, text=True, timeout=15
        )
        title = title_result.stdout.strip() if title_result.returncode == 0 else "video"
        safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()

        return jsonify({
            "success": True,
            "file_id": uid,
            "filename": f"{safe_title}_{start_ts.replace(':', '')}-{duration_ts.replace(':', '')}.mp4"
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Process timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<file_id>/<filename>")
def download_file(file_id, filename):
    filepath = os.path.join(DOWNLOAD_DIR, f"cut_{file_id}.mp4")
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    # cleanup old files
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.mp4")):
        try:
            os.remove(f)
        except:
            pass
    app.run(host="0.0.0.0", port=8080, debug=False)