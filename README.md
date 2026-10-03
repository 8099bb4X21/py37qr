# py37qr

Python3.7 文字转二维码小工具：左侧输入文字（跟随自动生成），过长自动拆成 1 至 4 个二维码，右侧预览并保存为 PNG。

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
```

`debug = 1` 时在同目录生成 `qr_debug.log`（启动环境、每次生成参数/耗时/错误堆栈），
UOS 上出问题先开它复现一次，把日志贴回来定位。

云编译包里默认 ini 会以内嵌 + 外置（exe 同目录）两种形式存在，
外置优先：把 `qr_config.ini` 放 exe 旁边改完重启即生效，不用重打包。

## 云编译（UOS20 ARM64）

参考 `KeymouseGo` / `docx-replace-tool` 的做法：`ubuntu-24.04-arm` 上起
`arm64v8/debian:10-slim` 容器，Python3.7 + PyInstaller 打单文件。

打 `v*` 标签或手动触发：`.github/workflows/build.yml`。
产物：`qr_tool`（Debian10 ARM64 单文件，UOS20 可直接运行）。
