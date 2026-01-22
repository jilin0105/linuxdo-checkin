"""
cron: 0 */6 * * *
new Env("Linux.Do Connect 自动补全 · 阅读 + 点赞")
"""

import os
import time
import random
import re
from loguru import logger
from typing import Dict, List
from curl_cffi import requests
from bs4 import BeautifulSoup


# ===================== 基础配置 =====================

LOGIN_URL = "https://linux.do/login"
CSRF_URL = "https://linux.do/session/csrf"
SESSION_URL = "https://linux.do/session"
LATEST_URL = "https://linux.do/latest"
CONNECT_URL = "https://connect.linux.do/"

USERNAME = os.getenv("LINUXDO_USERNAME") or os.getenv("USERNAME")
PASSWORD = os.getenv("LINUXDO_PASSWORD") or os.getenv("PASSWORD")

MAX_FAIL = 5
READ_SEGMENTS = (2, 4)
READ_TIME = (12, 45)

# ===================== 工具 =====================

def ua():
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

def human_sleep(a, b):
    t = random.uniform(a, b)
    logger.info(f"等待 {t:.1f}s")
    time.sleep(t)

# ===================== 主类 =====================

class LinuxDoClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ua(),
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    # ---------- 登录 ----------
    def login(self):
        logger.info("开始登录")
        self.session.get(LOGIN_URL, impersonate="chrome136")

        r = self.session.get(
            CSRF_URL,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": LOGIN_URL,
            },
            impersonate="chrome136",
        )

        csrf = r.json().get("csrf")
        if not csrf:
            logger.error("CSRF 获取失败")
            return False

        r = self.session.post(
            SESSION_URL,
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "https://linux.do",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "login": USERNAME,
                "password": PASSWORD,
                "second_factor_method": "1",
                "timezone": "Asia/Shanghai",
            },
            impersonate="chrome136",
        )

        if r.status_code != 200 or r.json().get("error"):
            logger.error("登录失败")
            return False

        logger.success("登录成功")
        return True

    # ---------- Connect 解析（自适应） ----------
    def parse_connect(self) -> Dict[str, int]:
        r = self.session.get(CONNECT_URL, impersonate="chrome136")
        soup = BeautifulSoup(r.text, "html.parser")

        tasks = {}

        for row in soup.select("table tr"):
            tds = row.select("td")
            if len(tds) < 3:
                continue

            name = tds[0].text.strip().lower()
            cur, need = tds[1].text.strip(), tds[2].text.strip()
            if not cur.isdigit() or not need.isdigit():
                continue

            diff = int(need) - int(cur)
            if diff <= 0:
                continue

            if any(k in name for k in ["read", "view", "topic", "阅读", "浏览"]):
                tasks["read"] = diff
            elif any(k in name for k in ["like", "赞"]):
                tasks["like"] = diff

        logger.success(f"识别 Connect 任务: {tasks}")
        return tasks

    # ---------- 帖子列表 ----------
    def get_topics(self, limit=50) -> List[int]:
        r = self.session.get(LATEST_URL, impersonate="chrome136")
        soup = BeautifulSoup(r.text, "html.parser")

        ids = []
        for a in soup.select("a.title"):
            m = re.search(r"/t/[^/]+/(\d+)", a.get("href", ""))
            if m:
                ids.append(int(m.group(1)))

        random.shuffle(ids)
        return ids[:limit]

    # ---------- 阅读（多段 timings） ----------
    def read_topic(self, topic_id):
        segments = random.randint(*READ_SEGMENTS)
        base = random.uniform(*READ_TIME)
        times = [int(base * random.uniform(0.6, 1.0)) for _ in range(segments)]

        for t in times:
            human_sleep(2, 5)
            r = self.session.post(
                f"https://linux.do/topics/{topic_id}/timings",
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://linux.do/t/{topic_id}",
                },
                data={
                    "timings[0][topic_id]": topic_id,
                    "timings[0][total_time]": t,
                },
                impersonate="chrome136",
            )

            if r.status_code != 200:
                logger.warning(f"timings 失败 topic={topic_id}")
                return False

        logger.success(f"阅读完成 topic={topic_id}")
        return True

    # ---------- 点赞 ----------
    def like_topic(self, topic_id):
        r = self.session.post(
            "https://linux.do/post_actions",
            data={
                "id": topic_id,
                "post_action_type_id": 2,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://linux.do/t/{topic_id}",
            },
            impersonate="chrome136",
        )

        if r.status_code == 200:
            logger.success(f"点赞成功 topic={topic_id}")
            return True

        logger.warning(f"点赞失败 topic={topic_id}")
        return False

    # ---------- 主流程 ----------
    def run(self):
        if not self.login():
            return

        tasks = self.parse_connect()
        if not tasks:
            logger.success("当前无需要补充的 Connect 项目")
            return

        topics = self.get_topics()
        fails = 0

        for tid in topics:
            if tasks.get("read", 0) > 0:
                if self.read_topic(tid):
                    tasks["read"] -= 1
                else:
                    fails += 1

            if tasks.get("like", 0) > 0:
                self.like_topic(tid)

            if all(v <= 0 for v in tasks.values()):
                logger.success("所有 Connect 项目已完成")
                break

            if fails >= MAX_FAIL:
                logger.warning("失败过多，自动降频")
                human_sleep(60, 120)
                fails = 0


# ===================== 入口 =====================

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        logger.error("未设置账号密码")
        exit(1)

    LinuxDoClient().run()
