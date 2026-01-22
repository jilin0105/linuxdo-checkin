"""
cron: 0 */6 * * *
new Env("Linux.Do 签到")
"""

import os
import random
import time
import functools
import sys
import re
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from curl_cffi import requests
from bs4 import BeautifulSoup


def retry_decorator(retries=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"函数 {func.__name__} 最终执行失败: {str(e)}")
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}"
                    )
                    time.sleep(1)
            return None

        return wrapper

    return decorator


os.environ.pop("DISPLAY", None)
os.environ.pop("DYLD_LIBRARY_PATH", None)

USERNAME = os.environ.get("LINUXDO_USERNAME") or os.environ.get("USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD") or os.environ.get("PASSWORD")

BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in [
    "false",
    "0",
    "off",
]

GOTIFY_URL = os.environ.get("GOTIFY_URL")
GOTIFY_TOKEN = os.environ.get("GOTIFY_TOKEN")
SC3_PUSH_KEY = os.environ.get("SC3_PUSH_KEY")

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"
LATEST_URL = "https://linux.do/latest"


class LinuxDoBrowser:
    def __init__(self) -> None:
        from sys import platform

        if platform.startswith("linux"):
            platformIdentifier = "X11; Linux x86_64"
        elif platform == "darwin":
            platformIdentifier = "Macintosh; Intel Mac OS X 10_15_7"
        else:
            platformIdentifier = "Windows NT 10.0; Win64; x64"

        co = (
            ChromiumOptions()
            .headless(True)
            .incognito(True)
            .set_argument("--no-sandbox")
        )

        co.set_user_agent(
            f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        self.browser = Chromium(co)
        self.page = self.browser.new_tab()

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )

    def login(self):
        logger.info("开始登录")

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }

        resp_csrf = self.session.get(CSRF_URL, headers=headers, impersonate="chrome136")
        csrf_token = resp_csrf.json().get("csrf")

        if not csrf_token:
            logger.error("未获取到 CSRF Token")
            return False

        headers["X-CSRF-Token"] = csrf_token
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["Origin"] = "https://linux.do"

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        resp_login = self.session.post(
            SESSION_URL, data=data, headers=headers, impersonate="chrome136"
        )

        if resp_login.status_code != 200:
            logger.error("登录失败")
            return False

        if resp_login.json().get("error"):
            logger.error(f"登录错误: {resp_login.json().get('error')}")
            return False

        logger.success("登录成功")

        # 同步 cookies
        cookies = []
        for k, v in self.session.cookies.get_dict().items():
            cookies.append(
                {"name": k, "value": v, "domain": ".linux.do", "path": "/"}
            )
        self.page.set.cookies(cookies)

        # 🔥 关键修复：进入 latest
        logger.info("跳转至 /latest 页面")
        self.page.get(LATEST_URL)

        if not self.page.wait.ele("@id=list-area", timeout=15):
            logger.error("list-area 未出现，页面结构异常")
            return False

        logger.success("页面验证成功")
        return True

    def click_topic(self):
        logger.info("等待主题列表")

        if not self.page.wait.ele("@id=list-area", timeout=15):
            logger.error("找不到 list-area")
            return False

        topic_list = self.page.ele("@id=list-area").eles(".:title")

        if not topic_list:
            logger.error("未获取到任何主题")
            return False

        logger.info(f"获取到 {len(topic_list)} 个主题")

        for topic in random.sample(topic_list, min(10, len(topic_list))):
            self.click_one_topic(topic.attr("href"))

        return True

    @retry_decorator()
    def click_one_topic(self, url):
        p = self.browser.new_tab()
        p.get(url)

        if random.random() < 0.3:
            self.click_like(p)

        self.browse_post(p)
        p.close()

    def browse_post(self, page):
        for _ in range(10):
            page.run_js(f"window.scrollBy(0, {random.randint(500, 700)})")
            time.sleep(random.uniform(2, 4))

    def click_like(self, page):
        btn = page.ele(".discourse-reactions-reaction-button")
        if btn:
            btn.click()
            time.sleep(random.uniform(1, 2))

    def print_connect_info(self):
        resp = self.session.get("https://connect.linux.do/", impersonate="chrome136")
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tr")
        data = []

        for r in rows:
            tds = r.select("td")
            if len(tds) >= 3:
                data.append([tds[0].text, tds[1].text or "0", tds[2].text or "0"])

        print(tabulate(data, headers=["项目", "当前", "要求"], tablefmt="pretty"))

    def send_notifications(self, browse):
        msg = "✅ Linux.Do 登录成功"
        if browse:
            msg += " + 浏览完成"

        if GOTIFY_URL and GOTIFY_TOKEN:
            requests.post(
                f"{GOTIFY_URL}/message",
                params={"token": GOTIFY_TOKEN},
                json={"title": "LINUX DO", "message": msg, "priority": 1},
            )

    def run(self):
        if not self.login():
            return

        self.print_connect_info()

        if BROWSE_ENABLED:
            self.click_topic()

        self.send_notifications(BROWSE_ENABLED)
        self.page.close()
        self.browser.quit()


if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("Please set USERNAME and PASSWORD")
        sys.exit(1)

    LinuxDoBrowser().run()
