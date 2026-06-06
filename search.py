import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import urljoin, unquote


class Txt80Downloader:
    """八零电子书 (txt80.cc) TXT小说下载器"""

    BASE_URL = "https://www.txt80.cc"
    SEARCH_URL = f"{BASE_URL}/e/search/index.php"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.session = requests.Session()
        self.default_save_dir = 'novel'

    def get_page(self, url, method='get', data=None):
        """获取网页内容"""
        try:
            if method == 'post':
                response = self.session.post(url, data=data, headers=self.headers, timeout=15)
            else:
                response = self.session.get(url, headers=self.headers, timeout=15)
            response.encoding = response.apparent_encoding or 'utf-8'
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"❌ 获取页面失败: {e}")
            return None

    def decode_filename(self, filename):
        """解码文件名"""
        if not filename:
            return filename

        try:
            decoded = unquote(filename)
            if decoded != filename:
                return decoded
        except Exception:
            pass

        if any('一' <= char <= '鿿' for char in filename):
            return filename

        try:
            raw_bytes = filename.encode('latin1')
        except UnicodeEncodeError:
            return filename

        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']:
            try:
                decoded = raw_bytes.decode(encoding)
                if any('一' <= char <= '鿿' for char in decoded):
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue

        return filename

    def search(self, keyword):
        """搜索小说，返回 [(书名, 详情页URL), ...]"""
        print(f"\n🔍 正在搜索: {keyword}")

        soup = self.get_page(
            self.SEARCH_URL,
            method='post',
            data={
                'show': 'title,softsay',
                'keyboard': keyword,
                'tbname': 'download',
                'tempid': '1',
            }
        )

        if not soup:
            return []

        results = []
        for link in soup.find_all('a', href=re.compile(r'/.*?/txt\d+\.html')):
            title_elem = link.find('font')
            text = link.get_text(strip=True)
            href = link.get('href', '')

            # 匹配格式: 《书名》全本TXT电子书下载
            match = re.search(r'《(.+?)》', text)
            if match:
                title = match.group(1)
                if keyword.lower() in title.lower():
                    url = urljoin(self.BASE_URL, href)
                    results.append((title, url))

        return results

    def download(self, detail_url, save_dir=None):
        """下载小说TXT文件"""
        if save_dir is None:
            save_dir = self.default_save_dir

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # Step 1: 获取详情页，提取中间下载页链接
        print(f"\n📖 正在访问小说详情页...")
        soup = self.get_page(detail_url)
        if not soup:
            return False

        # 提取书名
        title = "未知小说"
        title_match = re.search(r'《(.+?)》', soup.get_text())
        if title_match:
            title = title_match.group(1)
        print(f"📖 小说名称: {title}")

        # 查找中间下载链接 /down/txtXXX.html
        down_link = None
        for a in soup.find_all('a', href=re.compile(r'/down/txt.+\.html')):
            down_link = urljoin(self.BASE_URL, a.get('href'))
            break

        if not down_link:
            print("❌ 未找到下载链接")
            return False

        # Step 2: 获取中间下载页，提取直接下载URL
        print(f"🔗 正在获取下载地址...")
        soup = self.get_page(down_link)
        if not soup:
            return False

        direct_url = None
        for a in soup.find_all('a', href=re.compile(r'\.txt')):
            href = a.get('href', '').strip()
            if href and '.txt' in href.lower():
                direct_url = href if href.startswith('http') else urljoin(self.BASE_URL, href)
                break

        if not direct_url:
            print("❌ 未找到直接下载地址")
            return False

        print(f"📥 下载地址: {direct_url}")

        # Step 3: 下载文件
        try:
            print(f"⏬ 开始下载...")

            download_headers = self.headers.copy()
            download_headers['Referer'] = down_link

            response = self.session.get(direct_url, headers=download_headers, stream=True, timeout=120)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                print("❌ 下载链接返回的是HTML页面，可能是防盗链")
                return False

            total_size = int(response.headers.get('content-length', 0))

            # 确定文件名
            filename = None
            if 'content-disposition' in response.headers:
                cd = response.headers['content-disposition']
                m = re.search(r'filename[*]?=(?:UTF-8\'\')?"?([^";]+)', cd)
                if m:
                    filename = self.decode_filename(m.group(1))

            if not filename:
                filename = os.path.basename(direct_url.split('?')[0])
                filename = self.decode_filename(unquote(filename))

            filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
            save_path = os.path.join(save_dir, filename)

            import time

            downloaded = 0
            start_time = time.time()
            bar_width = 28

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(time.time() - start_time, 0.001)
                        speed = downloaded / elapsed

                        if total_size > 0:
                            percent = downloaded / total_size * 100
                            filled = int(bar_width * downloaded / total_size)
                            bar = '█' * filled + '░' * (bar_width - filled)
                            size_str = f"{self._human_size(downloaded)}/{self._human_size(total_size)}"
                        else:
                            # 无 content-length 时使用滚动动画
                            pos = (downloaded // 8192) % (bar_width * 2)
                            if pos < bar_width:
                                filled = pos
                            else:
                                filled = bar_width * 2 - pos
                            bar = '█' * filled + '▒' + '░' * max(bar_width - filled - 1, 0)
                            size_str = f"{self._human_size(downloaded)} 已下载"
                            percent = 0

                        print(
                            f"\r  {bar}  {size_str}  {self._human_size(speed)}/s  ",
                            end='', flush=True
                        )

            elapsed = time.time() - start_time
            print(f"\n\n✅ 下载完成！耗时 {elapsed:.1f} 秒")
            print(f"💾 保存位置: {os.path.abspath(save_path)}")
            print(f"📦 文件大小: {os.path.getsize(save_path) / 1024 / 1024:.2f} MB")

            self.fix_encoding(save_path)
            return True

        except Exception as e:
            print(f"\n❌ 下载失败: {e}")
            return False

    @staticmethod
    def _human_size(size_bytes):
        """将字节数转为人类可读的大小"""
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def fix_encoding(self, file_path):
        """检测并修复文件编码为UTF-8"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()

            if not raw_data:
                return

            best_encoding = 'utf-8'
            best_content = None
            best_chinese_count = -1

            for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']:
                try:
                    content = raw_data.decode(encoding)
                    chinese_count = sum(1 for c in content if '一' <= c <= '鿿')
                    if chinese_count > best_chinese_count:
                        best_chinese_count = chinese_count
                        best_encoding = encoding
                        best_content = content
                except (UnicodeDecodeError, LookupError):
                    continue

            if best_content and best_encoding != 'utf-8':
                print(f"🔄 检测到编码: {best_encoding}，转换为UTF-8...")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(best_content)
                print("✅ 编码转换完成")
        except Exception as e:
            print(f"⚠️  编码检查失败: {e}")


def main():
    print("=" * 60)
    print("📚 八零电子书 (txt80.cc) - TXT小说下载工具")
    print("=" * 60)

    downloader = Txt80Downloader()
    print(f"💾 默认下载目录: {downloader.default_save_dir}")

    print("\n请选择操作方式:")
    print("1. 搜索小说名称并下载")
    print("2. 直接输入小说详情页URL")

    choice = input("\n请选择 (1/2): ").strip() or "1"

    if choice == "1":
        keyword = input("\n请输入小说名称: ").strip()
        if not keyword:
            print("❌ 小说名称不能为空！")
            return

        results = downloader.search(keyword)

        if not results:
            print(f"❌ 未找到与 '{keyword}' 相关的小说")
            print("💡 提示: 可以尝试输入更简短的关键词，或直接输入详情页URL（选择操作方式2）")
            return

        # 去重
        seen = set()
        unique = []
        for t, u in results:
            if u not in seen:
                unique.append((t, u))
                seen.add(u)

        print(f"\n✅ 找到 {len(unique)} 个结果:\n")
        for i, (t, u) in enumerate(unique, 1):
            print(f"  {i}. 《{t}》")

        if len(unique) == 1:
            choice_idx = 1
        else:
            try:
                choice_idx = int(input(f"\n请选择 (1-{len(unique)}): "))
                if choice_idx < 1 or choice_idx > len(unique):
                    print("⚠️  选择超出范围，默认使用第1个结果")
                    choice_idx = 1
            except Exception:
                choice_idx = 1

        downloader.download(unique[choice_idx - 1][1])

    elif choice == "2":
        detail_url = input("\n请输入小说详情页URL: ").strip()
        if not detail_url:
            print("❌ URL不能为空！")
            return
        downloader.download(detail_url)

    else:
        print("❌ 无效选择！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n\n❌ 程序出错: {e}")
        import traceback
        traceback.print_exc()
