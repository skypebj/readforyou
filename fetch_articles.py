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
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== 配置 ====================
BASE_URL = "https://i.readforyou.life"
LIST_URL = f"{BASE_URL}/article/?order=today"
OUTPUT_DIR = "doc"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
]

def get_session():
    """创建带重试的会话"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": BASE_URL,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    # 添加重试机制
    retry = requests.adapters.Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def safe_request(url, session, max_retries=3, delay=2):
    """带延迟和重试的请求，返回响应对象或 None"""
    for i in range(max_retries):
        try:
            time.sleep(delay + random.uniform(0, 1))
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp
            else:
                logging.warning(f"状态码 {resp.status_code}，第 {i+1} 次重试")
        except Exception as e:
            logging.error(f"请求异常: {e}，第 {i+1} 次重试")
            time.sleep(2 ** i)
    return None

# ==================== 文章抓取 ====================
def fetch_article_list(session):
    """获取当日文章列表，返回文章信息列表"""
    resp = safe_request(LIST_URL, session)
    if not resp:
        logging.error("无法获取列表页")
        return []

    # 打印响应摘要用于调试
    html_preview = resp.text[:500].replace('\n', ' ')
    logging.info(f"列表页响应预览: {html_preview}...")

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    # 多种选择器策略
    selectors = [
        ("a", {"href": re.compile(r"^/article/\d+")}),          # 直接匹配 href
        ("a", {"class": re.compile(r"link")}),                  # 包含 link 类
        ("a", {"class": re.compile(r"text-lg")}),               # 原选择器
        ("a", {"class": "link-hover"}),                         # 精确匹配
    ]

    for tag, attrs in selectors:
        found = soup.find_all(tag, attrs)
        if found:
            logging.info(f"选择器 {tag} {attrs} 找到 {len(found)} 个链接")
            for link in found:
                href = link.get("href")
                if href and href.startswith("/article/"):
                    article_id = href.split("/")[-1]
                    title = link.get_text(strip=True)
                    if title and article_id.isdigit():
                        articles.append({
                            "id": article_id,
                            "title": title,
                            "url": f"{BASE_URL}{href}"
                        })
            if articles:
                break  # 找到有效文章后停止尝试其他选择器

    # 去重
    seen = set()
    unique = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)

    logging.info(f"共提取到 {len(unique)} 篇独特文章")
    if not unique:
        # 调试：输出所有链接
        all_links = soup.find_all("a", href=True)
        logging.info("页面中所有链接: " + ", ".join([a.get("href") for a in all_links[:20]]))
    return unique

def fetch_article_detail(article, session):
    """抓取单篇文章详情"""
    resp = safe_request(article["url"], session)
    if not resp:
        logging.warning(f"抓取详情失败: {article['url']}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 尝试多个正文容器选择器
    content_selectors = [
        "div.prose",
        "article",
        "div.content",
        "div.article-body",
        "div.post-content",
        "div[class*='content']",
        "div[class*='article']",
        "div[class*='body']",
    ]

    content_div = None
    for selector in content_selectors:
        content_div = soup.select_one(selector)
        if content_div:
            logging.info(f"使用选择器 '{selector}' 提取正文")
            break

    if content_div:
        # 清理无用标签
        for tag in content_div.find_all(["script", "style", "noscript", "iframe", "ins", "form"]):
            tag.decompose()
        content_html = str(content_div)
    else:
        logging.warning(f"未找到正文容器，文章: {article['title']}")
        content_html = "<p>无法提取正文内容</p>"

    # 提取元信息（来源、时间）
    meta = {}
    meta_candidates = soup.find_all(["p", "div"], class_=re.compile(r"meta|info|source|date"))
    for elem in meta_candidates:
        text = elem.get_text(strip=True)
        if "·" in text:
            parts = text.split("·")
            if len(parts) >= 2:
                meta["source"] = parts[0].strip()
                meta["time"] = parts[1].strip()
                break
        elif "来源" in text or "时间" in text:
            # 尝试提取
            if "来源" in text:
                meta["source"] = text.split("来源")[-1].strip()
            if "时间" in text:
                meta["time"] = text.split("时间")[-1].strip()

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

    book.set_identifier(f"babel_{date_str}")
    book.set_title(f"巴别阅读 - {date_str}")
    book.set_language("zh-CN")
    book.add_author("巴别阅读")

    style = """
    @namespace epub "http://www.idpf.org/2007/ops";
    body { font-family: "Noto Serif SC", "SimSun", serif; line-height: 1.8; margin: 1.5em; }
    h1 { font-size: 1.8em; text-align: center; margin-bottom: 0.5em; }
    .meta { color: #666; font-size: 0.9em; text-align: center; text-indent: 0; border-bottom: 1px solid #ddd; padding-bottom: 1em; }
    .article-title { font-size: 1.2em; font-weight: bold; margin-top: 1.5em; margin-bottom: 0.3em; }
    img { max-width: 100%; }
    p { text-indent: 2em; margin: 0.5em 0; }
    """
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)

    spine = ["nav"]
    toc = []

    for idx, item in enumerate(articles_data):
        title = item.get("title", f"文章 {idx+1}")

        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{idx+1}.xhtml",
            lang="zh-CN"
        )

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

    book.toc = toc
    book.spine = spine

    nav = epub.EpubNav()
    nav.add_item(nav_css)
    book.add_item(nav)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{OUTPUT_DIR}/babel_{date_str}.epub"
    epub.write_epub(filename, book, {})
    logging.info(f"✅ EPUB 已生成: {filename}")
    return filename

# ==================== 主流程 ====================
def main():
    # 北京时间
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    yesterday = beijing_time - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")

    logging.info(f"📅 开始抓取 {date_str} 的文章...")

    session = get_session()

    # 1. 获取文章列表
    articles = fetch_article_list(session)
    if not articles:
        logging.error("未获取到文章，请检查网站可访问性或更新选择器")
        return

    # 2. 抓取详情
    articles_data = []
    for i, art in enumerate(articles):
        logging.info(f"📖 抓取 [{i+1}/{len(articles)}]: {art['title'][:30]}...")
        detail = fetch_article_detail(art, session)
        if detail:
            articles_data.append(detail)
        # 礼貌延迟
        time.sleep(random.uniform(0.5, 1.5))

    logging.info(f"✅ 成功抓取 {len(articles_data)} 篇详情")

    # 3. 生成 EPUB
    if articles_data:
        create_epub(articles_data, date_str)
    else:
        logging.warning("没有成功抓取任何文章，跳过 EPUB 生成")

if __name__ == "__main__":
    main()
