# wax 宠物猫砂盆面板

首页用暖米色背景、猫咪插画和两个大按钮。猫砂铲图案标记「开始清理」。

## 数据点

| 数据点 | 产品定义 | 首页行为 |
| --- | --- | --- |
| DP1 | 手动铲粪，布尔 | 点「开始清理」时发 `false` 释放上次请求，再发一次 `true` 请求清理 |
| DP5 | 暂停／继续，布尔 | 「暂停清理」发 `true`。「继续清理」发 `false`。按钮跟随设备回报 |
| DP22 | 状态，上报枚举 | `standby`（0）待机，`waiting_cluster`（2）等待清理，`cleaning`（3）清理中 |

DP22 另支持 `off`、`uv`、`deodorization`、`sleep`，顺序与 APP004 的产品功能表一致。DP5 为暂停时，首页显示「已暂停」。指令发送中保留原设备状态，并显示发送提示。清理中对应主板使能电机输出，机构实际转动和动作完成需要整机实测。

上报离线时禁用两个动作。开始清理需要在线、待机和 DP5 已解除暂停。清理中或等待清理时可暂停。待机但仍处于暂停时可以解除暂停，再手动请求清理。

## 构建和上传

```powershell
shnote --what "构建猫砂盆面板" --why "生成源码包和独立预览" run -- python build_panel.py
```

生成文件位于 `output/LB_PANEL_UI/`。HTML 可离线打开并模拟按钮和设备状态。ZIP 是源码归档，解包后在涂鸦 MiniApp IDE 导入 `tuya-panel` 目录。正式代码包由 IDE 的「上传」生成。

在 IDE 登录产品所属账号，关联「wax宠物猫砂盆」面板小程序。调试启动参数设置该设备的 `deviceId`，使用虚拟设备核对 DP1、DP5、DP22，再上传开发版本。实际设备需在台架串口与手机并行核对。 [涂鸦面板快速开始](https://developer.tuya.com/en/miniapp/develop/miniapp/guide/start/quick-start)
