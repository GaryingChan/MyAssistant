"""Send the Kangrun data-validation reminder to the configured WeCom group."""

import json
import os
import urllib.request


def main():
    webhook = os.environ.get("KR_WECOM_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("KR_WECOM_WEBHOOK_URL is not configured")
    yuejia_mobile = os.environ.get("KR_YUEJIA_MOBILE")
    if not yuejia_mobile:
        raise RuntimeError("KR_YUEJIA_MOBILE is not configured")

    content = """悦嘉，请汇报康润数据校对进度。

请说明：
1. 当前已完成情况
2. 待处理问题或风险
3. 预计完成时间"""
    payload = json.dumps(
        {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_mobile_list": [yuejia_mobile],
            },
        },
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


if __name__ == "__main__":
    main()
