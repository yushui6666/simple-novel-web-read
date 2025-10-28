from flask import Flask, render_template, request, jsonify
import re
import os
import sys
import webbrowser
from threading import Timer

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

# 小说文件夹路径（从exe同目录读取）
if getattr(sys, 'frozen', False):
    # 打包后：从exe同目录读取
    NOVEL_FOLDER = os.path.join(os.path.dirname(sys.executable), "novel")
else:
    # 开发环境
    NOVEL_FOLDER = "novel"

def get_novels():
    """获取所有小说文件列表"""
    if not os.path.exists(NOVEL_FOLDER):
        os.makedirs(NOVEL_FOLDER)
        return []
    
    novels = []
    for filename in os.listdir(NOVEL_FOLDER):
        if filename.endswith('.txt'):
            novels.append({
                'filename': filename,
                'name': filename.replace('.txt', '')
            })
    return novels

def parse_novel(filename):
    """解析小说章节"""
    filepath = os.path.join(NOVEL_FOLDER, filename)
    
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    
    # 自动识别章节标题（如 "第1章"、"第十二章"、"第十节" 等）
    chapter_pattern = r"(第[\d一二三四五六七八九十百千]+[章节].*?)\n"
    splits = re.split(chapter_pattern, text)
    
    chapters = []
    for i in range(1, len(splits), 2):
        title = splits[i].strip()
        content = splits[i + 1].strip()
        if content:
            chapters.append({"title": title, "content": content})
    
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

@app.route("/api/chapters")
def api_chapters():
    """返回指定小说的章节列表"""
    novel = request.args.get("novel", "")
    if not novel or not novel.endswith('.txt'):
        return jsonify({"error": "invalid novel"}), 400
    
    filepath = os.path.join(NOVEL_FOLDER, novel)
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
    idx = int(request.args.get("id", 0))
    page = int(request.args.get("page", 1))
    
    if not novel or not novel.endswith('.txt'):
        return jsonify({"error": "invalid novel"}), 400
    
    filepath = os.path.join(NOVEL_FOLDER, novel)
    if not os.path.exists(filepath):
        return jsonify({"error": "novel not found"}), 404
    
    chapters = parse_novel(novel)
    
    if idx < 0 or idx >= len(chapters):
        return jsonify({"error": "invalid chapter"}), 404

    content = chapters[idx]["content"]
    total_pages = (len(content) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE
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

def open_browser():
    """自动打开浏览器"""
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == "__main__":
    # 1秒后自动打开浏览器
    Timer(1, open_browser).start()
    
    print("=" * 50)
    print("📖 小说阅读器已启动")
    print("🌐 访问地址: http://127.0.0.1:5000")
    print("📁 小说文件夹:", NOVEL_FOLDER)
    print("❌ 按 Ctrl+C 退出")
    print("=" * 50)
    
    app.run(debug=False, port=5000)