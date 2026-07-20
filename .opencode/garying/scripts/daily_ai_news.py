"""Send newly published official AI updates to the configured WeCom webhook."""

import argparse
import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as element_tree
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "daily_ai_news_state.json"
MAX_ITEMS_PER_SOURCE = 3
USER_AGENT = "GaryingDailyAINews/1.0"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def rss_items(url):
    root = element_tree.fromstring(fetch(url))
    items = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if title and link:
            items.append((title, link))
    return items


def page_items(url, link_pattern):
    page = fetch(url)
    items = []
    seen = set()
    for match in re.finditer(r'href="(' + link_pattern + r')"[^>]*>(.*?)</a>', page, re.DOTALL):
        path, label = match.groups()
        heading = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", label, re.DOTALL)
        title = clean_text(heading.group(1) if heading else label)
        link = urllib.request.urljoin(url, path)
        if title and link not in seen:
            seen.add(link)
            items.append((title, link))
    return items


def kimi_items():
    url = "https://www.kimi.com/blog/"
    page = fetch(url)
    items = []
    seen = set()
    for match in re.finditer(r'href="((?:https://www\.kimi\.com)?/blog/[^"]+)"', page):
        link = urllib.request.urljoin(url, match.group(1))
        if link in seen:
            continue
        seen.add(link)
        slug = link.rstrip("/").rsplit("/", 1)[-1]
        title = re.sub(r"[-_]", " ", slug).title()
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
        ("OpenAI", lambda: rss_items("https://openai.com/news/rss.xml")),
        ("Claude / Anthropic", lambda: page_items("https://www.anthropic.com/news", r'/(?:news|features)/[^"]+')),
        ("Kimi", kimi_items),
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
            failures.append(f"{name}: {type(error).__name__}")
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


def send_to_wecom(content):
    webhook = os.environ.get("WECOM_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("WECOM_WEBHOOK_URL is not configured")
    payload = json.dumps(
        {"msgtype": "markdown_v2", "markdown_v2": {"content": content}},
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
        raise RuntimeError(f"WeCom API error: {result.get('errcode')}")


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
    save_seen(seen | discovered)
    print("Daily AI news sent successfully")


if __name__ == "__main__":
    main()
