"""Send AI toy industry news from Google News RSS to a WeCom webhook."""

import argparse
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "toy_ai_news_state.json"
MAX_ITEMS = 15
USER_AGENT = "GaryingToyAINews/1.0"
QUERY = "(人工智能 OR AI OR 大模型 OR 智能体 OR 机器人) (玩具 OR 智能玩具 OR 陪伴玩具 OR 机器人玩具 OR 潮玩)"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def google_news_url():
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {
            "q": QUERY,
            "hl": "zh-CN",
            "gl": "CN",
            "ceid": "CN:zh-Hans",
        }
    )


def collect_items():
    root = ET.fromstring(fetch(google_news_url()))
    items = []
    seen = set()
    for entry in root.findall("./channel/item"):
        title = clean_text(entry.findtext("title", default=""))
        link = entry.findtext("link", default="")
        if title and link and link not in seen:
            seen.add(link)
            items.append((title, link))
    return items[:MAX_ITEMS]


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


def format_message(items, failure=None):
    lines = [f"# AI 玩具行业资讯 | {datetime.now():%Y-%m-%d}"]
    if failure:
        lines.append(f"\n> 本次抓取失败：{failure}")
    elif items:
        lines.extend(f"- [{title}]({link})" for title, link in items)
    else:
        lines.append("\n> 暂无未推送的 AI 玩具行业资讯。")
    return "\n".join(lines)


def split_message(content, max_bytes=3800):
    chunks = []
    current_lines = []
    current_size = 0
    for line in content.splitlines():
        line_size = len((line + "\n").encode("utf-8"))
        if current_lines and current_size + line_size > max_bytes:
            chunks.append("\n".join(current_lines))
            current_lines = ["# AI 玩具行业资讯（续）", line]
            current_size = len((current_lines[0] + "\n" + line + "\n").encode("utf-8"))
        else:
            current_lines.append(line)
            current_size += line_size
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


def send_to_wecom(content):
    webhook = os.environ.get("TOY_AI_NEWS_WECOM_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("TOY_AI_NEWS_WECOM_WEBHOOK_URL is not configured")
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
    try:
        items = collect_items()
    except Exception as error:
        message = format_message([], str(error))
        if args.dry_run:
            print(message)
            return
        send_to_wecom(message)
        raise RuntimeError("News collection failed; sent a failure notification without updating state")

    fresh = [(title, link) for title, link in items if link not in seen]
    message = format_message(fresh)
    if args.dry_run:
        print(message)
        return
    send_to_wecom(message)
    save_seen(seen | {link for _, link in fresh})
    print("AI toy industry news sent successfully")


if __name__ == "__main__":
    main()
