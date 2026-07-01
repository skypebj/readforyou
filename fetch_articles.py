#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import random
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from ebooklib import epub
import re

# ==================== 配置 ====================
BASE_URL = "https://i.readforyou.life"
LIST_URL = f"{BASE_URL}/article/?order=today"
OUTPUT_DIR = "doc"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]

# ==================== 工具函数 ====================
def get_headers():
    """随机获取请求头"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": BASE_URL,
    }

def safe_request(url, max_retries=3, delay=1):
    """带重试和延迟的安全请求"""
    for i in range(max_retries):
        try:
            time.sleep(delay + random.uniform(0, 0.5))
            resp = requests.get(url, headers=get_headers(), timeout=30)
            if resp.status_code == 200:
                return resp
        except Exception as e:
            print(f"请求失败 ({i+1}/{max_retries}): {e}")
            time.sleep(2 ** i)
    return None

# ==================== 文章抓取 ====================
def fetch_article_list():
    """获取当日文章列表"""
    resp = safe_request(LIST_URL)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    # 查找所有文章链接（源码中 class 为 "text-lg link link-hover"）
    for link in soup.find_all("a", class_="text-lg link link-hover"):
        href = link.get("href")
        if href and href.startswith("/article/"):
            article_id = href.split("/")[-1]
            title = link.get_text(strip=True)
            if title:
                articles.append({
                    "id": article_id,
                    "title": title,
                    "url": f"{BASE_URL}{href}"
                })

    # 去重（保留首次出现顺序）
    seen = set()
    unique = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)
    return unique

def fetch_article_detail(article):
    """抓取单篇文章详情"""
    resp = safe_request(article["url"])
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取正文内容 - 根据实际页面结构调整选择器
    content_div = soup.find("div", class_="prose") or soup.find("article") or soup.find("div", class_="content")

    if not content_div:
        # 尝试更通用的查找
        content_div = soup.find("div", class_=re.compile(r"content|article|body|prose"))

    if content_div:
        # 清理不需要的元素
        for tag in content_div.find_all(["script", "style", "noscript", "iframe", "ins"]):
            tag.decompose()
        content_html = str(content_div)
    else:
        content_html = "<p>无法提取正文内容</p>"

    # 提取来源和发布时间
    meta = {}
    for p in soup.find_all("p", class_=re.compile(r"text-gray|meta|info")):
        text = p.get_text(strip=True)
        if "·" in text:
            parts = text.split("·")
            if len(parts) >= 2:
                meta["source"] = parts[0].strip()
                meta["time"] = parts[1].strip()

    return {
        "title": article["title"],
        "url": article["url"],
        "content": content_html,
        "source": meta.get("source", "未知来源"),
        "time": meta.get("time", ""),
    }

# ==================== EPUB 生成 ====================
def create_epub(articles_data, date_str):
    """生成 EPUB 3.0 文件"""
    book = epub.EpubBook()

    # 元数据
    book.set_identifier(f"babel_{date_str}")
    book.set_title(f"巴别阅读 - {date_str}")
    book.set_language("zh-CN")
    book.add_author("巴别阅读")

    # 创建样式
    style = """
    @namespace epub "http://www.idpf.org/2007/ops";
    body { font-family: "Noto Serif SC", "SimSun", serif; line-height: 1.8; margin: 1.5em; }
    h1 { font-size: 1.8em; text-align: center; margin-bottom: 0.5em; }
    h2 { font-size: 1.4em; margin-top: 1.5em; margin-bottom: 0.5em; }
    p { text-indent: 2em; margin: 0.5em 0; }
    .meta { color: #666; font-size: 0.9em; text-align: center; text-indent: 0; border-bottom: 1px solid #ddd; padding-bottom: 1em; }
    .article-title { font-size: 1.2em; font-weight: bold; margin-top: 1.5em; margin-bottom: 0.3em; }
    img { max-width: 100%; }
    """
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)

    # 创建 Spine 和 TOC
    spine = ["nav"]
    toc = []

    for idx, item in enumerate(articles_data):
        title = item.get("title", f"文章 {idx+1}")

        # 创建章节
        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{idx+1}.xhtml",
            lang="zh-CN"
        )

        # 构建内容
        source_info = f"{item.get('source', '')} {item.get('time', '')}".strip()
        content_body = f"""
        <h1>{title}</h1>
        <div class="meta">{source_info}</div>
        {item.get('content', '<p>无内容</p>')}
        """
        chapter.content = f"""
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml">
        <head><title>{title}</title>
        <link rel="stylesheet" type="text/css" href="style/nav.css"/>
        </head>
        <body>{content_body}</body>
        </html>
        """

        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, title, f"chap_{idx+1}"))

    # 创建导航
    book.toc = toc
    book.spine = spine

    # 添加导航文件
    nav = epub.EpubNav()
    nav.add_item(nav_css)
    book.add_item(nav)

    # 生成文件
    filename = f"{OUTPUT_DIR}/babel_{date_str}.epub"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    epub.write_epub(filename, book, {})
    print(f"✅ EPUB 已生成: {filename}")
    return filename

# ==================== 主流程 ====================
def main():
    # 获取前一日日期（北京时间）
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    yesterday = beijing_time - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")

    print(f"📅 开始抓取 {date_str} 的文章...")

    # 1. 获取文章列表
    articles = fetch_article_list()
    print(f"📰 发现 {len(articles)} 篇文章")

    if not articles:
        print("⚠️ 未获取到文章，请检查网站是否可访问")
        return

    # 2. 抓取每篇文章详情
    articles_data = []
    for i, art in enumerate(articles):
        print(f"  📖 抓取 [{i+1}/{len(articles)}]: {art['title'][:30]}...")
        detail = fetch_article_detail(art)
        if detail:
            articles_data.append(detail)

    print(f"✅ 成功抓取 {len(articles_data)} 篇详情")

    # 3. 生成 EPUB
    if articles_data:
        create_epub(articles_data, date_str)
    else:
        print("⚠️ 没有成功抓取任何文章，跳过 EPUB 生成")

if __name__ == "__main__":
    main()
