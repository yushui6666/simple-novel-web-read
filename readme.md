# Simple Novel Web Read

一个轻量的本地 Web 小说阅读器，基于 Flask 构建。项目支持 TXT 小说书架、章节解析、分页阅读、阅读进度保存、笔记记录，以及从 txt80.cc 搜索并下载 TXT 小说。

## 功能

- TXT 书架：读取 `novel/` 目录中的小说文件，并在页面中切换阅读。
- 智能章节解析：支持常见的“第 X 章 / 第 X 回 / 卷 / 序章 / 番外”等章节标题格式。
- 分页阅读：每次加载固定字数，支持章节和页码切换。
- 阅读进度：按用户保存每本书的章节、页码、总章节数和阅读进度。
- 笔记功能：可按小说追加保存章节笔记到 `notes/` 目录。
- 小说管理：支持上传 TXT 小说，也支持从书架中删除小说。
- 小说下载器：`search.py` 可搜索并下载 TXT 小说，同时尝试修复编码为 UTF-8。
- 一键脚本：`server.sh` 支持启动、停止、重启和查看运行状态。

## 项目结构

```text
.
├── app.py                  # Flask 阅读器主程序
├── search.py               # TXT 小说搜索与下载工具
├── server.sh               # 本地服务启停脚本
├── templates/
│   └── read.html           # 阅读器页面
├── novel/                  # TXT 小说目录
├── notes/                  # 阅读笔记目录
├── tests/                  # 单元测试
├── requirements.txt        # Python 依赖
└── README.md
```

## 环境要求

- Python 3.10+
- macOS、Linux 或 Windows 均可运行

## 安装

```bash
git clone https://github.com/yushui6666/simple-novel-web-read.git
cd simple-novel-web-read

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 可使用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

直接运行：

```bash
python app.py
```

然后访问：

```text
http://127.0.0.1:6066
```

macOS/Linux 也可以使用脚本：

```bash
chmod +x server.sh
./server.sh start
./server.sh status
./server.sh stop
```

## 使用

1. 将 `.txt` 小说放入 `novel/` 目录，或在页面中上传 TXT 文件。
2. 打开 `http://127.0.0.1:6066`。
3. 选择小说开始阅读。
4. 阅读器会自动保存当前用户的阅读进度。
5. 需要记录想法时，可使用笔记功能，内容会写入 `notes/`。

## 下载小说

运行下载器：

```bash
python search.py
```

按提示输入小说名称，选择搜索结果后会下载到 `novel/` 目录。下载完成后刷新阅读器页面即可看到新书。

## 测试

```bash
python -m unittest discover -s tests
```

## 注意事项

- `reading_history.json` 是本地阅读进度文件，默认不会提交到仓库。
- `app.log`、虚拟环境、缓存、打包产物和本地快捷方式默认不会提交。
- 小说文本和笔记是否提交取决于个人使用场景；本项目保留 `novel/` 和 `notes/` 目录作为阅读器内容目录。
- 下载功能仅供学习和个人研究使用，请遵守目标网站规则和版权要求。
