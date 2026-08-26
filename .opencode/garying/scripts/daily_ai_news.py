"""Send newly published AI updates from RSS feeds to the configured WeCom webhook."""

import argparse
import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "daily_ai_news_state.json"
MAX_ITEMS_PER_SOURCE = 10
USER_AGENT = "GaryingDailyAINews/1.0"
AI_KEYWORDS = (
    "ai",
    "人工智能",
    "大模型",
    "模型",
    "智能体",
    "agent",
    "openai",
    "anthropic",
    "deepseek",
    "通义",
    "豆包",
    "生成式",
)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    if "_wafchallengeid" in page or "正在进行安全检测" in page:
        raise RuntimeError("36Kr returned a WAF challenge page")
    return page


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def rss_items(url, keywords=()):
    feed = fetch(url)
    root = ET.fromstring(feed)
    items = []
    seen = set()
    rss_entries = root.findall("./channel/item")
    atom_entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    for entry in rss_entries + atom_entries:
        title = entry.findtext("title", default="")
        if not title:
            title = entry.findtext("{http://www.w3.org/2005/Atom}title", default="")
        title = clean_text(title)
        link = entry.findtext("link", default="")
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link[@rel='alternate']")
            if atom_link is None:
                atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            link = atom_link.get("href", "") if atom_link is not None else ""
        haystack = title.lower()
        if keywords and not any(keyword in haystack for keyword in keywords):
            continue
        if title and link not in seen:
            seen.add(link)
            items.append((title, link))
    return items


def load_seen():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data.get("seen_urls", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps({"seen_urls": sorted(seen)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_updates(seen):
    sources = (
        ("InfoQ AI", lambda: rss_items("https://www.infoq.cn/feed", AI_KEYWORDS)),
        ("IT之家 AI", lambda: rss_items("https://www.ithome.com/rss/", AI_KEYWORDS)),
        ("量子位", lambda: rss_items("https://www.qbitai.com/feed")),
        ("极客公园 AI", lambda: rss_items("https://www.geekpark.net/rss", AI_KEYWORDS)),
        ("雷峰网 AI", lambda: rss_items("https://www.leiphone.com/feed", AI_KEYWORDS)),
    )
    updates = []
    discovered = set()
    failures = []
    for name, get_items in sources:
        try:
            fresh = [(title, link) for title, link in get_items() if link not in seen]
            fresh = fresh[:MAX_ITEMS_PER_SOURCE]
            updates.append((name, fresh))
            discovered.update(link for _, link in fresh)
        except Exception as error:
            failures.append(f"{name}: {error}")
    return updates, discovered, failures


def format_message(updates, failures):
    lines = [f"# 每日 AI 动态 | {datetime.now():%Y-%m-%d}"]
    item_count = 0
    for source, items in updates:
        lines.append(f"## {source}")
        if items:
            item_count += len(items)
            lines.extend(f"- [{title}]({link})" for title, link in items)
        else:
            lines.append("- 暂无未推送的官方更新")
    if failures:
        lines.append("\n> 以下官方源本次获取失败：" + "、".join(failures))
    if item_count == 0 and not failures:
        lines.append("\n> 今日未发现新的官方发布。")
    return "\n".join(lines)


def split_message(content, max_bytes=3800):
    chunks = []
    current_lines = []
    current_size = 0
    for line in content.splitlines():
        line_size = len((line + "\n").encode("utf-8"))
        if current_lines and current_size + line_size > max_bytes:
            chunks.append("\n".join(current_lines))
            current_lines = ["# 每日资讯（续）", line]
            current_size = len((current_lines[0] + "\n" + line + "\n").encode("utf-8"))
        else:
            current_lines.append(line)
            current_size += line_size
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


def send_to_wecom(content):
    webhook = os.environ.get("WECOM_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("WECOM_WEBHOOK_URL is not configured")
    for chunk in split_message(content):
        payload = json.dumps(
            {"msgtype": "markdown_v2", "markdown_v2": {"content": chunk}},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("errcode") != 0:
            raise RuntimeError(
                f"WeCom API error {result.get('errcode')}: {result.get('errmsg', 'unknown error')}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seen = load_seen()
    updates, discovered, failures = collect_updates(seen)
    message = format_message(updates, failures)
    if args.dry_run:
        print(message)
        return
    send_to_wecom(message)
    if failures and not updates:
        raise RuntimeError("All news sources failed; sent a failure notification without updating state")
    save_seen(seen | discovered)
    print("Daily AI news sent successfully")


if __name__ == "__main__":
    main()
