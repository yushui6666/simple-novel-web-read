from flask import Flask, render_template, request, jsonify
import hashlib
import re
import os
import sys
import json
from datetime import datetime
from urllib.parse import urlparse

from search import Txt80Downloader

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

WORDS_PER_PAGE = 3000  # 每次加载字数（增大以减少请求数）
_PARSE_CACHE = {}  # filepath -> {"key": (mtime_ns, size), "text": str, "chapters": [{"title": ..., "start": int, "end": int}]}

# 模块级预编译：章节标题行匹配正则（避免每次解析时重新编译）
_CHAPTER_LINE_RE = re.compile(
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
if getattr(sys, 'frozen', False):
    # 打包后：从exe同目录读取
    APP_DATA_FOLDER = os.path.dirname(sys.executable)
    NOVEL_FOLDER = os.path.join(APP_DATA_FOLDER, "novel")
else:
    # 开发环境
    APP_DATA_FOLDER = "."
    NOVEL_FOLDER = "novel"

HISTORY_FILE = os.path.join(APP_DATA_FOLDER, "reading_history.json")
_CACHE_DIR = os.path.join(APP_DATA_FOLDER, ".novel_cache")  # 磁盘缓存目录（只存章节元数据）

def _normalize_username(username):
    """Return a stable folder-safe username."""
    if not username or not isinstance(username, str):
        return "default"
    username = username.strip() or "default"
    username = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", username, flags=re.UNICODE).strip("._")
    return (username or "default")[:80]

def _get_user_folder(root_folder, username):
    safe_user = _normalize_username(username)
    base_dir = os.path.abspath(root_folder)
    folder = os.path.abspath(os.path.join(base_dir, safe_user))
    if os.path.commonpath([base_dir, folder]) != base_dir:
        return None
    return folder

def _migrate_default_novels_once(folder):
    """Move legacy root-level novels into the default user's bookshelf."""
    if _normalize_username("default") != os.path.basename(os.path.abspath(folder)):
        return
    root_dir = os.path.abspath(NOVEL_FOLDER)
    user_dir = os.path.abspath(folder)
    if root_dir == user_dir or not os.path.isdir(root_dir):
        return

    legacy_files = [
        filename for filename in os.listdir(root_dir)
        if filename.endswith(".txt") and os.path.isfile(os.path.join(root_dir, filename))
    ]
    if not legacy_files:
        return

    os.makedirs(user_dir, exist_ok=True)
    for filename in legacy_files:
        source = os.path.join(root_dir, filename)
        target = os.path.join(user_dir, filename)
        if not os.path.exists(target):
            os.replace(source, target)

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

def _get_novel_folder(username="default"):
    folder = _get_user_folder(NOVEL_FOLDER, username)
    if folder and _normalize_username(username) == "default":
        _migrate_default_novels_once(folder)
    return folder

def _get_novel_path(filename, username="default"):
    folder = _get_novel_folder(username)
    if not folder:
        return None
    return _safe_txt_path(folder, filename)

def _clean_upload_filename(filename, username="default"):
    """Keep readable names while preventing path traversal and non-txt uploads."""
    if not filename or not isinstance(filename, str):
        return None
    filename = os.path.basename(filename).replace("\x00", "").strip()
    if not filename.endswith(".txt"):
        return None
    return filename if _get_novel_path(filename, username) else None

def _get_note_path(novel, username="default"):
    if not _get_novel_path(novel, username):
        return None
    notes_folder = _get_user_folder(NOTES_FOLDER, username)
    if not notes_folder:
        return None
    note_filename = f"{novel[:-4]}_笔记.txt"
    return _safe_txt_path(notes_folder, note_filename)

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
    username = _normalize_username(username)
    data = _load_all_users()
    user_data = data["users"].get(username, {"books": {}})
    if not isinstance(user_data, dict) or not isinstance(user_data.get("books"), dict):
        return {"books": {}}
    return user_data


def _save_user_history(username, user_history):
    """保存指定用户的阅读历史"""
    username = _normalize_username(username)
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

def _remove_history_for_novel(novel, username):
    """从指定用户中移除指定小说的阅读历史"""
    data = _load_all_users()
    username = _normalize_username(username)
    if username in data["users"]:
        data["users"][username].get("books", {}).pop(novel, None)
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

def get_novels(username="default"):
    """获取所有小说文件列表"""
    folder = _get_novel_folder(username)
    if not folder:
        return []
    if not os.path.exists(folder):
        os.makedirs(folder)
        return []
    
    novels = []
    for filename in sorted(os.listdir(folder)):
        filepath = _get_novel_path(filename, username)
        if filepath and os.path.isfile(filepath):
            novels.append({
                'filename': filename,
                'name': filename.replace('.txt', '')
            })
    return novels

def parse_novel(filename, username="default"):
    """万能小说章节解析：适配常见TXT章节格式；匹配不到则按字数分页降级
    
    优化：缓存中只存 text + 章节偏移量（start/end），不复制每章内容，省一半内存。
    """
    cached = _get_parse_cache(filename, username)
    return _build_chapters_from_cache(cached)


def _get_parse_cache(filename, username="default"):
    """Return normalized full text plus chapter offsets for one novel."""
    filepath = _get_novel_path(filename, username)
    if not filepath or not os.path.exists(filepath):
        raise FileNotFoundError(filename)
    filepath = os.path.abspath(filepath)

    stat = os.stat(filepath)
    cache_key = (stat.st_mtime_ns, stat.st_size)
    
    # 1) 内存缓存命中
    cached = _PARSE_CACHE.get(filepath)
    if cached and cached["key"] == cache_key:
        return cached

    # 2) 磁盘缓存命中：读文本 + 复用章节元数据（跳过昂贵正则扫描）
    disk_cached = _load_disk_cache(filepath)
    if disk_cached and tuple(disk_cached["key"]) == cache_key:
        text = _read_normalized_text(filepath)
        _PARSE_CACHE[filepath] = {"key": cache_key, "text": text, "chapters": disk_cached["chapters"]}
        return _PARSE_CACHE[filepath]

    # 3) 全量解析：读取文本 + 正则扫描
    text = _read_normalized_text(filepath)

    # 3) 使用模块级预编译正则找到所有“章节标题行”的位置
    matches = list(_CHAPTER_LINE_RE.finditer(text))

    # 4) 如果一个都匹配不到：降级为“单章 + 全文”
    if not matches:
        chapters_meta = [{"title": "全文", "start": 0, "end": len(text)}] if text.strip() else []
        _PARSE_CACHE[filepath] = {"key": cache_key, "text": text, "chapters": chapters_meta}
        _save_disk_cache(filepath, _PARSE_CACHE[filepath])
        return _PARSE_CACHE[filepath]

    chapters_meta = []

    # 5) 章节切片：每个标题到下一个标题之间为正文
    for i, m in enumerate(matches):
        end_title = m.end()
        start_content = end_title
        end_content = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        title_line = text[m.start():end_title].strip()

        # 6) 兼容：标题下一行才是真正章节名（例如：第一章：\n你想看的里面都有）
        content_block = text[start_content:end_content]
        content_stripped = content_block.strip("\n").strip()
        if content_stripped:
            first_line = content_block.split("\n", 1)[0].strip()
            if (
                len(title_line) <= 20 and
                first_line and
                len(first_line) <= 40 and
                not re.search(r"[。！？.!?]$", first_line) and
                not re.match(r"^\s{6,}", content_block)
            ):
                # 合并下一行作为章节名，内容偏移量跳过这一行
                title_line = f"{title_line} {first_line}".strip()
                skip_len = len(content_block.split("\n", 1)[0]) + 1  # +1 for \n
                start_content += skip_len

        # 7) 计算正文的实际起始和结束（去除首尾空行）
        actual_start = start_content
        while actual_start < end_content and text[actual_start] in "\n\r ":
            actual_start += 1
        actual_end = end_content
        while actual_end > actual_start and text[actual_end - 1] in "\n\r ":
            actual_end -= 1

        if actual_start < actual_end:
            chapters_meta.append({"title": title_line, "start": actual_start, "end": actual_end})

    # 8) 兜底：如果过滤后空了，至少返回全文
    if not chapters_meta and text.strip():
        chapters_meta = [{"title": "全文", "start": 0, "end": len(text)}]

    _PARSE_CACHE[filepath] = {"key": cache_key, "text": text, "chapters": chapters_meta}
    _save_disk_cache(filepath, _PARSE_CACHE[filepath])  # 持久化章节元数据
    return _PARSE_CACHE[filepath]


def _build_chapters_from_cache(cached):
    """从缓存的 text + 偏移量动态构建 chapters 列表（兼容旧接口）"""
    text = cached["text"]
    return [
        {"title": m["title"], "content": text[m["start"]:m["end"]]}
        for m in cached["chapters"]
    ]


def _read_normalized_text(filepath):
    with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
        raw = f.read()
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\u3000", " ").replace("\t", " ")


def _get_chapter_titles(filename, username="default"):
    cached = _get_parse_cache(filename, username)
    return [chapter["title"] for chapter in cached["chapters"]]


def _get_chapter_page(filename, username, idx, page):
    cached = _get_parse_cache(filename, username)
    chapters = cached["chapters"]
    if idx >= len(chapters):
        return None

    chapter = chapters[idx]
    content_len = chapter["end"] - chapter["start"]
    total_pages = max((content_len + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE, 1)
    if page > total_pages:
        return None

    page_start = chapter["start"] + (page - 1) * WORDS_PER_PAGE
    page_end = min(chapter["start"] + page * WORDS_PER_PAGE, chapter["end"])
    has_next_chapter = idx + 1 < len(chapters)

    return {
        "chapter": idx,
        "title": chapter["title"],
        "page": page,
        "total_pages": total_pages,
        "content": cached["text"][page_start:page_end],
        "has_next_chapter": has_next_chapter,
        "next_chapter_title": chapters[idx + 1]["title"] if has_next_chapter else None,
        "total_chapters": len(chapters),
    }


# ══════════════ 磁盘缓存持久化 ══════════════

def _get_cache_path(filepath):
    """返回小说文件的磁盘缓存路径（SHA256 前16位 + .json）"""
    h = hashlib.sha256(filepath.encode()).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{h}.json")

def _load_disk_cache(filepath):
    """从磁盘加载章节元数据。失败或过期返回 None。"""
    cache_path = _get_cache_path(filepath)
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "key" not in data or "chapters" not in data:
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None

def _save_disk_cache(filepath, cache_data):
    """保存章节元数据到磁盘（不含 text 全文，text 从原始文件重读）。"""
    cache_path = _get_cache_path(filepath)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    save_data = {
        "key": cache_data["key"],
        "chapters": cache_data["chapters"]
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False)

def _remove_disk_cache(filepath):
    """删除磁盘缓存文件"""
    cache_path = _get_cache_path(filepath)
    try:
        os.remove(cache_path)
    except OSError:
        pass

def warmup_cache(username="default"):
    """启动时预热：后台解析所有小说填充内存缓存。"""
    novels = get_novels(username)
    if not novels:
        return
    print(f"🔥 预热缓存：正在解析 {len(novels)} 本小说...")
    for novel in novels:
        try:
            parse_novel(novel["filename"], username)
            print(f"  ✅ {novel['name']}")
        except Exception as e:
            print(f"  ⚠️ 跳过 {novel['name']}: {e}")
    print("🔥 预热完成！")


@app.route("/")
def index():
    """主页面"""
    novels = get_novels("default")
    return render_template("read.html", novels=novels) 

@app.route("/download")
def download_page():
    """在线搜索下载页面"""
    username = _normalize_username(request.args.get("user", "default"))
    return render_template("download.html", user=username)

def _is_allowed_txt80_url(url):
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and host in {"txt80.cc", "www.txt80.cc"}

def _dedupe_search_results(results):
    seen = set()
    unique = []
    for title, url in results:
        if url in seen:
            continue
        seen.add(url)
        unique.append({"title": title, "url": url})
    return unique

@app.route("/api/download/search")
def api_download_search():
    """搜索可下载的小说"""
    keyword = (request.args.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    try:
        results = Txt80Downloader().search(keyword)
    except Exception as exc:
        return jsonify({"error": f"search failed: {exc}"}), 502

    return jsonify({"results": _dedupe_search_results(results)})

@app.route("/api/download/novel", methods=["POST"])
def api_download_novel():
    """下载小说到指定用户的书架"""
    data = request.get_json(silent=True) or {}
    detail_url = (data.get("url") or "").strip()
    username = _normalize_username(data.get("user", "default"))
    if not _is_allowed_txt80_url(detail_url):
        return jsonify({"error": "only txt80.cc detail URLs are supported"}), 400

    folder = _get_novel_folder(username)
    if not folder:
        return jsonify({"error": "invalid user"}), 400
    os.makedirs(folder, exist_ok=True)

    try:
        result = Txt80Downloader().download(detail_url, save_dir=folder)
    except Exception as exc:
        return jsonify({"error": f"download failed: {exc}"}), 502

    if not result:
        return jsonify({"error": "download failed"}), 502

    filename = result.get("filename") if isinstance(result, dict) else None
    filepath = _get_novel_path(filename, username) if filename else None
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "downloaded file is invalid"}), 500

    abs_path = os.path.abspath(filepath)
    _PARSE_CACHE.pop(abs_path, None)
    _remove_disk_cache(abs_path)

    return jsonify({
        "success": True,
        "novel": {
            "filename": filename,
            "name": filename.replace(".txt", "")
        },
        "size": os.path.getsize(filepath),
        "user": username,
    })

@app.route("/api/novels")
def api_novels():
    """返回小说列表"""
    username = request.args.get("user", "default")
    novels = get_novels(username)
    return jsonify({"novels": novels, "user": _normalize_username(username)})

@app.route("/api/upload_novel", methods=["POST"])
def upload_novel():
    """上传TXT小说到novel目录"""
    username = request.form.get("user", "default")
    upload = request.files.get("novel")
    if not upload:
        return jsonify({"error": "missing file"}), 400

    filename = _clean_upload_filename(upload.filename, username)
    if not filename:
        return jsonify({"error": "only .txt files are supported"}), 400

    filepath = _get_novel_path(filename, username)
    if not filepath:
        return jsonify({"error": "invalid filename"}), 400
    if os.path.exists(filepath):
        return jsonify({"error": "novel already exists"}), 409

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    upload.save(filepath)
    _PARSE_CACHE.pop(os.path.abspath(filepath), None)
    _remove_disk_cache(os.path.abspath(filepath))

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
    username = data.get("user", "default")
    filepath = _get_novel_path(novel, username)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404

    os.remove(filepath)
    _PARSE_CACHE.pop(os.path.abspath(filepath), None)
    _remove_disk_cache(os.path.abspath(filepath))
    _remove_history_for_novel(novel, username)

    return jsonify({"success": True, "deleted": novel})

@app.route("/api/bookshelf")
def api_bookshelf():
    """返回书架阅读统计，按最近阅读时间排序"""
    username = _normalize_username(request.args.get("user", "default"))
    books = [_build_bookshelf_item(novel, username) for novel in get_novels(username)]
    books.sort(key=lambda item: (bool(item.get("last_read_at")), item.get("last_read_at") or ""), reverse=True)
    return jsonify({"books": books, "user": username})

@app.route("/api/reading_history", methods=["POST"])
def save_reading_history():
    """保存当前小说的阅读历史"""
    data = request.get_json(silent=True) or {}
    novel = data.get("novel", "")
    username = _normalize_username(data.get("user", "default"))
    filepath = _get_novel_path(novel, username)
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
    username = _normalize_username(request.args.get("user", "default"))
    novel = request.args.get("novel", "")
    user_history = _load_user_history(username)
    book = user_history["books"].get(novel)
    return jsonify({"book": book} if book else {"book": None})

@app.route("/api/chapters")
def api_chapters():
    """返回指定小说的章节列表"""
    novel = request.args.get("novel", "")
    username = request.args.get("user", "default")
    filepath = _get_novel_path(novel, username)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404
    
    titles = _get_chapter_titles(novel, username)
    return jsonify({
        "novel": novel,
        "chapters": titles,
        "total_chapters": len(titles)
    })
@app.route("/debug/files")
def debug_files():
    """调试：显示所有文件详情"""
    import os
    username = request.args.get("user", "default")
    folder = _get_novel_folder(username)
    
    result = {
        "folder": folder,
        "user": _normalize_username(username),
        "exists": bool(folder and os.path.exists(folder)),
        "all_files": []
    }
    
    if folder and os.path.exists(folder):
        for filename in os.listdir(folder):
            filepath = os.path.join(folder, filename)
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
    username = request.args.get("user", "default")
    idx = _parse_int_arg("id", 0)
    page = _parse_int_arg("page", 1)
    
    filepath = _get_novel_path(novel, username)
    if not filepath:
        return jsonify({"error": "invalid novel"}), 400
    if idx is None or page is None or idx < 0 or page < 1:
        return jsonify({"error": "invalid chapter or page"}), 400
    
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404
    
    page_data = _get_chapter_page(novel, username, idx, page)
    if page_data is None:
        return jsonify({"error": "invalid page"}), 404
    return jsonify(page_data)
if getattr(sys, 'frozen', False):
    NOTES_FOLDER = os.path.join(os.path.dirname(sys.executable), "notes")
else:
    NOTES_FOLDER = "notes"

@app.route("/api/save_note", methods=["POST"])
def save_note():
    """保存笔记"""
    data = request.get_json(silent=True) or {}
    novel = data.get("novel", "")
    username = data.get("user", "default")
    chapter_title = data.get("chapter_title", "")
    content = data.get("content", "")
    
    note_filepath = _get_note_path(novel, username)
    if not note_filepath or not content:
        return jsonify({"error": "invalid data"}), 400
    
    # 确保笔记文件夹存在
    os.makedirs(os.path.dirname(note_filepath), exist_ok=True)
    
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
    username = request.args.get("user", "default")
    note_filepath = _get_note_path(novel, username)
    if not note_filepath:
        return jsonify({"error": "invalid novel"}), 400
    
    if not os.path.exists(note_filepath):
        return jsonify({"notes": "", "exists": False})
    
    with open(note_filepath, "r", encoding="utf-8") as f:
        notes_content = f.read()
    
    return jsonify({"notes": notes_content, "exists": True})

if __name__ == "__main__":
    print("=" * 50)
    print("📖 novel action")
    print("🌐 address: http://127.0.0.1:6066")
    print("📁 dir:", NOVEL_FOLDER)
    print("💾 cache:", _CACHE_DIR)
    print("❌  Ctrl+C exit")
    print("=" * 50)
    
    # 启动时预热所有小说的章节缓存 + 磁盘缓存
    warmup_cache("default")
    
    # threaded=True 允许并发请求，翻页时不会阻塞其他操作
    app.run(host="0.0.0.0", debug=False, port=6066, threaded=True)
