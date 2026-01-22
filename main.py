"""
cron: 0 */6 * * *
new Env("Linux.Do 纯 API 阅读")
"""

import os
import time
import random
import re
from typing import List
from loguru import logger
from curl_cffi import requests
from bs4 import BeautifulSoup


# ===================== 配置 =====================

LOGIN_URL = "https://linux.do/login"
CSRF_URL = "https://linux.do/session/csrf"
SESSION_URL = "https://linux.do/session"
LATEST_URL = "https://linux.do/latest"
CONNECT_URL = "https://connect.linux.do/"

USERNAME = os.getenv("LINUXDO_USERNAME") or os.getenv("USERNAME")
PASSWORD = os.getenv("LINUXDO_PASSWORD") or os.getenv("PASSWORD")

BROWSE_TARGET = 20       # 每次最多补多少“阅读”
MIN_READ_SEC = 15        # 每篇最小阅读时间
MAX_READ_SEC = 45        # 每篇最大阅读时间

# ===================== 工具函数 =====================

def gen_ua():
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


def sleep_human(sec):
    logger.info(f"模拟阅读 {sec:.1f}s")
    time.sleep(sec)


# ===================== 主类 =====================

class LinuxDoClient:
    def __init__(self):
        self.ua = gen_ua()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    # ---------- 登录 ----------
    def login(self) -> bool:
        logger.info("开始 API 登录流程")

        # 1️⃣ 建立 session
        self.session.get(LOGIN_URL, impersonate="chrome136")

        # 2️⃣ 获取 CSRF
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        r = self.session.get(CSRF_URL, headers=headers, impersonate="chrome136")

        if "application/json" not in r.headers.get("Content-Type", ""):
            logger.error("CSRF 接口返回非 JSON")
            logger.error(r.text[:300])
            return False

        csrf = r.json().get("csrf")
        if not csrf:
            logger.error("CSRF 字段缺失")
            return False

        logger.success("CSRF 获取成功")

        # 3️⃣ 登录
        headers.update({
            "X-CSRF-Token": csrf,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://linux.do",
        })

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        r = self.session.post(
            SESSION_URL,
            headers=headers,
            data=data,
            impersonate="chrome136"
        )

        if r.status_code != 200 or r.json().get("error"):
            logger.error(f"登录失败: {r.text}")
            return False

        logger.success("登录成功")
        return True

    # ---------- 获取未完成的阅读数 ----------
    def get_needed_reads(self) -> int:
        r = self.session.get(CONNECT_URL, impersonate="chrome136")
        soup = BeautifulSoup(r.text, "html.parser")

        for row in soup.select("table tr"):
            tds = row.select("td")
            if len(tds) >= 3 and "阅读" in tds[0].text:
                cur = int(tds[1].text.strip() or 0)
                need = int(tds[2].text.strip() or 0)
                logger.info(f"阅读进度 {cur}/{need}")
                return max(0, need - cur)

        logger.warning("未找到阅读项目，默认补 0")
        return 0

    # ---------- 获取帖子列表 ----------
    def get_topics(self, limit=30) -> List[int]:
        r = self.session.get(LATEST_URL, impersonate="chrome136")
        soup = BeautifulSoup(r.text, "html.parser")

        ids = []
        for a in soup.select("a.title"):
            m = re.search(r"/t/[^/]+/(\d+)", a.get("href", ""))
            if m:
                ids.append(int(m.group(1)))

        logger.info(f"获取到 {len(ids)} 个帖子 ID")
        return ids[:limit]

    # ---------- 模拟阅读 ----------
    def read_topic(self, topic_id: int):
        sec = random.uniform(MIN_READ_SEC, MAX_READ_SEC)
        sleep_human(sec)

        url = f"https://linux.do/topics/{topic_id}/timings"
        data = {
            "timings[0][topic_id]": topic_id,
            "timings[0][total_time]": int(sec),
        }

        r = self.session.post(
            url,
            data=data,
            headers={
                "Accept": "*/*",
                "Referer": f"https://linux.do/t/{topic_id}",
                "X-Requested-With": "XMLHttpRequest",
            },
            impersonate="chrome136"
        )

        if r.status_code == 200:
            logger.success(f"阅读计时提交成功 topic={topic_id}")
        else:
            logger.warning(f"阅读计时失败 topic={topic_id}")

    # ---------- 主流程 ----------
    def run(self):
        if not self.login():
            return

        need = self.get_needed_reads()
        if need <= 0:
            logger.success("阅读已完成，无需补充")
            return

        topics = self.get_topics()
        random.shuffle(topics)

        for topic_id in topics[:min(need, BROWSE_TARGET)]:
            self.read_topic(topic_id)


# ===================== 入口 =====================

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        logger.error("请设置 LINUXDO_USERNAME / LINUXDO_PASSWORD")
        exit(1)

    LinuxDoClient().run()
