from flask import Flask, render_template, request, send_file, redirect, url_for, session, jsonify
import os
import tempfile
import re
import unicodedata
from werkzeug.utils import secure_filename
from time import time, sleep
import threading

app = Flask(__name__)
app.secret_key = "super_secret_key"

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ========= 公共函数 =========
def clean_line(line: str) -> str:
    """去掉不可见字符、前导+@、标准化 Unicode 并转换小写"""
    if not line:
        return ""
    line = re.sub(r"[\u200b\u200e\u200f\uFEFF\s\u00a0\t]", "", line)
    line = line.lstrip("+@")
    line = unicodedata.normalize('NFKC', line)
    return line.lower()

ENABLE_BLACKLIST = False
blacklist = ["haihua", "chuhai", "benchi", "818", "databox", "dolphin", "diggoldsl", "juejin"]

def is_valid_username(name: str) -> bool:
    if not name:
        return False
    if name.lower().endswith("bot"):
        return False
    if ENABLE_BLACKLIST:
        if 'bot' in name:
            return False
        for word in blacklist:
            if word in name:
                return False
    return True

# ========= 后台任务管理 =========
tasks = {}  # task_id -> {"progress":x,"file":path or dict(A,B)}

def update_progress(task_id, percent):
    if task_id in tasks:
        tasks[task_id]["progress"] = percent

# ========= 后台任务函数 =========
def process_merge_task(file_paths, task_id):
    seen = set()
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix="_merge.txt", mode="w", encoding="utf-8")
    total = sum(1 for path in file_paths for _ in open(path, "r", encoding="utf-8-sig"))
    done = 0
    for path in file_paths:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                done += 1
                line_clean = clean_line(line)
                if is_valid_username(line_clean) and line_clean not in seen:
                    seen.add(line_clean)
                    output_file.write(line_clean + "\n")
                if done % 500 == 0:
                    update_progress(task_id, int(done / total * 100))
    output_file.close()
    tasks[task_id]["file"] = output_file.name
    tasks[task_id]["progress"] = 100

def process_compare_task(file_a_path, file_b_path, task_id):
    set_a, set_b = set(), set()
    total = sum(1 for _ in open(file_a_path, "r", encoding="utf-8-sig")) + sum(1 for _ in open(file_b_path, "r", encoding="utf-8-sig"))
    done = 0

    for path, target_set in [(file_a_path, set_a), (file_b_path, set_b)]:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                done += 1
                line_clean = clean_line(line)
                if is_valid_username(line_clean):
                    target_set.add(line_clean)
                if done % 500 == 0:
                    update_progress(task_id, int(done / total * 50))

    unique_a = set_a - set_b
    unique_b = set_b - set_a

    output_a = tempfile.NamedTemporaryFile(delete=False, suffix="_A.txt", mode="w", encoding="utf-8")
    output_b = tempfile.NamedTemporaryFile(delete=False, suffix="_B.txt", mode="w", encoding="utf-8")

    for i, line in enumerate(sorted(unique_a)):
        output_a.write(line + "\n")
        if i % 500 == 0:
            update_progress(task_id, 50 + int(i / (len(unique_a) + 1) * 25))
    for i, line in enumerate(sorted(unique_b)):
        output_b.write(line + "\n")
        if i % 500 == 0:
            update_progress(task_id, 75 + int(i / (len(unique_b) + 1) * 25))

    output_a.close()
    output_b.close()
    tasks[task_id]["file"] = {"A": output_a.name, "B": output_b.name}
    tasks[task_id]["progress"] = 100

def process_username_task(file_path, task_id):
    seen = set()
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix="_username.txt", mode="w", encoding="utf-8")
    total = sum(1 for _ in open(file_path, "r", encoding="utf-8-sig"))
    done = 0
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            done += 1
            line_clean = clean_line(line)
            if is_valid_username(line_clean) and line_clean not in seen:
                seen.add(line_clean)
                output_file.write(line_clean + "\n")
            if done % 500 == 0:
                update_progress(task_id, int(done / total * 100))
    output_file.close()
    tasks[task_id]["file"] = output_file.name
    tasks[task_id]["progress"] = 100

