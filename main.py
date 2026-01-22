# -*- coding: utf-8 -*-
"""
cron: 0 */6 * * *
new Env("Linux.Do 签到 (纯浏览器版)")
"""

import os
import random
import time
import sys
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
# 仅用于通知，不用于登录
from curl_cffi import requests 

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
CONNECT_URL = "https://connect.linux.do/"

class LinuxDoBrowser:
    def __init__(self) -> None:
        # 1. 设置浏览器选项
        co = ChromiumOptions()
        co.headless(True)  # 调试时可设为 False 观看过程
        co.incognito(True) # 无痕模式
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        # 禁用自动化特征，防止被检测
        co.set_argument("--disable-blink-features=AutomationControlled")
        
        # 2. 启动浏览器
        self.browser = Chromium(co)
        self.page = self.browser.latest_tab
        
        # 设置超时时间
        self.page.timeout = 15

    def login(self):
        logger.info("开始浏览器模拟登录...")
        
        try:
            # 1. 访问登录页
            self.page.get(LOGIN_URL)
            
            # 2. 等待输入框加载 (Discourse 的登录框)
            logger.info("等待登录框加载...")
            user_input = self.page.wait.ele("#login-account-name", timeout=15)
            pass_input = self.page.wait.ele("#login-account-password", timeout=5)
            
            if not user_input or not pass_input:
                # 某些情况下可能重定向到了首页，尝试点击首页的“登录”按钮
                logger.warning("未直接进入登录页，尝试查找首页登录按钮")
                login_btn = self.page.ele(".login-button")
                if login_btn:
                    login_btn.click()
                    user_input = self.page.wait.ele("#login-account-name", timeout=10)
                    pass_input = self.page.wait.ele("#login-account-password")
            
            if not user_input:
                logger.error("无法找到用户名输入框")
                return False

            # 3. 输入账号密码
            logger.info("正在输入账号密码...")
            user_input.input(USERNAME)
            time.sleep(0.5)
            pass_input.input(PASSWORD)
            time.sleep(0.5)

            # 4. 点击登录按钮
            login_btn = self.page.ele("#login-button")
            if login_btn:
                login_btn.click()
                logger.info("已点击登录按钮")
            else:
                logger.error("未找到提交按钮")
                return False

            # 5. 验证登录结果
            logger.info("等待登录跳转...")
            # 等待头像出现，或者 current-user 元素
            is_login = False
            for _ in range(20): # 最多等待 20秒
                time.sleep(1)
                if self.page.ele("#current-user") or self.page.ele(".current-user") or self.page.ele("#current-user-avatar"):
                    is_login = True
                    break
                # 检测是否有错误提示
                error_alert = self.page.ele("#modal-alert")
                if error_alert and error_alert.text:
                    logger.error(f"登录界面提示错误: {error_alert.text}")
                    return False
            
            if is_login:
                logger.success("登录成功！")
                return True
            else:
                logger.error("登录超时，未检测到登录状态")
                # self.page.get_screenshot(path="login_timeout.png")
                return False

        except Exception as e:
            logger.error(f"登录过程发生异常: {e}")
            return False

    def click_topic(self):
        logger.info("准备浏览帖子...")
        
        # 确保在首页或 Latest 页面
        if "/latest" not in self.page.url:
            self.page.get("https://linux.do/latest")
        
        if not self.page.wait.ele("#list-area", timeout=15):
            logger.error("列表区域未加载")
            return

        # 模拟滚动加载
        self.page.scroll.down(random.randint(300, 600))
        time.sleep(2)

        # 获取帖子链接
        topic_links = self.page.eles("css:.title.raw-link")
        if not topic_links:
            logger.warning("未找到帖子链接")
            return

        # 提取链接
        urls = []
        for t in topic_links:
            href = t.attr("href")
            if href:
                if not href.startswith("http"):
                    href = HOME_URL.rstrip("/") + href
                urls.append(href)
        
        # 去重
        urls = list(set(urls))
        logger.info(f"发现 {len(urls)} 个帖子")

        # 随机浏览 5-8 个
        count = 0
        target_count = random.randint(5, 8)
        
        for url in random.sample(urls, min(target_count, len(urls))):
            self.browse_one_post(url)
            count += 1
            time.sleep(random.uniform(2, 4))
        
        logger.success(f"浏览完成，共阅读 {count} 篇帖子")

    def browse_one_post(self, url):
        logger.info(f"正在阅读: {url}")
        tab = self.browser.new_tab()
        try:
            tab.get(url)
            # 随机停留
            sleep_time = random.uniform(6, 12)
            
            # 模拟滚动
            for _ in range(3):
                tab.scroll.down(random.randint(200, 500))
                time.sleep(sleep_time / 3)
            
            # 概率点赞 (20%)
            if random.random() < 0.2:
                btn = tab.ele(".discourse-reactions-reaction-button")
                if btn and "点赞" in btn.attr("title", ""):
                    btn.click()
                    logger.info("已点赞")

        except Exception as e:
            logger.warning(f"阅读异常: {e}")
        finally:
            tab.close()

    def print_connect_info(self):
        logger.info("正在获取 Connect 信息...")
        try:
            self.page.get(CONNECT_URL)
            # 等待表格出现
            table = self.page.wait.ele("tag:table", timeout=15)
            
            if not table:
                logger.warning("未找到 Connect 数据表格 (可能需要手动登录 connect.linux.do 或 CF 验证)")
                return

            rows = table.eles("tag:tr")
            data = []
            for r in rows:
                tds = r.eles("tag:td")
                if len(tds) >= 3:
                    data.append([tds[0].text, tds[1].text or "0", tds[2].text or "0"])

            if data:
                print(tabulate(data, headers=["项目", "当前", "要求"], tablefmt="pretty"))
            else:
                logger.warning("Connect 表格为空")

        except Exception as e:
            logger.error(f"获取 Connect 信息失败: {e}")

    def send_notifications(self, browse):
        msg = "✅ Linux.Do 签到脚本执行完毕"
        if browse:
            msg += " (含自动浏览)"

        if GOTIFY_URL and GOTIFY_TOKEN:
            try:
                # 这里仅用于推送，可以用 requests
                requests.post(
                    f"{GOTIFY_URL}/message",
                    params={"token": GOTIFY_TOKEN},
                    json={"title": "LINUX DO", "message": msg, "priority": 1},
                    timeout=10,
                    impersonate="chrome120" # 推送时加上指纹防止 Gotify 端（如果是公网）拦截
                )
                logger.success("通知发送成功")
            except Exception as e:
                logger.error(f"通知发送失败: {e}")

    def run(self):
        if self.login():
            time.sleep(2)
            self.print_connect_info()
            
            if BROWSE_ENABLED:
                self.click_topic()
            
            self.send_notifications(BROWSE_ENABLED)
        
        logger.info("关闭浏览器")
        self.browser.quit()

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        logger.error("请设置环境变量 LINUXDO_USERNAME 和 LINUXDO_PASSWORD")
        sys.exit(1)

    try:
        LinuxDoBrowser().run()
    except Exception as e:
        logger.error(f"主程序崩溃: {e}")
        sys.exit(1)
