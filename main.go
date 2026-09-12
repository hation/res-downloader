package main

import (
	"context"
	"embed"
	"flag"
	"fmt"
	"github.com/wailsapp/wails/v2/pkg/menu"
	"github.com/wailsapp/wails/v2/pkg/options/linux"
	"github.com/wailsapp/wails/v2/pkg/options/mac"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
	"log"
	"os"
	"os/signal"
	"res-downloader/core"
	"runtime"
	"syscall"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

//go:embed build/appicon.png
var icon []byte

//go:embed wails.json
var wailsJson string

func main() {
	headless := flag.Bool("headless", false, "run without GUI (HTTP API only)")
	flag.Parse()

	// Create an instance of the app structure
	app := core.GetApp(assets, wailsJson)

	if *headless {
		runHeadless(app)
		return
	}

	bind := core.NewBind()
	isMac := runtime.GOOS == "darwin"
	// menu
	appMenu := menu.NewMenu()
	if isMac {
		appMenu.Append(menu.AppMenu())
		appMenu.Append(menu.EditMenu())
		appMenu.Append(menu.WindowMenu())
	}

	// Create application with options
	err := wails.Run(&options.App{
		Title:                    app.AppName,
		Width:                    1280,
		MinWidth:                 960,
		Height:                   800,
		MinHeight:                600,
		Frameless:                !isMac,
		Menu:                     appMenu,
		EnableDefaultContextMenu: true,
		AssetServer: &assetserver.Options{
			Assets:     assets,
			Middleware: core.Middleware,
		},
		BackgroundColour: &options.RGBA{R: 27, G: 38, B: 54, A: 1},
		OnStartup: func(ctx context.Context) {
			logo := `
	 _ __    ___   ___            __| |   ___   __      __  _ __   | |   ___     __ _     __| |   ___   _ __
	| '__|  / _ \ / __|  _____   / _· |  / _ \  \ \ /\ / / | '_ \  | |  / _ \   / _· |   / _· |  / _ \ | ·__|
	| |    |  __/ \__ \ |_____| | (_| | | (_) |  \ V  V /  | | | | | | | (_) | | (_| |  | (_| | |  __/ | |
	|_|     \___| |___/          \__,_|  \___/    \_/\_/   |_| |_| |_|  \___/   \__ ,_|  \__,_|  \___| |_|`

			log.Println(logo)
			fmt.Println("version:", app.Version)
			fmt.Println("lockfile:", app.LockFile)
			app.Startup(ctx)
		},
		OnShutdown: func(ctx context.Context) {
			app.OnExit()
		},
		Bind: []interface{}{
			bind,
		},
		Mac: &mac.Options{
			TitleBar: mac.TitleBarHiddenInset(),
			About: &mac.AboutInfo{
				Title:   fmt.Sprintf("%s %s", app.AppName, app.Version),
				Message: app.Description + app.Copyright,
				Icon:    icon,
			},
			WebviewIsTransparent: false,
			WindowIsTranslucent:  false,
		},
		Windows: &windows.Options{
			WebviewIsTransparent:              false,
			WindowIsTranslucent:               false,
			DisableFramelessWindowDecorations: false,
		},
		Linux: &linux.Options{
			ProgramName:         app.AppName,
			Icon:                icon,
			WebviewGpuPolicy:    linux.WebviewGpuPolicyOnDemand,
			WindowIsTranslucent: true,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}

// runHeadless starts only the HTTP API + proxy service, no GUI window.
func runHeadless(app *core.App) {
	fmt.Printf("[headless] %s v%s starting...\n", app.AppName, app.Version)
	// ctx stays nil so Wails runtime calls are no-ops (see core guards)
	app.StartService()
	fmt.Printf("[headless] HTTP API + proxy listening on http://%s:%s\n", "127.0.0.1", "8899")
	fmt.Println("[headless] Press Ctrl+C to stop.")

	// wait for interrupt
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	fmt.Println("\n[headless] shutting down...")
	_ = app.UnsetSystemProxy()
}
