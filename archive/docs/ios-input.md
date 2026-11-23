# iOS 测试输入

后续 iOS 测试固定使用用户提供的 iPhone X iOS 16.7.16（20H392）。
`board.toml` 校验 iPhone10,3 / d22ap / T8015（0x8015）/ board 0x06；该 IPSW
同时支持 iPhone10,6。小米 14 的物理硬件描述始终保持 houji / SM8650。

原文件名：`iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw`，6,171,035,648 字节。

完整 IPSW SHA256：
`ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb`

已读取 BuildManifest 并提取 DeviceTree、StaticTrustCache、SystemTrustCache，
解压出 50,937,856 字节的 ARM64 kernelcache：

`2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221`

内核自报 Darwin 22.6.0，XNU 8796.142.1.703.8~1，RELEASE_ARM64_T8015。
这只是原版 Apple 输入的验证，尚不是可在 SM8650 启动的内核。目前另行编译的
Apple XNU 8796.141.3 早期移植内核已在本机显示 Darwin 22.6.0 和 VM 初始化日志，
使用适配 Darwin 22 boot_args 布局的 DarwinBoot；它并不等同于上述原版 T8015 内核。

在通用 UniXNU 仓库中运行：

```sh
./unixnu ipsw fetch -D ../UniXNU-houji --ipsw /absolute/path/to/Restore.ipsw --out /absolute/path/to/output
```

未配置远程下载源，避免意外回退到参考设备的 iPadOS。Apple 固件、设备采集数据和 OEM
二进制均保存在仓库外，不提交 Git。Android boot image 的 `os_version=16.0.0`
是适配现有 Android 启动链的封装字段，与以上 iOS 测试版本分别记录。

## 数据保留

目前没有配置 userdata 窗口或系统卷，不生成刷写 userdata 的操作。
UEFI 第一轮使用无存储驱动、RAM 变量的固件，只通过 `fastboot boot` 临时启动。
当前 XNU 试验添加了只读 RAM Block I/O 和软件 FAT 文件系统，仍没有物理存储驱动
或 iOS 系统卷。完整 iOS 用户态测试需要另外安排不占用现有 Android
分区的系统卷方案。
