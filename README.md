# py37qr

文字转二维码小工具：左侧输入跟随生成，短文字单码静止，
长文字喷泉码（fountain）切片后单张轮播，手机 App 抓够块数即还原。

## 本地运行

```bash
pip install -r requirements.txt
python3.7 qr_gui.py
```

依赖只有两个：`segno`（纯 Python 编码，无编译依赖）+ `Pillow`（界面预览渲染）。

## 配置文件

`qr_config.ini` 与程序放同一目录（编译后放 exe 同目录），改完重启生效：

```ini
[general]
debug = 0

[carousel]
interval_ms = 100

[qr]
box_size = 10
```

`debug = 1` 时在同目录生成 `qr_debug.log`（启动环境、每次生成参数/耗时/错误堆栈），
UOS 上出问题先开它复现一次，把日志贴回来定位。

云编译包里默认 ini 会以内嵌 + 外置（exe 同目录）两种形式存在，
外置优先：把 `qr_config.ini` 放 exe 旁边改完重启即生效，不用重打包。

## 云编译（UOS20 ARM64）

参考 `KeymouseGo` / `docx-replace-tool` 的做法：`ubuntu-24.04-arm` 上起
`arm64v8/debian:10-slim` 容器，Python3.7 + PyInstaller 打单文件。

打日期标签（如 `20261004`）或手动触发：`.github/workflows/build.yml`。
发版用日期版本号，`QR_tool_日期.zip` / `QR_scanner_日期.apk` 的日期自动跟随。
产物：`QR_tool_日期.zip`（内含 qr_tool 单文件 + ini + desktop + svg，UOS20 可直接运行）。

## UOS 桌面图标安装

Linux 图标不嵌进二进制（PyInstaller `--icon` 仅 Windows/macOS 有效），
靠 freedesktop `.desktop` 文件。把 zip 解压后，UOS 上手动安装：

```bash
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
cp qr_tool ~/.local/bin/ && chmod +x ~/.local/bin/qr_tool
cp qr_tool.svg ~/.local/share/icons/hicolor/scalable/apps/
sed "s|^Exec=.*|Exec=$HOME/.local/bin/qr_tool %F|" qr_tool.desktop > ~/.local/share/applications/qr_tool.desktop
```

装到 `~/.local/bin` + 应用菜单，无需 root。窗口 `WM_CLASS=Qrtool` 与
`qr_tool.desktop` 的 `StartupWMClass` 对应（注意 Tk 会把类名归一化为首字母大写其余小写，两处已对齐），任务栏可正确归组。
（注：文件管理器里二进制本体仍显示通用可执行文件图标，这是 Linux 正常行为。）

## 安卓 App（App/）

扫码拼接：CameraX 预览 + zxing-cpp 解码（C++，离线可用，无 Google 依赖），
按 `PYQRF1:` 喷泉帧头去重消元，集齐即进方格结果页（4500 字一段，点格复制）。
云编译见 `.github/workflows/android.yml`，产物为 release APK（versionCode 随构建号递增）。

签名与《云编译/签名密钥配置说明.md》同一套（别名 mykey）：
仓库 Secrets 备齐 `KEYSTORE_BASE64/KEYSTORE_PASSWORD/KEY_ALIAS/KEY_PASSWORD` 四项即可出签名包；
本地无密钥也能编过（产物为 unsigned 包，仅自测用）。
密钥文件（`*.keystore`）已进 `.gitignore`，绝不提交。
