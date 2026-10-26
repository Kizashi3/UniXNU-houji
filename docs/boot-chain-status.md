# houji 启动链状态

- 原厂输入：`桌面/临时/xiaomi14-rom-stock/images`
- 目标：Xiaomi 14 / houji / SM8650
- 原厂版本：OS3.0.305.0.WNCCNXM
- 用户当前系统：OS4.0.18.0.XNCCNXM
- iOS 输入：iOS 16.7.16 / iPhone10,3 / build 20H392

## 当前结论

原厂包可以作为启动链与板级分析输入，但它不等于 UniXNU 可启动镜像。交接快照已包含 Mu-Silicium 的 houji 平台构建产物：`houji.dsc`、`houji.fdf`、`FVMAIN.inf` 以及 ShmBridge/UFSDxe FFS。离线一致性检查已通过，当前剩余问题是设备运行时的 `ASSERT RpmbListener.c+160 Not Found`。

## 已确认的离线证据

- 目标是 Xiaomi 14 / `houji` / `SM8650`，首个 ADT 仍采用 256 MiB 单核探测窗口。
- `FVMAIN.inf` 包含 ShmBridge 文件 GUID `41EBB6A6-2C19-4C02-841D-848CE004A282`。
- `FVMAIN.inf` 包含 UFSDxe 文件 GUID `0D35CD8E-97EA-4F9A-96AF-0F0D89F76567`。
- ShmBridge INF 的 `[Depex]` 为 `TRUE`；这只能证明调度依赖满足，不能证明 `9C1EB71F-DD6C-4ED5-9F6A-5CC0CA789F16` 已在运行时安装。
- ShmBridge 二进制含有 `Failed to install ShmBridgeProtocol` 诊断字符串，后续应从 Dispatcher 日志确认该入口的实际返回状态。

使用 `scripts/verify-houji-port.py` 可重复上述检查；脚本只读，不连接设备，也不会调用 fastboot。

## 禁止事项

在形成可验证的实验 payload 前，不执行任何 `fastboot flash`、`fastboot erase`、`fastboot format` 或 userdata 操作。
