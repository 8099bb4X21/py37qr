# py37qr

长文字跨设备传递：ARM 端把文字转成二维码轮播，安卓 App 对着扫即还原全文。

## ARM 端（`qr_tool`）

作用：输入文字，短文字显示一张静态二维码；长文字按喷泉码切片后单张轮播，
手机抓够块数自动还原（免顺序、免缺码）。

用法：解压 `QR_tool_日期.zip` 直接运行 `qr_tool`；长按无，输入即生成。

桌面图标（Linux 菜单/任务栏）：

```bash
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
cp qr_tool ~/.local/bin/ && chmod +x ~/.local/bin/qr_tool
cp qr_tool.svg ~/.local/share/icons/hicolor/scalable/apps/
sed "s|^Exec=.*|Exec=$HOME/.local/bin/qr_tool %F|" qr_tool.desktop > ~/.local/share/applications/qr_tool.desktop
```

## 安卓端（`QR_scanner_日期.apk`）

作用：对着 ARM 端屏幕扫码，自动收集轮播帧，集齐进方格结果页，
4500 字一段，点格复制；扫码进自动复制第一段；右上角菜单有历史记录（最近 30 次）与退出。

用法：安装 APK，授予相机权限，对准二维码，保持到提示集齐。

## 传输说明

- 短文字：一张静态码，内容即原文，任意扫码 App 可读。
- 长文字：先 gzip -9 择优压缩（压不动则原文直发），再喷泉码切片轮播。
- 压缩帧前缀为 `PYQRF2`（原文帧为 `PYQRF1`），须用配套版本 App 扫码。
- 无新增依赖（gzip 为 Python 标准库）。

## 配置文件

`qr_config.ini` 与程序放同一目录，改完重启生效：

```ini
[general]
debug = 0

[carousel]
interval_ms = 100

[qr]
box_size = 10
```
