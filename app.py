from flask import Flask, render_template, request, jsonify
import re
import os
import sys
import json
from datetime import datetime

# 获取资源路径（支持打包后的环境）
def resource_path(relative_path):
    """获取资源的绝对路径，支持打包后的临时目录"""
    try:
        # PyInstaller 创建的临时文件夹路径
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(__name__, 
            template_folder=resource_path('templates'))

WORDS_PER_PAGE = 1000  # 每次加载字数
_PARSE_CACHE = {}

# 小说文件夹路径（从exe同目录读取）
if getattr(sys, 'frozen', False):
    # 打包后：从exe同目录读取
    APP_DATA_FOLDER = os.path.dirname(sys.executable)
    NOVEL_FOLDER = os.path.join(APP_DATA_FOLDER, "novel")
else:
    # 开发环境
    APP_DATA_FOLDER = "."
    NOVEL_FOLDER = "novel"

HISTORY_FILE = os.path.join(APP_DATA_FOLDER, "reading_history.json")

def _safe_txt_path(folder, filename):
    """Return a safe txt file path inside folder, or None for invalid input."""
    if not filename or not isinstance(filename, str):
        return None
    if "\x00" in filename or os.path.basename(filename) != filename:
        return None
    if not filename.endswith(".txt"):
        return None

    base_dir = os.path.abspath(folder)
    filepath = os.path.abspath(os.path.join(base_dir, filename))
    if os.path.commonpath([base_dir, filepath]) != base_dir:
        return None
    return filepath

def _get_novel_path(filename):
    return _safe_txt_path(NOVEL_FOLDER, filename)

def _clean_upload_filename(filename):
    """Keep readable names while preventing path traversal and non-txt uploads."""
    if not filename or not isinstance(filename, str):
        return None
    filename = os.path.basename(filename).replace("\x00", "").strip()
    if not filename.endswith(".txt"):
        return None
    return filename if _get_novel_path(filename) else None

def _get_note_path(novel):
    if not _get_novel_path(novel):
        return None
    note_filename = f"{novel[:-4]}_笔记.txt"
    return _safe_txt_path(NOTES_FOLDER, note_filename)

def _parse_int_arg(name, default):
    raw_value = request.args.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None

def _load_all_users():
    """加载所有用户的阅读历史。兼容旧版单用户格式自动迁移。"""
    if not os.path.exists(HISTORY_FILE):
        return {"users": {}}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"users": {}}

    if not isinstance(data, dict):
        return {"users": {}}

    # 旧版格式迁移：{"books": {...}} → {"users": {"default": {"books": {...}}}}
    if "books" in data and "users" not in data:
        old_books = data["books"] if isinstance(data["books"], dict) else {}
        data = {"users": {"default": {"books": old_books}}}
        _save_all_users(data)
    elif "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}

    return data


def _load_user_history(username):
    """加载指定用户的阅读历史"""
    if not username or not isinstance(username, str):
        username = "default"
    data = _load_all_users()
    user_data = data["users"].get(username, {"books": {}})
    if not isinstance(user_data, dict) or not isinstance(user_data.get("books"), dict):
        return {"books": {}}
    return user_data


def _save_user_history(username, user_history):
    """保存指定用户的阅读历史"""
    if not username or not isinstance(username, str):
        username = "default"
    data = _load_all_users()
    if not isinstance(user_history, dict) or not isinstance(user_history.get("books"), dict):
        user_history = {"books": {}}
    data["users"][username] = user_history
    _save_all_users(data)


