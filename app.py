from flask import Flask, render_template, request, jsonify
import re
import os

app = Flask(__name__)

WORDS_PER_PAGE = 1000  # 每次加载字数
NOVEL_FOLDER = "novel"  # 小说文件夹

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
        "chapters": [c["title"] for c in chapters]
    })

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
        "next_chapter_title": chapters[idx + 1]["title"] if has_next_chapter else None
    })

if __name__ == "__main__":
    app.run(debug=True)
    #http://127.0.0.1:5000