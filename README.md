# OptiScaler 汉化版 nightly

[OptiScaler](https://github.com/optiscaler/OptiScaler) 的中文构建：每天跟随上游 master 自动注入译文并编译

上游更新频繁，新增功能尚未汉化属正常，新文本先显示英文

推荐搭配多倍帧生成插件：<https://github.com/dashdogy/MFG-Unlocker>

## 下载与安装

- 仓库 [Releases](../../releases) 页下载 `OptiScaler_zh-CN_*.7z`（上游有变化时每日构建，保留最近 11 个）
- 解压后把全部文件放进游戏目录，运行 `setup_windows.bat`；卸载运行生成的 `卸载_OptiScaler.bat`

> **注意：界面直接调用系统字体的微软雅黑或宋体，系统需至少存在其中一个才能显示中文**

## 与上游的差别

| 项                          | 上游     | 本仓库                                   |
| -------------------------- | ------ | ------------------------------------- |
| 界面文字                       | 英文     | 中文，显示字体调用系统微软雅黑，缺失时用宋体                |
| `OptiScaler.ini` 注释        | 英文     | 中文                                    |
| bat 安装脚本说明                 | 英文     | 中文，生成的卸载 bat 改名为 `卸载_OptiScaler.bat`  |
| ini 里 `LoadAsiPlugins` 默认值 | `auto` | `true`（默认允许加载 `plugins` 文件夹里的 asi 插件） |

游戏兼容性、功能行为与官方一致，只改显示文本与上述一处默认值

## 仓库内容

- `dict/`：三份汉化字典（界面文本 `menu.json`、`OptiScaler.ini` 注释 `ini.json`、安装脚本 `bat.json`）
- `zhkit/`：注入工具链，负责接入系统字体、写入译文、体检报告与回归自测（纯 Python 标准库）
- `.github/workflows/nightly-zh.yml`：Actions 工作流内容

本仓库不含上游源码，工作流运行时现拉 `optiscaler/OptiScaler` 再注入编译

## 声明

- 个人汉化分支构建，**未做代码签名**，首次运行可能弹 SmartScreen「未知发布者」提示
- 上游代码遵循其原始许可，本仓库只维护译文与工具链
