from flask import Flask, render_template, request, send_file, redirect, url_for, session, jsonify
import os
import tempfile
import re
import unicodedata
from werkzeug.utils import secure_filename
from time import time
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
blacklist = [
    "haihua", "chuhai", "benchi", "818", "databox", "dolphin", 
    "diggoldsl", "juejin"
]

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
tasks = {}  # task_id -> 文件路径

def process_merge_task(file_paths, task_id):
    """多文件合并去重"""
    seen = set()
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix="_merge.txt", mode="w", encoding="utf-8")
    for path in file_paths:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line_clean = clean_line(line)
                if is_valid_username(line_clean) and line_clean not in seen:
                    seen.add(line_clean)
                    output_file.write(line_clean + "\n")
    output_file.close()
    tasks[task_id] = output_file.name

def process_compare_task(file_a_path, file_b_path, task_id):
    """AB 文件对比去重"""
    set_a, set_b = set(), set()
    with open(file_a_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line_clean = clean_line(line)
            if is_valid_username(line_clean):
                set_a.add(line_clean)
    with open(file_b_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line_clean = clean_line(line)
            if is_valid_username(line_clean):
                set_b.add(line_clean)
    unique_a = set_a - set_b
    unique_b = set_b - set_a

    output_a = tempfile.NamedTemporaryFile(delete=False, suffix="_A.txt", mode="w", encoding="utf-8")
    output_b = tempfile.NamedTemporaryFile(delete=False, suffix="_B.txt", mode="w", encoding="utf-8")
    for line in sorted(unique_a):
        output_a.write(line + "\n")
    for line in sorted(unique_b):
        output_b.write(line + "\n")
    output_a.close()
    output_b.close()
    tasks[task_id+"_A"] = output_a.name
    tasks[task_id+"_B"] = output_b.name

def process_username_task(file_path, task_id):
    """单文件用户名去重"""
    seen = set()
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix="_username.txt", mode="w", encoding="utf-8")
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line_clean = clean_line(line)
            if is_valid_username(line_clean) and line_clean not in seen:
                seen.add(line_clean)
                output_file.write(line_clean + "\n")
    output_file.close()
    tasks[task_id] = output_file.name

# ========= 网页路由 =========
@app.route("/", methods=["GET"])
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

# ========= 合并去重 =========
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
    threading.Thread(target=process_merge_task, args=(tmp_paths, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

# ========= 对比去重 =========
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
    threading.Thread(target=process_compare_task, args=(tmp_a.name, tmp_b.name, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

# ========= 用户名去重 =========
@app.route("/username_dedup", methods=["POST"])
def username_dedup():
    uploaded_file = request.files.get("username_file")
    if not uploaded_file:
        return jsonify({"status":"error","message":"请上传文件"})
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix="_input.txt")
    uploaded_file.save(tmp_file.name)
    task_id = str(len(tasks)+1)
    threading.Thread(target=process_username_task, args=(tmp_file.name, task_id)).start()
    return jsonify({"status":"success","task_id":task_id})

# ========= 下载/任务状态 =========
@app.route("/status/<task_id>")
def status(task_id):
    if task_id in tasks:
        file_path = tasks.pop(task_id)
        count = len(open(file_path, "r", encoding="utf-8").readlines())
        return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")
    else:
        return "<h3>处理中，请稍后刷新页面...</h3>"

if __name__ == "__main__":
    app.run(port=5001)
