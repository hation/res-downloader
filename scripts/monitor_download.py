#!/usr/bin/env python3
"""
微信视频号监测下载脚本（无头模式）

用法:
  python3 scripts/monitor_download.py "标题关键词" [--match contains|prefix|exact]

功能:
  1. 启动无头服务（如果未运行）
  2. 开启系统代理
  3. 设置抓取类型为 video
  4. 实时监测 newResources 事件
  5. 标题匹配则自动下载（自动解密）

匹配模式:
  contains  - 标题包含关键词（默认）
  prefix    - 标题以关键词开头
  exact     - 标题完全匹配
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# 禁用输出缓冲，确保日志实时可见
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

API_BASE = "http://127.0.0.1:8899"
PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_DIR / "resdl_headless.log"
CLI_BIN = PROJECT_DIR / "res-downloader-cli"
DOWNLOAD_DIR = Path.home() / "Documents" / "video"
KEYWORDS_FILE = PROJECT_DIR / ".trae" / "watch_keywords.txt"


def api_post(path, data=None):
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()
    except Exception as e:
        return None


def api_get(path):
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=5) as resp:
            return resp.read().decode()
    except Exception:
        return None


def is_server_running():
    return api_get("/api/app-info") is not None


def start_server():
    if is_server_running():
        print("[INFO] 检测到已有服务运行，重启以接管日志输出...")
        # 关闭已有服务，确保由本脚本启动（输出重定向到日志文件）
        api_post("/api/proxy-unset")
        # 找到并杀死占用8899端口的进程
        try:
            result = subprocess.run(
                ["lsof", "-ti", ":8899"],
                capture_output=True, text=True
            )
            for pid in result.stdout.strip().split():
                os.kill(int(pid), 15)
                print(f"[INFO] 已终止旧服务进程 {pid}")
            time.sleep(1)
        except Exception:
            pass

    if not CLI_BIN.exists():
        print("[ERROR] 未找到 res-downloader-cli，请先执行 go build -o res-downloader-cli .")
        return False
    print("[INFO] 启动无头服务...")
    # 清空日志文件，只保留本次运行的事件
    log_fp = open(LOG_FILE, "w")
    subprocess.Popen([str(CLI_BIN), "--headless"],
                     stdout=log_fp, stderr=subprocess.STDOUT,
                     cwd=str(PROJECT_DIR))
    for _ in range(30):
        time.sleep(0.5)
        if is_server_running():
            print("[INFO] 无头服务已启动")
            return True
    print("[ERROR] 服务启动超时")
    return False


def open_proxy():
    api_post("/api/proxy-open")
    time.sleep(1)
    print("[INFO] 系统代理已开启")
    print("[!!!] 请完全退出微信(Cmd+Q)后重新打开，让微信走代理")


def set_type():
    api_post("/api/set-type", {"type": "video"})
    print("[INFO] 抓取类型已设为 video")


def download_resource(res):
    payload = {
        "Id": res.get("Id", ""),
        "Url": res.get("Url", ""),
        "Name": res.get("Description", res.get("Id", "video"))[:50],
        "Type": "video",
        "Mime": "video/mp4",
        "Suffix": ".mp4",
        "DecodeStr": res.get("DecodeKey", ""),
    }
    result = api_post("/api/download", payload)
    return result


def match_title(description, keyword, mode):
    if not description:
        return False
    desc = str(description)
    if mode == "exact":
        return desc == keyword
    elif mode == "prefix":
        return desc.startswith(keyword)
    else:  # contains
        return keyword in desc


def load_keywords(keyword_args=None):
    """加载关键词列表：优先命令行参数，否则从关键词文件读取。
    返回 dict: {关键词: 已下载数量}"""
    keywords = {}
    if keyword_args:
        for kw in keyword_args:
            kw = kw.strip()
            if kw:
                keywords[kw] = 0
    if KEYWORDS_FILE.exists():
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                kw = line.strip()
                if kw and not kw.startswith("#"):
                    if kw not in keywords:
                        keywords[kw] = 0
    return keywords


def reload_keywords(current_keywords):
    """热更新：从关键词文件读取新增的关键词。返回是否有新增。"""
    if not KEYWORDS_FILE.exists():
        return False
    new_added = False
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            kw = line.strip()
            if kw and not kw.startswith("#") and kw not in current_keywords:
                current_keywords[kw] = 0
                new_added = True
                print(f"[新增] 检测到新关键词: {kw}")
    return new_added


def all_done(keywords, max_per_keyword):
    """检查是否所有关键词都已达到目标下载数量。"""
    return all(count >= max_per_keyword for count in keywords.values())


def main():
    parser = argparse.ArgumentParser(description="微信视频号监测下载（支持多关键词批量）")
    parser.add_argument("keywords", nargs="*", help="标题关键词（可传多个，也可写入 .trae/watch_keywords.txt）")
    parser.add_argument("--match", choices=["contains", "prefix", "exact"],
                        default="contains", help="匹配模式（默认 contains）")
    parser.add_argument("--max", type=int, default=1,
                        help="每个关键词最多下载几个（默认 1）")
    args = parser.parse_args()

    # 加载关键词（命令行 + 关键词文件）
    keywords = load_keywords(args.keywords)
    if not keywords:
        print("[ERROR] 未指定关键词。用法:")
        print("  python3 scripts/monitor_download.py 关键词1 关键词2 ...")
        print(f"  或在 {KEYWORDS_FILE} 中每行写一个关键词")
        sys.exit(1)

    print(f"[监测] 匹配模式: {args.match}")
    print(f"[监测] 每个关键词目标数量: {args.max}")
    print(f"[监测] 关键词列表:")
    for kw in keywords:
        print(f"  - {kw}")
    print()
    print(f"[监测] 关键词文件（支持热更新）: {KEYWORDS_FILE}")
    print()

    # 1. 启动服务
    if not start_server():
        sys.exit(1)

    # 2. 开代理 + 设置类型
    open_proxy()
    set_type()

    print()
    print("[监测] 现在请在微信视频号中浏览视频...")
    print(f"[监测] 匹配到以上任一关键词的视频将自动下载")
    print("[监测] 可在监测过程中向关键词文件追加新关键词，无需重启")
    print("[监测] 按 Ctrl+C 退出")
    print()

    downloaded_ids = set()
    match_count = 0
    last_event_time = time.time()
    last_reload_time = time.time()
    MONITOR_TIMEOUT = 300    # 监听阶段：5分钟无新事件则退出
    DOWNLOAD_TIMEOUT = 120   # 下载阶段：最多等2分钟
    RELOAD_INTERVAL = 5      # 每5秒重新加载关键词文件

    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            f.seek(0, 2)  # 跳到文件末尾
            while not all_done(keywords, args.max):
                # 检查监听超时
                if time.time() - last_event_time > MONITOR_TIMEOUT:
                    print(f"\n[超时] {MONITOR_TIMEOUT}秒内无新视频事件，退出")
                    break

                # 定期热更新关键词
                if time.time() - last_reload_time > RELOAD_INTERVAL:
                    reload_keywords(keywords)
                    last_reload_time = time.time()

                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue
                line = line.strip()
                if not line.startswith("[event]"):
                    continue
                try:
                    evt = json.loads(line[len("[event] "):])
                except json.JSONDecodeError:
                    continue

                evt_type = evt.get("type")
                if evt_type == "newResources":
                    last_event_time = time.time()
                    data = evt.get("data", {})
                    res_id = data.get("Id", "")
                    desc = data.get("Description", "")
                    if not res_id or res_id in downloaded_ids:
                        continue

                    # 检查是否匹配任意关键词（且该关键词未达目标数量）
                    matched_kw = None
                    for kw, count in keywords.items():
                        if count < args.max and match_title(desc, kw, args.match):
                            matched_kw = kw
                            break

                    if matched_kw:
                        print(f"[匹配] 关键词「{matched_kw}」-> {desc}")
                        print(f"[下载] 触发下载: {data.get('Url', '')[:80]}...")
                        result = download_resource(data)
                        if result:
                            print(f"[下载] 响应: {result[:200]}")
                        downloaded_ids.add(res_id)
                        match_count += 1
                        keywords[matched_kw] += 1
                        # 等待下载完成
                        print(f"[下载] 等待下载完成...")
                        download_done = False
                        wait_start = time.time()
                        while not download_done and time.time() - wait_start < DOWNLOAD_TIMEOUT:
                            dline = f.readline()
                            if not dline:
                                time.sleep(0.3)
                                continue
                            dline = dline.strip()
                            if not dline.startswith("[event]"):
                                continue
                            try:
                                devt = json.loads(dline[len("[event] "):])
                            except json.JSONDecodeError:
                                continue
                            if devt.get("type") == "downloadProgress":
                                evt_data = devt.get("data", {})
                                if evt_data.get("Id") == res_id:
                                    save_path = evt_data.get("SavePath", "")
                                    if save_path:
                                        print(f"[完成] 下载完成: {save_path}")
                                        download_done = True
                        if not download_done:
                            print(f"[完成] 下载已触发（{DOWNLOAD_TIMEOUT}秒超时，可能仍在后台进行）")
                        last_event_time = time.time()
                        print(f"[进度] 关键词「{matched_kw}」已下载 {keywords[matched_kw]}/{args.max}")
                        print(f"[进度] 总计已下载 {match_count} 个视频")
                        remaining = [kw for kw, c in keywords.items() if c < args.max]
                        if remaining:
                            print(f"[进度] 剩余待抓: {', '.join(remaining)}")
                        print()
    except KeyboardInterrupt:
        print("\n[监测] 用户中断，退出")
    finally:
        # 关闭系统代理
        api_post("/api/proxy-unset")
        time.sleep(0.5)
        subprocess.run(["networksetup", "-setwebproxystate", "Wi-Fi", "off"],
                       capture_output=True)
        subprocess.run(["networksetup", "-setsecurewebproxystate", "Wi-Fi", "off"],
                       capture_output=True)
        print("[INFO] 系统代理已关闭")
        # 停止无头服务
        try:
            result = subprocess.run(["lsof", "-ti", ":8899"],
                                    capture_output=True, text=True)
            for pid in result.stdout.strip().split():
                os.kill(int(pid), 15)
                print(f"[INFO] 已停止服务进程 {pid}")
        except Exception:
            pass
        print(f"[总结] 共下载 {match_count} 个视频")
        print(f"[总结] 文件保存在: {DOWNLOAD_DIR}")


if __name__ == "__main__":
    main()
