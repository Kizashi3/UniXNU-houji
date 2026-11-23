# UniXNU 组织仓库对照（2026-10-24）

本轮在线枚举了 UniXNU 的 28 个公开仓库，并重点读取了 NativeWifi、NativeUfs、
ArmSmmu4K 和 UniXNU-sheng 的源码、板级配置与支持表。上游源码快照与固定 ref
在本机证据目录 `native-research/UniXNU-org-20261024/`；未更新原始 UniXNU 工作树，
也未将上游 SM8550 的物理驱动直接装到小米 14。

| 仓库/文件 | 已确认的内容 | 对 houji 的用途与边界 |
| --- | --- | --- |
| [NativeUfs](https://github.com/UniXNU/NativeUfs/tree/af785c1777161a62931425c2faaa536ce0bebd5b) | 原生 UFS、userdata 窗口、持久 Data 与磁盘尾部日志预留；源码明确是 sheng/SM8550 | 优先参考 SCSI/UTP、分区窗口和日志布局；GCC、PHY、SMMU、MCQ 与 DMA 必须按 houji 验证 |
| [ArmSmmu4K](https://github.com/UniXNU/ArmSmmu4K/tree/4d0d6598b1a36aeec3de01091893fa6660e49388) | 4 KiB 表、stream/context 验证与 live 更新逻辑 | 可复用表构建与审计规则；不能照搬寄存器扫描，houji 已在 S2CR 首读和 SMR 重读出现过外部异常 |
| [NativeWifi](https://github.com/UniXNU/NativeWifi/tree/dee6ec5c4371dd85d0867e563c7be19b4cf30783) | ath12k/WCN7850、MHI、QRTR/QMI、station 扫描/连接/收发接口及 host 模拟测试 | 上层代码值得复用，但需要板级 BAR/config space、MSI、DMA、固件、供电和时钟实现；代码存在不等同于 houji 已能联网 |
| [Sheng WifiProbe](https://github.com/UniXNU/UniXNU-sheng/blob/251b291adf941b9953fe3ae66a808b9b626e164d/package/WifiProbe.cpp) | `sheng-wifi=1` 的 stage 1 是只读检查 PCIe 供电、时钟、GPIO 与 root port | 可参考预检结构；GPIO 80/82/94 和 SM8550 GCC 偏移不能直接套用 |
| [Sheng 支持表](https://github.com/UniXNU/UniXNU-sheng/tree/251b291adf941b9953fe3ae66a808b9b626e164d#device-support) | 声明已进入原 iPadOS 桌面，UFS/显示/触摸/GPU 可用，Wi-Fi/USB 尚列为不可用 | 是参考设备的上游声明；不能当作小米 14 或 iOS 16 的实机结果 |

## 小米 14 的当前设备证据

Android 只读采集 `pci-ids-20261024.txt`：

- root port：`17cb:0113`，class `060400`。
- Wi-Fi endpoint：`17cb:1107`，class `028000`。Sheng 源码将相同 ID 标为 WCN7850。
  这支持共用芯片家族上层驱动的判断，不证明板级接线相同。
- live FDT 的 PCIe0：PARF `0x1c00000`，PHY `0x1c06000`，DBI `0x60000000`，
  config `0x60100000`；兼容串为下游 `qcom,pci-msm`。
- UFS host `0x1d84000/0x3000`，有 MCQ SQD `0x1da5000/0x2000` 和 VS
  `0x1da4000/0x10`，SMMU SID `0x60`。地址相同的部分仍需核验控制器模式和时钟。

这些事实来自当前运行设备，不把参考设备的硬件参数当作 houji 实测参数。

## 接入次序

先修正 OEM Scheduler HOB 的获取/核验并验证原厂服务环境，再验证 UEFI UFS
只读访问。随后对 NativeUfs 的板级常量进行参数化并检查 Darwin 22 ABI，接入
持久系统卷和专用磁盘日志区。磁盘日志需要存储驱动能实际写入、重启后能读回，
不是实时 USB 串口。原先的 pstore 标记没有成功跨重启读回，仍不可用。

Wi-Fi 排在可挂载根卷和 iOS 用户态启动之后；本轮没有在原型内核启用 PCIe、MSI
或 WLAN DMA。测试输入继续为用户提供的 iPhone X iOS 16.7.16 / 20H392，不使用
Sheng 的 iPadOS 17.7.11 载荷或该版本 Apple 二进制驱动替换 iOS 16 组件。
