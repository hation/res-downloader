package core

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"res-downloader/core/shared"
	"strconv"
	"strings"
	"sync"
)

type WxFileDecodeResult struct {
	SavePath string
	Message  string
}

type Resource struct {
	mediaMark  sync.Map
	tasks      sync.Map
	resType    map[string]bool
	resTypeMux sync.RWMutex
}

func initResource() *Resource {
	if resourceOnce == nil {
		resourceOnce = &Resource{}
		resourceOnce.resType = resourceOnce.buildResType(globalConfig.MimeMap)
	}
	return resourceOnce
}

func (r *Resource) buildResType(mime map[string]MimeInfo) map[string]bool {
	t := map[string]bool{
		"all": true,
	}

	for _, item := range mime {
		if _, ok := t[item.Type]; !ok {
			t[item.Type] = true
		}
	}

	return t
}

func (r *Resource) mediaIsMarked(key string) bool {
	_, loaded := r.mediaMark.Load(key)
	return loaded
}

func (r *Resource) markMedia(key string) {
	r.mediaMark.Store(key, true)
}

func (r *Resource) getResType(key string) (bool, bool) {
	r.resTypeMux.RLock()
	value, ok := r.resType[key]
	r.resTypeMux.RUnlock()
	return value, ok
}

func (r *Resource) setResType(n []string) {
	r.resTypeMux.Lock()
	for key := range r.resType {
		r.resType[key] = false
	}

	for _, value := range n {
		if _, ok := r.resType[value]; ok {
			r.resType[value] = true
		}
	}
	r.resTypeMux.Unlock()
}

func (r *Resource) clear() {
	r.mediaMark.Clear()
}

func (r *Resource) delete(sign string) {
	r.mediaMark.Delete(sign)
}

func (r *Resource) cancel(id string) error {
	if d, ok := r.tasks.Load(id); ok {
		d.(*FileDownloader).Cancel()
		r.tasks.Delete(id) // 可选：取消后清理
		return nil
	}
	return errors.New("task not found")
}

func (r *Resource) download(mediaInfo shared.MediaInfo, decodeStr string) {
	if globalConfig.SaveDirectory == "" {
		return
	}
	go func(mediaInfo shared.MediaInfo) {
		rawUrl := mediaInfo.Url
		fileName := shared.Md5(rawUrl)

		if v := shared.GetFileNameFromURL(rawUrl); v != "" {
			fileName = v
		}

		if mediaInfo.Description != "" {
			fileName = regexp.MustCompile(`[^\w\p{Han}]`).ReplaceAllString(mediaInfo.Description, "")
			fileLen := globalConfig.FilenameLen
			if fileLen <= 0 {
				fileLen = 10
			}

			runes := []rune(fileName)
			if len(runes) > fileLen {
				fileName = string(runes[:fileLen])
			}
		}

		if globalConfig.FilenameTime {
			mediaInfo.SavePath = filepath.Join(globalConfig.SaveDirectory, fileName+"_"+shared.GetCurrentDateTimeFormatted())
		} else {
			mediaInfo.SavePath = filepath.Join(globalConfig.SaveDirectory, fileName)
		}

		if !strings.HasSuffix(mediaInfo.SavePath, mediaInfo.Suffix) {
			mediaInfo.SavePath = mediaInfo.SavePath + mediaInfo.Suffix
		}

		if strings.Contains(rawUrl, "qq.com") {
			if globalConfig.Quality == 1 &&
				strings.Contains(rawUrl, "encfilekey=") &&
				strings.Contains(rawUrl, "token=") {
				parseUrl, err := url.Parse(rawUrl)
				queryParams := parseUrl.Query()
				if err == nil && queryParams.Has("encfilekey") && queryParams.Has("token") {
					rawUrl = parseUrl.Scheme + "://" + parseUrl.Host + "/" + parseUrl.Path +
						"?encfilekey=" + queryParams.Get("encfilekey") +
						"&token=" + queryParams.Get("token")
				}
			} else if globalConfig.Quality > 1 && mediaInfo.OtherData["wx_file_formats"] != "" {
				format := strings.Split(mediaInfo.OtherData["wx_file_formats"], "#")
				qualityMap := []string{
					format[0],
					format[len(format)/2],
					format[len(format)-1],
				}
				rawUrl += "&X-snsvideoflag=" + qualityMap[globalConfig.Quality-2]
			}
		}

		headers, _ := r.parseHeaders(mediaInfo)

		downloader := NewFileDownloader(rawUrl, mediaInfo.SavePath, globalConfig.TaskNumber, headers)
		downloader.progressCallback = func(totalDownloaded, totalSize float64, taskID int, taskProgress float64) {
			r.progressEventsEmit(mediaInfo, strconv.Itoa(int(totalDownloaded*100/totalSize))+"%", shared.DownloadStatusRunning)
		}
		r.tasks.Store(mediaInfo.Id, downloader)
		err := downloader.Start()
		mediaInfo.SavePath = downloader.FileName
		if err != nil {
			if !strings.Contains(err.Error(), "cancelled") {
				r.progressEventsEmit(mediaInfo, err.Error())
			}
			return
		}
		if decodeStr != "" {
			r.progressEventsEmit(mediaInfo, "decrypting in progress", shared.DownloadStatusRunning)
			if err := r.decodeWxFile(mediaInfo.SavePath, decodeStr); err != nil {
				r.progressEventsEmit(mediaInfo, "decryption error: "+err.Error())
				return
			}
		}
		r.progressEventsEmit(mediaInfo, "complete", shared.DownloadStatusDone)
	}(mediaInfo)
}