# ========= 路由 =========
@app.route("/")
def index():
    bg_url = session.get("bg_url", url_for('static', filename='default_bg.jpg'))
    return render_template("index.html", bg_url=bg_url, timestamp=int(time()))

@app.route("/upload_bg", methods=["POST"])
def upload_bg():
    file = request.files.get("bg_file")
    if not file:
        return redirect(url_for("index"))
    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)
    session["bg_url"] = url_for('static', filename=filename)
    return redirect(url_for("index"))

@app.route("/merge", methods=["POST"])
def merge():
    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        return jsonify({"status":"error","message":"请至少上传一个文件"})
    tmp_paths = []
    for f in uploaded_files:
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        f.save(tmp_file.name)
        tmp_paths.append(tmp_file.name)
    task_id = str(len(tasks)+1)
    tasks[task_id] = {"progress": 0}
    threading.Thread(target=process_merge_task, args=(tmp_paths, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

@app.route("/compare", methods=["POST"])
def compare():
    file_a = request.files.get("file_a")
    file_b = request.files.get("file_b")
    if not file_a or not file_b:
        return jsonify({"status":"error","message":"请上传 A 和 B 两个文件"})
    tmp_a = tempfile.NamedTemporaryFile(delete=False, suffix="_A_input.txt")
    tmp_b = tempfile.NamedTemporaryFile(delete=False, suffix="_B_input.txt")
    file_a.save(tmp_a.name)
    file_b.save(tmp_b.name)
    task_id = str(len(tasks)+1)
    tasks[task_id] = {"progress": 0}
    threading.Thread(target=process_compare_task, args=(tmp_a.name, tmp_b.name, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

@app.route("/username_dedup", methods=["POST"])
def username_dedup():
    uploaded_file = request.files.get("username_file")
    if not uploaded_file:
        return jsonify({"status":"error","message":"请上传文件"})
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix="_input.txt")
    uploaded_file.save(tmp_file.name)
    task_id = str(len(tasks)+1)
    tasks[task_id] = {"progress": 0}
    threading.Thread(target=process_username_task, args=(tmp_file.name, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

@app.route("/status/<task_id>")
def status(task_id):
    if task_id not in tasks:
        return jsonify({"status":"processing","progress":0})

    info = tasks[task_id]
    progress = info.get("progress", 0)
    if progress < 100:
        return jsonify({"status":"processing","progress":progress})

    file = info.get("file")
    if isinstance(file, str):
        count = len(open(file, "r", encoding="utf-8").readlines())
        return jsonify({"status":"ready","count":count,"download_url":f"/download/{task_id}"})
    elif isinstance(file, dict):
        count_a = len(open(file["A"], "r", encoding="utf-8").readlines())
        count_b = len(open(file["B"], "r", encoding="utf-8").readlines())
        return jsonify({
            "status":"ready","count_a":count_a,"count_b":count_b,
            "download_url_a":f"/download/{task_id}_A","download_url_b":f"/download/{task_id}_B"
        })

@app.route("/download/<task_id>")
def download(task_id):
    if "_" in task_id:
        base_id, suffix = task_id.split("_", 1)
        if base_id in tasks and suffix in tasks[base_id]["file"]:
            file_path = tasks[base_id]["file"][suffix]
            count = len(open(file_path, "r", encoding="utf-8").readlines())
            return send_file(file_path, as_attachment=True, download_name=f"{suffix}_{count}.txt")
    else:
        if task_id in tasks:
            file_path = tasks[task_id]["file"]
            count = len(open(file_path, "r", encoding="utf-8").readlines())
            return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")
    return "<h3>文件不存在或已下载</h3>"

if __name__ == "__main__":
    app.run(port=5001)