def _save_all_users(data):
    """保存所有用户数据到文件"""
    history_dir = os.path.dirname(os.path.abspath(HISTORY_FILE))
    if history_dir:
        os.makedirs(history_dir, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _remove_history_for_novel(novel):
    """从所有用户中移除指定小说的阅读历史"""
    data = _load_all_users()
    for username in data["users"]:
        if novel in data["users"][username].get("books", {}):
            data["users"][username]["books"].pop(novel, None)
    _save_all_users(data)

def _calc_progress_percent(chapter, total_chapters):
    if total_chapters <= 0:
        return 0.0
    return round(min(max((chapter + 1) / total_chapters * 100, 0), 100), 1)

def _build_bookshelf_item(novel, username="default"):
    filename = novel["filename"]
    history = _load_user_history(username)["books"].get(filename, {})
    chapter = history.get("chapter")
    total_chapters = history.get("total_chapters")
    progress_percent = history.get("progress_percent", 0.0)

    return {
        "filename": filename,
        "name": novel["name"],
        "last_chapter": chapter if isinstance(chapter, int) else None,
        "last_chapter_title": history.get("chapter_title", ""),
        "last_page": history.get("page", 1),
        "total_pages": history.get("total_pages", 1),
        "total_chapters": total_chapters if isinstance(total_chapters, int) else None,
        "progress_percent": progress_percent if isinstance(progress_percent, (int, float)) else 0.0,
        "last_read_at": history.get("last_read_at", ""),
    }

def get_novels():
    """获取所有小说文件列表"""
    if not os.path.exists(NOVEL_FOLDER):
        os.makedirs(NOVEL_FOLDER)
        return []
    
    novels = []
    for filename in sorted(os.listdir(NOVEL_FOLDER)):
        filepath = _get_novel_path(filename)
        if filepath and os.path.isfile(filepath):
            novels.append({
                'filename': filename,
                'name': filename.replace('.txt', '')
            })
    return novels

def parse_novel(filename):
    """万能小说章节解析：适配常见TXT章节格式；匹配不到则按字数分页降级"""
    filepath = _get_novel_path(filename)
    if not filepath or not os.path.exists(filepath):
        raise FileNotFoundError(filename)

    stat = os.stat(filepath)
    cache_key = (stat.st_mtime_ns, stat.st_size)
    cached = _PARSE_CACHE.get(filepath)
    if cached and cached["key"] == cache_key:
        return cached["chapters"]

    # 1) 读取文本：兼容 UTF-8 BOM / 宽松错误处理
    with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
        raw = f.read()

    # 2) 统一换行，去掉一些怪字符
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\t", " ")

    # 3) 定义“章节标题行”匹配：覆盖 常见写法（章/节/回/卷/部/篇）
    #    - 支持：第1章 / 第一章 / 第十回 / 卷一 / 第一卷 / 序章 / 楔子 / 后记 等
    #    - 支持：中文冒号： / 英文冒号: / 破折号- / 空格标题
    #    - 允许标题在同一行或下一行（见后面的“合并下一行标题”逻辑）
    chapter_line_re = re.compile(
        r"""
        ^\s*(
            # A) 第X章/节/回/卷/部/篇（X为阿拉伯或中文数字）
            第\s*[\d一二三四五六七八九十百千万两零〇]+?\s*[章节回卷部篇]\s*.*?
            |
            # B) 卷X / 第X卷
            (?:第?\s*[\d一二三四五六七八九十百千万两零〇]+?\s*卷)\s*.*?
            |
            # C) 特殊章节名（常见：序章/楔子/引子/前言/后记/番外/终章/尾声）
            (?:序章|楔子|引子|前言|后记|番外|终章|尾声)\s*.*?
        )\s*
        (?:[:：\-—]{0,2}\s*)?
        $
        """,
        re.VERBOSE | re.MULTILINE
    )

    # 4) 找到所有“章节标题行”的位置
    matches = list(chapter_line_re.finditer(text))

    # 5) 如果一个都匹配不到：降级为“单章 + 全文”
    if not matches:
        # 也可以改成“按固定字数分成多章”，但保持你前端结构最简单：
        chapters = [{"title": "全文", "content": text.strip()}] if text.strip() else []
        _PARSE_CACHE[filepath] = {"key": cache_key, "chapters": chapters}
        return chapters

    chapters = []

    # 6) 章节切片：每个标题到下一个标题之间为正文
    for i, m in enumerate(matches):
        start_title = m.start()
        end_title = m.end()
        start_content = end_title

        end_content = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        title_line = text[start_title:end_title].strip()
        content_block = text[start_content:end_content].strip("\n").strip()

        # 7) 兼容：标题下一行才是真正章节名（例如：第一章：\n你想看的里面都有）
        #    规则：若标题行本身很短 & 下一行不是空行 & 下一行不像正文（不以缩进开头/不太长）则合并
        if content_block:
            first_line = content_block.split("\n", 1)[0].strip()
            # 判断“下一行像标题”：
            # - 不太长（可调，比如 <= 40）
            # - 不包含明显句号结尾（像正文）
            # - 不以大量缩进开头
            if (
                len(title_line) <= 20 and
                first_line and
                len(first_line) <= 40 and
                not re.search(r"[。！？.!?]$", first_line) and
                not re.match(r"^\s{6,}", content_block)
            ):
                # 合并下一行作为章节名，然后从正文里删掉这一行
                title_line = f"{title_line} {first_line}".strip()
                content_block = content_block[len(content_block.split("\n", 1)[0]):].lstrip("\n").strip()

        # 8) 过滤掉空正文（有些文件只有目录/空章）
        if content_block:
            chapters.append({"title": title_line, "content": content_block})

    # 9) 兜底：如果过滤后空了，至少返回全文
    if not chapters and text.strip():
        chapters = [{"title": "全文", "content": text.strip()}]

    _PARSE_CACHE[filepath] = {"key": cache_key, "chapters": chapters}
    return chapters


@app.route("/")
def index():
    """主页面"""
    novels = get_novels()
    return render_template("read.html", novels=novels) 

@app.route("/api/novels")
def api_novels():
    """返回小说列表"""
    novels = get_novels()
    return jsonify({"novels": novels})

@app.route("/api/upload_novel", methods=["POST"])
def upload_novel():
    """上传TXT小说到novel目录"""
    upload = request.files.get("novel")
    if not upload:
        return jsonify({"error": "missing file"}), 400

    filename = _clean_upload_filename(upload.filename)
    if not filename:
        return jsonify({"error": "only .txt files are supported"}), 400

    filepath = _get_novel_path(filename)
    if not filepath:
        return jsonify({"error": "invalid filename"}), 400
    if os.path.exists(filepath):
        return jsonify({"error": "novel already exists"}), 409

    os.makedirs(NOVEL_FOLDER, exist_ok=True)
    upload.save(filepath)
    _PARSE_CACHE.pop(os.path.abspath(filepath), None)

    return jsonify({
        "success": True,
        "novel": {
            "filename": filename,
            "name": filename.replace(".txt", "")
        }
    })

@app.route("/api/delete_novel", methods=["POST"])
def delete_novel():
    """删除novel目录中的指定小说"""
    data = request.get_json(silent=True) or {}
    novel = data.get("novel", "")
    filepath = _get_novel_path(novel)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404

    os.remove(filepath)
    _PARSE_CACHE.pop(os.path.abspath(filepath), None)
    _remove_history_for_novel(novel)

    return jsonify({"success": True, "deleted": novel})

@app.route("/api/bookshelf")
def api_bookshelf():
    """返回书架阅读统计，按最近阅读时间排序"""
    username = request.args.get("user", "default").strip() or "default"
    books = [_build_bookshelf_item(novel, username) for novel in get_novels()]
    books.sort(key=lambda item: (bool(item.get("last_read_at")), item.get("last_read_at") or ""), reverse=True)
    return jsonify({"books": books, "user": username})

@app.route("/api/reading_history", methods=["POST"])
def save_reading_history():
    """保存当前小说的阅读历史"""
    data = request.get_json(silent=True) or {}
    novel = data.get("novel", "")
    filepath = _get_novel_path(novel)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404

    try:
        chapter = int(data.get("chapter", 0))
        page = int(data.get("page", 1))
        total_pages = int(data.get("total_pages", 1))
        total_chapters = int(data.get("total_chapters", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid history"}), 400

    if chapter < 0 or page < 1 or total_pages < 1 or total_chapters < 1 or chapter >= total_chapters:
        return jsonify({"error": "invalid history"}), 400

    chapter_title = str(data.get("chapter_title", "")).strip()
    username = data.get("user", "default").strip() or "default"
    user_history = _load_user_history(username)
    user_history["books"][novel] = {
        "novel": novel,
        "name": novel.replace(".txt", ""),
        "chapter": chapter,
        "chapter_title": chapter_title,
        "page": page,
        "total_pages": total_pages,
        "total_chapters": total_chapters,
        "progress_percent": _calc_progress_percent(chapter, total_chapters),
        "last_read_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_user_history(username, user_history)

    return jsonify({"success": True, "history": user_history["books"][novel]})

@app.route("/api/user/list")
def api_user_list():
    """返回所有用户列表"""
    data = _load_all_users()
    users = sorted(data["users"].keys())
    return jsonify({"users": users})

@app.route("/api/user/history")
def api_user_history():
    """返回指定用户对指定小说的阅读历史"""
    username = request.args.get("user", "default").strip() or "default"
    novel = request.args.get("novel", "")
    user_history = _load_user_history(username)
    book = user_history["books"].get(novel)
    return jsonify({"book": book} if book else {"book": None})

@app.route("/api/chapters")
def api_chapters():
    """返回指定小说的章节列表"""
    novel = request.args.get("novel", "")
    filepath = _get_novel_path(novel)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404
    
    chapters = parse_novel(novel)
    return jsonify({
        "novel": novel,
        "chapters": [c["title"] for c in chapters],
        "total_chapters": len(chapters)  # 新增：返回总章节数
    })
@app.route("/debug/files")
def debug_files():
    """调试：显示所有文件详情"""
    import os
    
    result = {
        "folder": NOVEL_FOLDER,
        "exists": os.path.exists(NOVEL_FOLDER),
        "all_files": []
    }
    
    if os.path.exists(NOVEL_FOLDER):
        for filename in os.listdir(NOVEL_FOLDER):
            filepath = os.path.join(NOVEL_FOLDER, filename)
            result["all_files"].append({
                "name": filename,
                "is_file": os.path.isfile(filepath),
                "size": os.path.getsize(filepath) if os.path.isfile(filepath) else 0,
                "ends_with_txt": filename.endswith('.txt'),
                "lower_ends_with_txt": filename.lower().endswith('.txt')
            })
    
    return jsonify(result)

@app.route("/api/chapter")
def api_chapter():
    """返回章节内容（分页）"""
    novel = request.args.get("novel", "")
    idx = _parse_int_arg("id", 0)
    page = _parse_int_arg("page", 1)
    
    filepath = _get_novel_path(novel)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400
    if idx is None or page is None or idx < 0 or page < 1:
        return jsonify({"error": "invalid chapter or page"}), 400
    
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404
    
    chapters = parse_novel(novel)
    
    if idx >= len(chapters):
        return jsonify({"error": "invalid chapter"}), 404

    content = chapters[idx]["content"]
    total_pages = (len(content) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE
    if page > total_pages:
        return jsonify({"error": "invalid page"}), 404

    start = (page - 1) * WORDS_PER_PAGE
    end = start + WORDS_PER_PAGE
    
    # 判断是否有下一章
    has_next_chapter = idx + 1 < len(chapters)
    
    return jsonify({
        "chapter": idx,
        "title": chapters[idx]["title"],
        "page": page,
        "total_pages": total_pages,
        "content": content[start:end],
        "has_next_chapter": has_next_chapter,
        "next_chapter_title": chapters[idx + 1]["title"] if has_next_chapter else None,
        "total_chapters": len(chapters)  # 新增：返回总章节数
    })
if getattr(sys, 'frozen', False):
    NOTES_FOLDER = os.path.join(os.path.dirname(sys.executable), "notes")
else:
    NOTES_FOLDER = "notes"

@app.route("/api/save_note", methods=["POST"])
def save_note():
    """保存笔记"""
    data = request.get_json(silent=True) or {}
    novel = data.get("novel", "")
    chapter_title = data.get("chapter_title", "")
    content = data.get("content", "")
    
    note_filepath = _get_note_path(novel)
    if not note_filepath or not content:
        return jsonify({"error": "invalid data"}), 400
    
    # 确保笔记文件夹存在
    if not os.path.exists(NOTES_FOLDER):
        os.makedirs(NOTES_FOLDER)
    
    # 笔记文件名：小说名_笔记.txt
    note_filename = os.path.basename(note_filepath)
    
    # 添加时间戳
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 格式化笔记内容
    note_entry = f"\n{'='*50}\n"
    note_entry += f"📅 时间: {timestamp}\n"
    note_entry += f"📖 章节: {chapter_title}\n"
    note_entry += f"{'='*50}\n"
    note_entry += f"{content}\n"
    
    # 追加到文件
    with open(note_filepath, "a", encoding="utf-8") as f:
        f.write(note_entry)
    
    return jsonify({
        "success": True,
        "message": "笔记保存成功",
        "note_file": note_filename
    })

@app.route("/api/get_notes")
def get_notes():
    """获取笔记内容"""
    novel = request.args.get("novel", "")
    note_filepath = _get_note_path(novel)
    if not note_filepath:
        return jsonify({"error": "invalid novel"}), 400
    
    if not os.path.exists(note_filepath):
        return jsonify({"notes": "", "exists": False})
    
    with open(note_filepath, "r", encoding="utf-8") as f:
        notes_content = f.read()
    
    return jsonify({"notes": notes_content, "exists": True})

if __name__ == "__main__":
    # 1秒后自动打开浏览器
    
    print("=" * 50)
    print("📖 novel action")
    print("🌐 address: http://127.0.0.1:6066")
    print("📁 dir:", NOVEL_FOLDER)
    print("❌  Ctrl+C exit")
    print("=" * 50)
    
    app.run(host="0.0.0.0",debug=False, port=6066)