func (r *Resource) parseHeaders(mediaInfo shared.MediaInfo) (map[string]string, error) {
	headers := make(map[string]string)

	if hh, ok := mediaInfo.OtherData["headers"]; ok {
		var tempHeaders map[string][]string
		if err := json.Unmarshal([]byte(hh), &tempHeaders); err != nil {
			return headers, fmt.Errorf("parse headers JSON err: %v", err)
		}

		for key, values := range tempHeaders {
			if len(values) > 0 {
				headers[key] = values[0]
			}
		}
	}

	return headers, nil
}

func (r *Resource) wxFileDecode(mediaInfo shared.MediaInfo, fileName, decodeStr string) (string, error) {
	sourceFile, err := os.Open(fileName)
	if err != nil {
		return "", err
	}
	defer sourceFile.Close()
	mediaInfo.SavePath = strings.ReplaceAll(fileName, ".mp4", "_decrypt.mp4")

	destinationFile, err := os.Create(mediaInfo.SavePath)
	if err != nil {
		return "", err
	}
	defer destinationFile.Close()

	_, err = io.Copy(destinationFile, sourceFile)
	if err != nil {
		return "", err
	}
	err = r.decodeWxFile(mediaInfo.SavePath, decodeStr)
	if err != nil {
		return "", err
	}
	return mediaInfo.SavePath, nil
}

func (r *Resource) progressEventsEmit(mediaInfo shared.MediaInfo, args ...string) {
	Status := shared.DownloadStatusError
	Message := "ok"

	if len(args) > 0 {
		Message = args[0]
	}
	if len(args) > 1 {
		Status = args[1]
	}

	httpServerOnce.send("downloadProgress", map[string]interface{}{
		"Id":       mediaInfo.Id,
		"Status":   Status,
		"SavePath": mediaInfo.SavePath,
		"Message":  Message,
	})
	return
}

func (r *Resource) decodeWxFile(fileName, decodeStr string) error {
	decodeStr = strings.TrimSpace(decodeStr)
	decodedBytes, err := base64.StdEncoding.DecodeString(decodeStr)
	if err != nil {
		// 前端传来的是 base64 编码的 ISAAC64 密钥
		// 无头模式下用户传的是原始 decodeKey（纯数字），需要通过 WASM 生成密钥
		decodedBytes, err = r.generateWxDecryptKey(decodeStr)
		if err != nil {
			return fmt.Errorf("生成解密密钥失败: %v", err)
		}
	}
	file, err := os.OpenFile(fileName, os.O_RDWR, 0644)
	if err != nil {
		return err
	}
	defer file.Close()

	byteCount := len(decodedBytes)
	fileBytes := make([]byte, byteCount)
	n, err := file.Read(fileBytes)
	if err != nil && err != io.EOF {
		return err
	}

	if n < byteCount {
		byteCount = n
	}

	xorResult := make([]byte, byteCount)
	for i := 0; i < byteCount; i++ {
		xorResult[i] = decodedBytes[i] ^ fileBytes[i]
	}
	_, err = file.Seek(0, 0)
	if err != nil {
		return err
	}

	_, err = file.Write(xorResult)
	if err != nil {
		return err
	}
	return nil
}

// generateWxDecryptKey 通过 Node.js 调用 WASM 模块生成微信视频解密密钥（ISAAC64）
func (r *Resource) generateWxDecryptKey(decodeKey string) ([]byte, error) {
	// 查找脚本路径：优先在可执行文件同级目录，其次在上一级目录
	scriptPaths := []string{
		"scripts/gen_decrypt_key.js",
		"../scripts/gen_decrypt_key.js",
	}
	var scriptPath string
	for _, p := range scriptPaths {
		if _, err := os.Stat(p); err == nil {
			scriptPath = p
			break
		}
	}
	if scriptPath == "" {
		return nil, fmt.Errorf("未找到 gen_decrypt_key.js 脚本")
	}

	cmd := exec.Command("node", "--no-deprecation", scriptPath, decodeKey)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("%s", string(exitErr.Stderr))
		}
		return nil, err
	}

	keyBase64 := strings.TrimSpace(string(output))
	decodedBytes, err := base64.StdEncoding.DecodeString(keyBase64)
	if err != nil {
		return nil, fmt.Errorf("密钥 base64 解码失败: %v", err)
	}
	return decodedBytes, nil
}
