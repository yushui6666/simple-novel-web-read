import json
import tempfile
import unittest
from pathlib import Path


class ReadingHistoryTest(unittest.TestCase):
    def test_reading_history_persists_and_is_cleared_on_delete(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            novel_dir = temp_path / "novel"
            novel_dir.mkdir()
            novel_path = novel_dir / "测试小说.txt"
            novel_path.write_text("第一章 开始\n正文内容\n第二章 继续\n更多正文", encoding="utf-8")

            old_novel_folder = app_module.NOVEL_FOLDER
            old_history_file = getattr(app_module, "HISTORY_FILE", None)
            app_module.NOVEL_FOLDER = str(novel_dir)
            app_module.HISTORY_FILE = str(temp_path / "reading_history.json")
            app_module._PARSE_CACHE.clear()

            try:
                client = app_module.app.test_client()

                response = client.post("/api/reading_history", json={
                    "novel": "测试小说.txt",
                    "chapter": 1,
                    "chapter_title": "第二章 继续",
                    "page": 1,
                    "total_pages": 2,
                    "total_chapters": 2,
                })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()["success"])

                history_file = temp_path / "reading_history.json"
                stored = json.loads(history_file.read_text(encoding="utf-8"))
                default_books = stored["users"]["default"]["books"]
                self.assertEqual(default_books["测试小说.txt"]["chapter_title"], "第二章 继续")
                self.assertEqual(default_books["测试小说.txt"]["progress_percent"], 100.0)

                response = client.get("/api/bookshelf")
                self.assertEqual(response.status_code, 200)
                books = response.get_json()["books"]
                self.assertEqual(books[0]["filename"], "测试小说.txt")
                self.assertEqual(books[0]["last_chapter_title"], "第二章 继续")
                self.assertEqual(books[0]["progress_percent"], 100.0)

                response = client.post("/api/delete_novel", json={"novel": "测试小说.txt"})
                self.assertEqual(response.status_code, 200)

                response = client.get("/api/bookshelf")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["books"], [])
            finally:
                app_module.NOVEL_FOLDER = old_novel_folder
                if old_history_file is None:
                    delattr(app_module, "HISTORY_FILE")
                else:
                    app_module.HISTORY_FILE = old_history_file
                app_module._PARSE_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
