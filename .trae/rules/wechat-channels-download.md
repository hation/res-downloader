# 微信视频号监测下载流程（无头模式）

当用户要求"监测视频并下载"、"抓视频号视频"、"下载微信视频"等时，按此流程执行。

## 前置条件（已完成，无需重复）
- Go + Wails v2 环境已配置（`~/go/bin/wails`）
- macOS 系统代理启用已修复（`core/system_darwin.go` 增加 `-setwebproxystate on`）
- ISAAC64 解密密钥生成已修复（`core/resource.go` + `scripts/gen_decrypt_key.js`）
- CA 证书已安装（之前装过 release 版）

## 执行步骤

### 方式 A：按标题关键词自动监测下载（推荐）

当用户提供视频标题关键词时，直接使用自动化脚本：

```bash
cd /Users/xingan/Documents/software/aiengine/res-downloader
python3 scripts/monitor_download.py "标题关键词" [--match contains|prefix|exact] [--max N]
```

参数说明：
- `标题关键词` — 要匹配的视频标题片段
- `--match` — 匹配模式：`contains`(包含,默认) / `prefix`(前缀) / `exact`(完全匹配)
- `--max` — 最多下载几个匹配视频（默认 1）

脚本会自动完成：启动服务 → 开代理 → 设 video 类型 → 监听事件 → 匹配标题 → 下载。

**使用流程：**
1. 运行脚本
2. 脚本提示后，让用户**完全退出微信(Cmd+Q)后重新打开**
3. 用户在微信视频号中浏览视频
4. 脚本自动匹配并下载，达到目标数量后退出

### 方式 B：手动流程

### 1. 编译并启动无头服务
```bash
cd /Users/xingan/Documents/software/aiengine/res-downloader
export PATH="$PATH:$(go env GOPATH)/bin"
export GOPROXY=https://goproxy.cn,direct
go build -o res-downloader-cli .
./res-downloader-cli --headless
```
后台运行，等待输出 `HTTP API + proxy listening on http://127.0.0.1:8899`。

### 2. 开启系统代理
```bash
curl -s -X POST http://127.0.0.1:8899/api/proxy-open
```
验证：`networksetup -getwebproxy "Wi-Fi"` 应显示 `Enabled: Yes`。

**重要**：如果微信已在运行，需让用户完全退出微信（Cmd+Q）后重开，让微信读取系统代理设置。

### 3. 设置抓取类型为 video
```bash
curl -s -X POST http://127.0.0.1:8899/api/set-type -H "Content-Type: application/json" -d '{"type":"video"}'
```

### 4. 等待用户刷视频号
让用户在微信里播放视频号视频。监控服务日志中的 `newResources` 事件：
```
[event] {"type":"newResources","data":{"Id":"...","Url":"...","DecodeKey":"...","Description":"..."}}
```

### 5. 下载视频（自动解密）
从事件中提取 Id、Url、DecodeKey，调用下载接口：
```bash
curl -X POST http://127.0.0.1:8899/api/download \
  -H "Content-Type: application/json" \
  -d '{"Id":"<事件Id>","Url":"<事件Url>","Name":"<自定义名称>","Type":"video","Mime":"video/mp4","Suffix":".mp4","DecodeStr":"<事件DecodeKey>"}'
```
下载完成后自动用 ISAAC64 密钥 XOR 解密。进度通过 `downloadProgress` 事件输出。

### 6. 退出
`Ctrl+C` 停止服务（自动关闭系统代理）。

## 关键注意事项
1. **必须先开代理再开微信**（或重启微信），否则微信不走代理，抓不到
2. **DecodeKey 必须传**，否则下载的是加密文件无法播放
3. 下载目录：`/Users/xingan/Documents/video/`
4. 解密后的文件以 `_decrypt.mp4` 结尾
5. 微信视频号视频用 ISAAC64 生成的密钥流做 XOR 解密，密钥生成通过 `scripts/gen_decrypt_key.js` 调用 WASM 模块

## 常用 API
| 操作 | 方法 | 端点 |
|------|------|------|
| 开启代理 | POST | /api/proxy-open |
| 关闭代理 | POST | /api/proxy-unset |
| 代理状态 | GET | /api/is-proxy |
| 设置类型 | POST | /api/set-type `{"type":"video"}` |
| 下载 | POST | /api/download |
| 解密已有文件 | POST | /api/wx-file-decode |
| 查看配置 | GET | /api/get-config |

## 解密原理
微信视频号视频用 XOR 加密，密钥不是直接用 decodeKey，而是：
1. 用 decodeKey 作为种子，通过 ISAAC64 伪随机数生成器生成 131072 字节密钥流
2. 反转字节数组
3. 用密钥流 XOR 视频文件开头
前端通过 WASM 实现 ISAAC64，无头模式下后端通过 Node.js 调用同一个 WASM 模块生成密钥。
