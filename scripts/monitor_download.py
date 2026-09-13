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


def main():
    parser = argparse.ArgumentParser(description="微信视频号监测下载")
    parser.add_argument("keyword", help="标题关键词")
    parser.add_argument("--match", choices=["contains", "prefix", "exact"],
                        default="contains", help="匹配模式（默认 contains）")
    parser.add_argument("--max", type=int, default=1,
                        help="最多下载几个匹配视频（默认 1）")
    args = parser.parse_args()

    print(f"[监测] 关键词: {args.keyword}")
    print(f"[监测] 匹配模式: {args.match}")
    print(f"[监测] 目标数量: {args.max}")
    print()

    # 1. 启动服务
    if not start_server():
        sys.exit(1)

    # 2. 开代理 + 设置类型
    open_proxy()
    set_type()

    print()
    print(f"[监测] 现在请在微信视频号中浏览视频...")
    print(f"[监测] 匹配到标题含「{args.keyword}」的视频将自动下载")
    print("[监测] 按 Ctrl+C 退出")
    print()

    downloaded_ids = set()
    match_count = 0

    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            f.seek(0, 2)  # 跳到文件末尾（日志已在启动时清空）
            while match_count < args.max:
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
                if evt.get("type") != "newResources":
                    continue
                data = evt.get("data", {})
                res_id = data.get("Id", "")
                desc = data.get("Description", "")
                if not res_id or res_id in downloaded_ids:
                    continue
                if match_title(desc, args.keyword, args.match):
                    print(f"[匹配] {desc}")
                    print(f"[下载] 触发下载: {data.get('Url', '')[:80]}...")
                    result = download_resource(data)
                    if result:
                        print(f"[下载] 响应: {result[:200]}")
                    downloaded_ids.add(res_id)
                    match_count += 1
                    print(f"[完成] 已下载 {match_count}/{args.max}")
                    print()
    except KeyboardInterrupt:
        print("\n[监测] 用户中断，退出")
    finally:
        print(f"[总结] 共下载 {match_count} 个视频")
        print(f"[总结] 文件保存在: {DOWNLOAD_DIR}")


if __name__ == "__main__":
    main()
