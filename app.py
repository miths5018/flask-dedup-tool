from flask import Flask, render_template, request, send_file, redirect, url_for, session, jsonify
import os
import tempfile
import re
import unicodedata
from werkzeug.utils import secure_filename
from time import time

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

# Blacklist 可选，如果想开启过滤，把 ENABLE_BLACKLIST 改为 True
ENABLE_BLACKLIST = False
blacklist = [
    "haihua", "chuhai", "benchi", "818", "databox", "dolphin", 
    "diggoldsl", "juejin"
]

def is_valid_username(name: str) -> bool:
    """判断用户名是否有效"""
    if not name:
        return False  # 去掉空行
    
    # 检查结尾是否包含 "bot"
    if name.lower().endswith("bot"):
        return False
    
    if ENABLE_BLACKLIST:
        if 'bot' in name:
            return False
        for word in blacklist:
            if word in name:
                return False
    return True

# ========= 去重函数 =========
def merge_dedup(files):
    """多文件合并去重"""
    all_data = set()
    for f in files:
        f.seek(0)
        for line in f.read().decode("utf-8-sig").splitlines():
            cleaned = clean_line(line)
            if is_valid_username(cleaned):
                all_data.add(cleaned)
    return sorted(all_data)

def compare_dedup(file_a, file_b):
    """AB 文件对比去重"""
    file_a.seek(0)
    file_b.seek(0)
    data_a = {clean_line(line) for line in file_a.read().decode("utf-8-sig").splitlines() if is_valid_username(clean_line(line))}
    data_b = {clean_line(line) for line in file_b.read().decode("utf-8-sig").splitlines() if is_valid_username(clean_line(line))}

    unique_a = sorted(data_a - data_b)
    unique_b = sorted(data_b - data_a)
    return unique_a, unique_b

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

@app.route("/merge", methods=["POST"])
def merge():
    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        return jsonify({"status":"error","message":"请至少上传一个文件"})
    result = merge_dedup(uploaded_files)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    tmp_file.write("\n".join(result))
    tmp_file.close()
    session["merge_file"] = tmp_file.name
    return jsonify({"status":"success","count":len(result)})

@app.route("/compare", methods=["POST"])
def compare():
    file_a = request.files.get("file_a")
    file_b = request.files.get("file_b")
    if not file_a or not file_b:
        return jsonify({"status":"error","message":"请上传 A 和 B 两个文件"})
    unique_a, unique_b = compare_dedup(file_a, file_b)
    tmp_a = tempfile.NamedTemporaryFile(delete=False, suffix="_A.txt", mode="w", encoding="utf-8")
    tmp_a.write("\n".join(unique_a))
    tmp_a.close()
    tmp_b = tempfile.NamedTemporaryFile(delete=False, suffix="_B.txt", mode="w", encoding="utf-8")
    tmp_b.write("\n".join(unique_b))
    tmp_b.close()
    session["compare_a"] = tmp_a.name
    session["compare_b"] = tmp_b.name
    return jsonify({"status":"success","count_a":len(unique_a),"count_b":len(unique_b)})

@app.route("/username_dedup", methods=["POST"])
def username_dedup():
    uploaded_file = request.files.get("username_file")
    if not uploaded_file:
        return jsonify({"status":"error","message":"请上传文件"})
    
    uploaded_file.seek(0)
    result = sorted({clean_line(line) for line in uploaded_file.read().decode("utf-8-sig").splitlines() if is_valid_username(clean_line(line))})
    
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix="_username.txt", mode="w", encoding="utf-8")
    tmp_file.write("\n".join(result))
    tmp_file.close()
    session["username_file"] = tmp_file.name
    return jsonify({"status":"success","count":len(result)})

# ========= 下载 =========
@app.route("/download")
def download():
    file_path = session.get("merge_file")
    if not file_path or not os.path.exists(file_path):
        return "❌ 没有可下载的文件"
    count = len(open(file_path, "r", encoding="utf-8").readlines())
    return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")

@app.route("/download_a")
def download_a():
    file_path = session.get("compare_a")
    if not file_path or not os.path.exists(file_path):
        return "❌ 没有可下载的 A 文件"
    count = len(open(file_path, "r", encoding="utf-8").readlines())
    return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")

@app.route("/download_b")
def download_b():
    file_path = session.get("compare_b")
    if not file_path or not os.path.exists(file_path):
        return "❌ 没有可下载的 B 文件"
    count = len(open(file_path, "r", encoding="utf-8").readlines())
    return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")

@app.route("/download_username")
def download_username():
    file_path = session.get("username_file")
    if not file_path or not os.path.exists(file_path):
        return "❌ 没有可下载的文件"
    count = len(open(file_path, "r", encoding="utf-8").readlines())
    return send_file(file_path, as_attachment=True, download_name=f"MG_{count}.txt")

if __name__ == "__main__":
    app.run(port=5001)


