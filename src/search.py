import requests
from bs4 import BeautifulSoup
import time
import os
import re
from urllib.parse import urljoin, urlparse, unquote
import chardet

class Novel80Downloader:
    def __init__(self):
        """初始化80小说网下载器"""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.session = requests.Session()
        # 设置默认下载目录
        self.default_save_dir = r'D:\read\dist\novel'
    
    def get_page(self, url):
        """获取网页内容"""
        try:
            response = self.session.get(url, headers=self.headers, timeout=15)
            response.encoding = response.apparent_encoding or 'utf-8'
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"❌ 获取页面失败: {e}")
            return None
    
    def decode_filename(self, filename):
        """解码文件名，处理乱码问题"""
        if not filename:
            return filename
        
        # 先尝试URL解码（处理%E6%96%97%E7%BD%97%E5%A4%A7%E9%99%86.txt这种情况）
        try:
            decoded = unquote(filename)
            if decoded != filename:
                print(f"🔤 URL解码文件名: {decoded}")
                return decoded
        except:
            pass
            
        # 尝试不同的编码方式
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin1']
        
        for encoding in encodings:
            try:
                decoded = filename.encode('latin1').decode(encoding)
                # 检查解码后的字符串是否包含中文字符
                if any('\u4e00' <= char <= '\u9fff' for char in decoded):
                    return decoded
            except:
                continue
        
        # 如果都不行，返回原始文件名
        return filename
    
    def download_txt_file(self, download_url, save_dir=None):
        """
        直接下载TXT文件
        :param download_url: TXT下载页面URL
        :param save_dir: 保存目录，默认为D:\read\dist\novel
        """
        # 如果没有指定保存目录，使用默认目录
        if save_dir is None:
            save_dir = self.default_save_dir
            
        print("\n" + "="*60)
        print("📥 正在下载TXT文件...")
        print("="*60)
        
        # 创建保存目录
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            print(f"📁 创建目录: {save_dir}")
        
        # 获取下载页面
        soup = self.get_page(download_url)
        if not soup:
            print("❌ 无法访问下载页面")
            return False
        
        # 查找小说标题
        title = "未知小说"
        title_selectors = ['h1', 'title', '.book-title', '.title']
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                title = title_elem.get_text(strip=True)
                title = re.sub(r'TXT.*下载|全集.*|完.*', '', title).strip()
                break
        
        print(f"📖 小说名称: {title}")
        
        # 查找真实的TXT下载链接
        download_link = None
        
        # 优先查找手机版TXT链接（不是ZIP）
        txt_links = soup.find_all('a', href=re.compile(r'\.txt', re.IGNORECASE))
        for link in txt_links:
            href = link.get('href')
            text = link.get_text(strip=True)
            # 跳过"最新章节"和"备份"链接，优先选择主下载链接
            if href and '.txt' in href.lower():
                if 'nt.80zw.la' not in href and 'txt.80zw.la' not in href:  # 排除最新50章和备份
                    download_link = href if href.startswith('http') else urljoin(download_url, href)
                    print(f"🔗 找到TXT下载链接: {download_link}")
                    break
        
        # 如果没找到，尝试任何TXT链接
        if not download_link:
            for link in txt_links:
                href = link.get('href')
                if href:
                    download_link = href if href.startswith('http') else urljoin(download_url, href)
                    print(f"🔗 找到TXT下载链接: {download_link}")
                    break
        
        # 方法2: 查找ZIP文件链接（作为备选）
        if not download_link:
            zip_links = soup.find_all('a', href=re.compile(r'\.zip', re.IGNORECASE))
            for link in zip_links:
                href = link.get('href')
                if href and 'nz.80zw.la' not in href and 'zip.80zw.la' not in href:  # 排除最新50章和备份
                    download_link = href if href.startswith('http') else urljoin(download_url, href)
                    print(f"🔗 找到ZIP下载链接: {download_link}")
                    break
        
        if not download_link:
            print("\n❌ 未找到TXT下载链接")
            print("💡 可能原因:")
            print("   1. 该页面不是直接下载页")
            print("   2. 网站需要登录或验证")
            print("   3. 链接格式特殊，需要手动分析")
            print("\n📝 请尝试:")
            print("   1. 在浏览器中打开这个URL")
            print("   2. 找到真正的TXT下载按钮")
            print("   3. 右键复制下载链接")
            print("   4. 再次运行程序，输入真实下载链接")
            return False
        
        # 开始下载
        try:
            print(f"\n⏬ 开始下载...")
            
            # 添加特殊headers，模拟浏览器下载
            download_headers = self.headers.copy()
            download_headers['Referer'] = download_url
            
            response = self.session.get(download_link, headers=download_headers, stream=True, timeout=60)
            response.raise_for_status()
            
            # 检查是否又返回了HTML（说明链接不对）
            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                print("\n❌ 下载链接返回的是HTML页面，不是文件")
                print("💡 这可能是防盗链或需要特殊处理")
                print(f"📋 Content-Type: {content_type}")
                return False
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 判断文件类型
            is_zip = download_link.lower().endswith('.zip')
            
            # 从URL或响应头获取文件名
            filename = None
            if 'content-disposition' in response.headers:
                content_disp = response.headers['content-disposition']
                filename_match = re.search(r'filename="?(.+?)"?(?:;|$)', content_disp)
                if filename_match:
                    filename = filename_match.group(1)
                    print(f"📄 服务器返回的文件名: {filename}")
                    # 解码文件名，处理乱码
                    filename = self.decode_filename(filename)
                    print(f"🔤 解码后的文件名: {filename}")
            
            if not filename:
                # 清理文件名中的非法字符
                safe_title = title.replace('\\', '_').replace('/', '_').replace(':', '_')
                safe_title = safe_title.replace('*', '_').replace('?', '_').replace('"', '_')
                safe_title = safe_title.replace('<', '_').replace('>', '_').replace('|', '_')
                filename = f"{safe_title}.{'zip' if is_zip else 'txt'}"
            
            # 确保文件名是安全的
            filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
            
            save_path = os.path.join(save_dir, filename)
            
            # 下载文件
            downloaded = 0
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = downloaded / total_size * 100
                            print(f"\r   进度: {percent:.1f}% ({downloaded}/{total_size} 字节)", end='', flush=True)
            
            print(f"\n\n✅ 下载完成！")
            print(f"💾 保存位置: {os.path.abspath(save_path)}")
            print(f"📦 文件大小: {os.path.getsize(save_path) / 1024 / 1024:.2f} MB")
            
            # 如果是ZIP文件，尝试解压
            if is_zip:
                print(f"\n📦 检测到ZIP压缩包，尝试解压...")
                try:
                    import zipfile
                    extract_dir = os.path.join(save_dir, 'extracted')
                    if not os.path.exists(extract_dir):
                        os.makedirs(extract_dir)
                    
                    with zipfile.ZipFile(save_path, 'r') as zip_ref:
                        # 列出压缩包内容
                        file_list = zip_ref.namelist()
                        print(f"   压缩包内文件: {', '.join(file_list)}")
                        
                        # 解压所有文件
                        zip_ref.extractall(extract_dir)
                        print(f"✅ 解压完成！文件保存在: {os.path.abspath(extract_dir)}")
                        
                        # 对解压出的TXT文件进行编码检查
                        for extracted_file in file_list:
                            if extracted_file.endswith('.txt'):
                                txt_path = os.path.join(extract_dir, extracted_file)
                                self.check_and_fix_encoding(txt_path)
                except Exception as e:
                    print(f"⚠️  解压失败: {e}")
                    print(f"   你可以手动解压ZIP文件")
            else:
                # 检测编码并尝试转换
                self.check_and_fix_encoding(save_path)
            
            print("="*60)
            return True
            
        except Exception as e:
            print(f"\n❌ 下载失败: {e}")
            return False
    
    def check_and_fix_encoding(self, file_path):
        """检查并修复文件编码"""
        try:
            # 尝试检测文件编码
            with open(file_path, 'rb') as f:
                raw_data = f.read()
            
            # 尝试不同编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']
            content = None
            detected_encoding = None
            
            for encoding in encodings:
                try:
                    content = raw_data.decode(encoding)
                    detected_encoding = encoding
                    break
                except:
                    continue
            
            if content and detected_encoding != 'utf-8':
                print(f"\n🔄 检测到编码: {detected_encoding}，转换为UTF-8...")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print("✅ 编码转换完成")
        except Exception as e:
            print(f"\n⚠️  编码检查失败: {e}")
    
    def search_and_download(self, keyword):
        """搜索并下载小说（从80zw.la）"""
        base_url = "http://www.80zw.la"
        
        print(f"\n🔍 正在搜索: {keyword}")
        
        # 访问首页查找
        soup = self.get_page(base_url)
        if not soup:
            return False
        
        results = []
        all_links = soup.find_all('a', href=re.compile(r'/txtxz/\d+\.html'))
        
        for link in all_links:
            title = link.get_text(strip=True)
            if keyword.lower() in title.lower():
                url = urljoin(base_url, link.get('href'))
                results.append((title, url))
        
        # 去重
        unique_results = []
        seen_urls = set()
        for title, url in results:
            if url not in seen_urls:
                unique_results.append((title, url))
                seen_urls.add(url)
        
        if not unique_results:
            print(f"❌ 未找到 '{keyword}'")
            return False
        
        print(f"\n✅ 找到 {len(unique_results)} 个结果:\n")
        for i, (title, url) in enumerate(unique_results, 1):
            print(f"{i}. {title}")
        
        if len(unique_results) == 1:
            choice = 1
        else:
            try:
                choice = int(input(f"\n请选择 (1-{len(unique_results)}): "))
            except:
                choice = 1
        
        novel_url = unique_results[choice - 1][1]
        
        # 获取小说页面，查找下载链接
        print(f"\n📖 正在访问小说页面...")
        soup = self.get_page(novel_url)
        if soup:
            # 查找下载链接
            download_links = soup.find_all('a', href=re.compile(r'down|download|txt'))
            if download_links:
                download_url = urljoin(novel_url, download_links[0].get('href'))
                return self.download_txt_file(download_url)
        
        return False


def main():
    """主程序"""
    print("="*60)
    print("📚 80小说网 - TXT文件下载工具")
    print("="*60)
    
    downloader = Novel80Downloader()
    
    print(f"💾 默认下载目录: {downloader.default_save_dir}")
    
    print("\n请选择操作方式:")
    print("1. 直接输入下载页面URL")
    print("2. 搜索小说名称")
    
    choice = input("\n请选择 (1/2): ").strip() or "1"
    
    if choice == "1":
        download_url = input("\n请输入下载页面URL: ").strip()
        
        if not download_url:
            print("❌ URL不能为空！")
            return
        
        downloader.download_txt_file(download_url)
    
    elif choice == "2":
        keyword = input("\n请输入小说名称: ").strip()
        
        if not keyword:
            print("❌ 小说名称不能为空！")
            return
        
        downloader.search_and_download(keyword)
    
    else:
        print("❌ 无效选择！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断下载")
    except Exception as e:
        print(f"\n\n❌ 程序出错: {e}")
        import traceback
        traceback.print_exc()