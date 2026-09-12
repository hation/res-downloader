package core

import (
	"fmt"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

func DialogErr(message string) {
	if appOnce == nil || appOnce.ctx == nil {
		fmt.Println("[Error]", message)
		return
	}
	_, _ = runtime.MessageDialog(appOnce.ctx, runtime.MessageDialogOptions{
		Type:          runtime.ErrorDialog,
		Title:         "Error",
		Message:       message,
		DefaultButton: "Cancel",
	})
}
