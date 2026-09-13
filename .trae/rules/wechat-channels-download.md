# 微信视频号监测下载流程（无头模式）

当用户说"抓 XXX 视频"、"下载标题含 XXX 的视频"、"监测 XXX"时，直接执行一键脚本。

## 前置条件（已完成，无需重复）
- Go + Wails v2 环境已配置（`~/go/bin/wails`）
- macOS 系统代理启用已修复（`core/system_darwin.go`）
- ISAAC64 解密密钥生成已修复（`core/resource.go` + `scripts/gen_decrypt_key.js`）
- CA 证书已安装

## 一键使用流程（唯一推荐方式）

### 单个关键词
```bash
cd /Users/xingan/Documents/software/aiengine/res-downloader
python3 scripts/monitor_download.py "标题关键词"
```

### 批量多关键词
```bash
# 方式1：命令行传多个
python3 scripts/monitor_download.py "关键词1" "关键词2" "关键词3"

# 方式2：写入关键词文件（支持热更新）
# 把关键词追加到 .trae/watch_keywords.txt，每行一个
# 然后运行：
python3 scripts/monitor_download.py
```

### 监测过程中追加新关键词（无需重启）
脚本每 5 秒重新读取 `.trae/watch_keywords.txt`。监测过程中用户给新关键词时，直接追加到该文件即可，脚本会自动识别。

**脚本自动完成全部流程：**
1. 启动无头服务（端口 8899）
2. 开启系统代理
3. 设置抓取类型为 video
4. 监听 `newResources` 事件
5. 标题匹配（任一关键词）→ 触发下载（自动 ISAAC64 解密）
6. 所有关键词下载完成 → 关闭代理 → 停止服务 → 退出

**超时机制：**
- 监听阶段：5 分钟内无新视频事件 → 自动退出（不浪费资源）
- 下载阶段：触发后最多等 2 分钟 → 超时也退出

**用户操作：**
1. 我运行脚本（写入关键词到文件）
2. 提醒用户**完全退出微信(Cmd+Q)后重新打开**
3. 用户在微信视频号里刷到目标视频并播放
4. 脚本自动下载完成后退出

**下载目录：** `/Users/xingan/Documents/video/`

**可选参数：**
- `--match contains|prefix|exact` — 匹配模式（默认 contains）
- `--max N` — 每个关键词最多下载几个（默认 1）

**关键词文件：** `.trae/watch_keywords.txt`

## 关键注意事项
1. **必须先开代理再开微信**（或重启微信），否则微信不走代理，抓不到
2. **关键词不要太精确**——视频标题常有空格、emoji、话题标签，用关键词片段即可
3. 解密后的文件直接是 `.mp4`（下载接口已自动解密）
4. 微信视频号视频用 ISAAC64 生成 131072 字节密钥流做 XOR 解密，密钥生成通过 `scripts/gen_decrypt_key.js` 调用 WASM 模块

## 常用 API（手动调试用）
| 操作 | 方法 | 端点 |
|------|------|------|
| 开启代理 | POST | /api/proxy-open |
| 关闭代理 | POST | /api/proxy-unset |
| 代理状态 | GET | /api/is-proxy |
| 设置类型 | POST | /api/set-type `{"type":"video"}` |
| 下载 | POST | /api/download |
| 查看配置 | GET | /api/get-config |
