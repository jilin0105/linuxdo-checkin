# -*- coding: utf-8 -*-
"""
cron: 0 */6 * * *
new Env("Linux.Do 签到")
"""

import os
import random
import time
import functools
import sys
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from curl_cffi import requests
from bs4 import BeautifulSoup

# --- 配置部分 ---
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

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"
LATEST_URL = "https://linux.do/latest"


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
                    else:
                        logger.warning(
                            f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}"
                        )
                        time.sleep(1)
            return None
        return wrapper
    return decorator


class LinuxDoBrowser:
    def __init__(self) -> None:
        # 1. 设置 DrissionPage 浏览器选项
        co = ChromiumOptions()
        co.headless(True)  # 如需调试可视界面，设为 False
        co.incognito(True) # 无痕模式
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        # 禁用自动化特征，减少被检测概率
        co.set_argument("--disable-blink-features=AutomationControlled")

        # 2. 启动浏览器
        self.browser = Chromium(co)
        self.page = self.browser.latest_tab

        # 3. 【关键】获取浏览器真实的 User-Agent
        # 必须确保 requests 发出的 API 请求和浏览器完全一致，否则 session 会失效
        self.real_ua = self.page.run_js("return navigator.userAgent")
        logger.info(f"同步浏览器 UA: {self.real_ua[:50]}...")

        # 4. 初始化 API 会话
        self.session = requests.Session()
        # 强制覆盖 requests 的 headers
        self.session.headers.update({
            "User-Agent": self.real_ua,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://linux.do",
            "Referer": "https://linux.do/"
        })

    def login(self):
        logger.info("开始 API 登录流程...")

        # 1. 预访问获取基础 Cookie
        try:
            self.session.get(HOME_URL)
        except Exception as e:
            logger.error(f"无法连接主页: {e}")
            return False

        # 2. 获取 CSRF Token
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        
        # 注意：这里不再使用 impersonate 参数，因为我们手动指定了完全一致的 UA
        try:
            resp_csrf = self.session.get(CSRF_URL, headers=headers)
            csrf_token = resp_csrf.json().get("csrf")
        except Exception as e:
            logger.error(f"获取 CSRF 失败: {e}")
            return False

        if not csrf_token:
            logger.error("未获取到 CSRF Token")
            return False

        # 3. 发送登录 POST
        headers.update({
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        })

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        try:
            resp_login = self.session.post(SESSION_URL, data=data, headers=headers)
        except Exception as e:
            logger.error(f"登录请求异常: {e}")
            return False

        if "error" in resp_login.text and "此时无法登录" in resp_login.text:
             logger.error("IP被风控或账号异常，API返回无法登录")
             return False

        resp_json = resp_login.json()
        if resp_json.get("error"):
            logger.error(f"登录失败: {resp_json.get('error')}")
            return False

        logger.success("API 认证成功，正在同步 Cookie...")

        # 4. 【关键】同步 Cookie 到浏览器
        # 必须先让浏览器处于 linux.do 域名下（即使是404或未登录页）才能设置 Cookie
        self.page.get(HOME_URL)

        cookies_list = []
        for k, v in self.session.cookies.get_dict().items():
            cookies_list.append({
                "name": k,
                "value": v,
                "domain": "linux.do", # 强制主域
                "path": "/",          # 强制根路径
                "secure": True
            })
        
        self.page.set.cookies(cookies_list)

        # 5. 跳转验证
        logger.info("导航至 /latest...")
        self.page.get(LATEST_URL)
        
        # 等待页面加载（寻找头像或当前用户标识）
        # Discourse 登录后通常会有 current-user 的 meta 标签或 ID
        is_login = False
        if self.page.wait.ele("@id=current-user", timeout=10):
            is_login = True
        elif self.page.wait.ele(".current-user", timeout=5):
            is_login = True
        elif self.page.ele("#current-user-avatar"):
            is_login = True

        if not is_login:
            # 截图调试（可选）
            # self.page.get_screenshot(path='login_failed.jpg')
            logger.error("Cookie 同步后验证失败：未找到登录标识")
            return False

        logger.success("浏览器登录验证通过！")
        return True

    def click_topic(self):
        logger.info("开始浏览帖子...")
        
        if not self.page.wait.ele("#list-area", timeout=15):
            logger.error("列表区域未加载")
            return False

        # 模拟真人滚动
        self.page.scroll.down(random.randint(200, 500))

        # 获取帖子链接
        # 选择器优化：直接找包含 href 的 title 类
        topic_links = self.page.eles("css:.title.raw-link")
        
        if not topic_links:
            logger.warning("未找到帖子链接")
            return False

        # 去重并筛选
        urls = list(set([t.attr("href") for t in topic_links if t.attr("href")]))
        logger.info(f"当前页面发现 {len(urls)} 个帖子")

        # 随机选取 5-8 个帖子
        selected_urls = random.sample(urls, min(random.randint(5, 8), len(urls)))
        
        for url in selected_urls:
            # 处理相对路径
            if not url.startswith("http"):
                url = HOME_URL.rstrip("/") + url
            self.click_one_topic(url)

        return True

    @retry_decorator()
    def click_one_topic(self, url):
        logger.info(f"正在浏览: {url}")
        
        # 新标签页打开
        tab = self.browser.new_tab()
        try:
            tab.get(url)
            
            # 随机停留 5-10 秒
            sleep_time = random.uniform(5, 10)
            
            # 模拟滚动阅读
            scroll_steps = random.randint(3, 6)
            for _ in range(scroll_steps):
                tab.scroll.down(random.randint(200, 600))
                time.sleep(sleep_time / scroll_steps)

            # 概率点赞 (20%)
            if random.random() < 0.2:
                self.click_like(tab)

        except Exception as e:
            logger.warning(f"浏览帖子异常: {e}")
        finally:
            tab.close()

    def click_like(self, page):
        # Discourse 底部点赞按钮
        try:
            # 查找点赞按钮，注意不要点到已经点赞的（通常有点赞数的 title）
            btn = page.ele(".discourse-reactions-reaction-button")
            if btn and "点赞" in btn.attr("title", ""):
                btn.click()
                logger.info("已点赞")
                time.sleep(1)
        except:
            pass

    def print_connect_info(self):
        logger.info("获取 Connect 信息...")
        try:
            # 使用已登录的浏览器访问
            self.page.get("https://connect.linux.do/")
            
            # 等待表格加载
            table = self.page.wait.ele("tag:table", timeout=10)
            if not table:
                logger.warning("未找到 Connect 数据表格")
                return

            rows = table.eles("tag:tr")
            data = []
            for r in rows:
                tds = r.eles("tag:td")
                if len(tds) >= 3:
                    data.append([tds[0].text, tds[1].text or "0", tds[2].text or "0"])

            print(tabulate(data, headers=["项目", "当前", "要求"], tablefmt="pretty"))
            
        except Exception as e:
            logger.error(f"获取 Connect 信息失败: {e}")

    def send_notifications(self, browse):
        msg = "✅ Linux.Do 签到完成"
        if browse:
            msg += " (含自动浏览)"

        if GOTIFY_URL and GOTIFY_TOKEN:
            try:
                requests.post(
                    f"{GOTIFY_URL}/message",
                    params={"token": GOTIFY_TOKEN},
                    json={"title": "LINUX DO", "message": msg, "priority": 1},
                    timeout=5
                )
                logger.success("推送通知成功")
            except Exception as e:
                logger.error(f"推送通知失败: {e}")

    def run(self):
        if not self.login():
            self.browser.quit()
            return

        # 登录成功后稍作等待
        time.sleep(3)
        
        self.print_connect_info()

        if BROWSE_ENABLED:
            self.click_topic()

        self.send_notifications(BROWSE_ENABLED)
        
        logger.info("任务结束，关闭浏览器")
        self.browser.quit()


if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        logger.error("请设置 LINUXDO_USERNAME 和 LINUXDO_PASSWORD 环境变量")
        sys.exit(1)

    try:
        LinuxDoBrowser().run()
    except Exception as e:
        logger.error(f"程序运行崩溃: {e}")
        sys.exit(1)
