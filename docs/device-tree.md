# 小米 14 设备树核对

2026-10-31 核对。硬件输入优先级为：本机 Recovery 的运行数据和 FDT、对应的小米官方 DTS/驱动、社区配置。
Android 的 `device/xiaomi/houji` 包含构建、HAL 和资源配置；内核 DTS 描述硬件资源。
两者都有用，但不能直接替代 XNU 的驱动实现。

## 固定来源

| 来源 | 本次读取的版本与用途 |
| --- | --- |
| [MiCode/kernel_devicetree](https://github.com/MiCode/kernel_devicetree/tree/d28b3972becd282c19d9d5b1bbd4ece3c6ad3989) | `shennong-u-oss` / `d28b3972` 同时含 houji 和 shennong；读取 `qcom/houji-sm8650.dtsi`、`pineapple.dtsi`、`pineapple-thermal.dtsi`、`pineapple-pcie.dtsi` |
| [MiCode 显示设备树](https://github.com/MiCode/vendor_qcom_proprietary_display-devicetree/tree/fade75a43279e91a83060a68612d872ab2dcc086) | `shennong-u-oss` / `fade75a4`；读取 houji 显示路由与 n3_42_0d_0a 面板命令 |
| [MiCode 显示驱动](https://github.com/MiCode/vendor_opensource_display-drivers/tree/abe499b28a74c723bdf619e07add6923d8e3aec8) | `shennong-u-oss` / `abe499b2`；核对 DCS 字节序、HS 模式、FIFO、回包计数及中断状态位 |
| [MiCode 内核](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/317e609aa4fb956c3aff565b62215e5a8041ca0c) | `shennong-u-oss` / `317e609a`；核对 `qcom-cpufreq-hw.c`、`qcom_q6v5_pas.c`、`qti_battery_charger.c` |
| [lolipuru 的 houji Android 配置](https://github.com/lolipuru/android_device_xiaomi_houji/tree/90f836ebc7b89a8dd22840b49db8c18cf7cabc2a) | `lineage-24.0` / `90f836eb`；核对显示、电源统计和音频依赖。`BoardConfig.mk` 默认仍使用预编译 kernel/DTB/DTBO，不能据此宣称完整公开了板级驱动 |
| [onelots 的 SM8650 公共配置](https://github.com/onelots/android_device_xiaomi_sm8650-common/tree/32fbdddf5395b2a0bc67a42e7425ffd7f79ce474) | `lineage-24.0` / `32fbdddf`；核对 Android 的性能、音频及 init 配置 |
| [onelots 的 SM8650 内核设备树](https://github.com/onelots/android_kernel_xiaomi_sm8650-devicetrees/tree/d9d0fc2cd8138d3fa0523e226ea5460380c4d240) | `lineage-24.0` / `d9d0fc2c`；核对 `qcom/graphics/gpu/pineapple-v2-gpu-pwrlevels.dtsi`。公共 SoC/aurora 内容不能当作 houji 专用音频树 |

上述是参考版本，不改变 `sources.lock.json` 中 XNU、UEFI 和图形组件的构建依赖。
设备标识、完整 FDT、固件及 Recovery 日志保留在私有验证目录。

## 已落实的修正

**GPU：** 本机选择 `qcom,gpu-pwrlevels-3`；逐项对照社区 DTS、本机 FDT 派生表和有效头文件，
12 档频率及总线票一致：231、310、366、422、500、578、629、680、720、770、834、903 MHz。
运行默认上限为 903 MHz。公共文件里的 950/1000 MHz 属于其他 SKU，SG 文件还有不同频点，不能取所有表的最大值。
KGSL 的 `initial-pwrlevel=11` 对应其降序表的 231 MHz；本项目 HFI 交接的 level 5 / 500 MHz 使用另一套索引，
并非设备树规定的运行默认值。启动交接仍需独立实测，不能简单替换索引。

**CPU：** 本次重读 houji Recovery 后发现，X4 的 `scaling_available_frequencies` 只列到 3052800 kHz，
另外四档 3110400、3187200、3244800、3302400 kHz 在 `scaling_boost_frequencies`；`boost=1`，
`cpuinfo_max_freq`、`scaling_max_freq` 都是 3302400 kHz，当次 `scaling_cur_freq` 也为 3302400。
旧代码只取普通表的上限，遗漏 boost。现将 X4 的允许上限改为 3302400 kHz，仍从启动后的 EPSS LUT 取真实索引，
要求表递增、首末频点匹配；不生成频率或电压。其他三个域保持本机原有上限，所有域继续服从 TSENS 限制。
`checks/cpu-lut.py` 使用实际 LUT 读取函数与 Recovery 的四域频率集合回归，覆盖遗漏最高档、损坏表和禁用域。
这证明源码不再丢弃 boost，不能证明 XNU 下已持续运行在该频率或提升了应用速度。

**结温：** 官方 `pineapple-thermal.dtsi` 与候选中四个 CPU 域的传感器分组相符：
EPSS 域 0/1/2/3 分别为 TSENS1 的 4–5、TSENS0 的 11–14、TSENS1 的 1–3、TSENS0 的 5–10；
GPU 使用 TSENS2 的 1–8。PMIC 的 `cpu_therm`、`display_therm`、`charger_therm0` 等属于另一条 ADC 通路，
不能把其中的 125°C 被动占位阈值当作机身/电池安全温度，也不能用结温代替机身温度。

已从本机保留的 vendor/odm 只读提取 `OS3.0.307.0.WNCCNXM` 的温控与性能配置，
确认普通模式使用六路温度的虚拟传感器和分簇限制，详见[原厂温控与调度核对](stock-power.md)。
配置本身不能替代 XNU 尚缺的 ADC5 Gen3/SDAM 与电池温度通信。

**亮度：** 官方 n3 面板使用 DCS、HS 模式和高字节在前的亮度值；范围与当前候选一致。
进一步对照官方驱动后，修复了读命令未清除旧 RDBK 数据/计数的问题，改为有界等待新回包，验证长度、包类型和范围。
修复 `DSI_INT_CTRL` 中断确认掩码，只确认自己完成的命令，保留 stream/frame/refresh 等其他事件及使能位。
主机回归涵盖旧回包、短包、错误包、超范围、既有错误状态和其他中断位的保留。
官方驱动还对 n3 的 QSync 状态作亮度延后处理；候选没有接管 QSync/动态刷新，必须在本机手工亮度、连续拖动与熄屏唤醒测试中核实交接状态。

## 电量、充电与音频的接入输入

官方 `pineapple.dtsi` 将 ADSP 绑定到 `qcom,pineapple-adsp-pas`，SMEM 远端为 2，
电源通信通道为 `PMIC_RTR_ADSP_APPS`。对应 PAS 驱动需要 `adsp.mdt` 与 `adsp_dtb.mdt`，
PAS ID 分别为 1 和 `0x24`，使用 ELF64；不能遗漏 DTB 的认证与保留内存。

`qti_battery_charger.c` 已确认协议字段，不再将它们记为未知：

| 字段 | 属性编号 | Linux 驱动的解释 |
| --- | --- | --- |
| 电池状态 | 0 | 充电、放电、满电等枚举，不能只从 USB 在线推断 |
| 容量 | 4 | 原始值除以 100 得到百分比 |
| 当前电压 | 7 | 电源接口单位为 µV |
| 当前电流 | 9 | 有符号 µA；接入 iOS 前仍需实机核对符号与充放电状态 |
| 恒定充电电流 | 12 | 位于温度字段之前；不在初始化中盲写此项 |
| 电池温度 | 13 | 驱动将原始值除以 10 后给出 0.1°C，即线上的值为 0.01°C |

电池/USB GET opcode 是 `0x30`/`0x32`，USB 在线属性为 0。这些基础编号与当前 sheng 实现对应；
它们的相符不代表 USB 限流、无线充电扩展或安全策略也可复制。
houji 覆盖层还给出 3150 mV 关机电压及延迟关机行为，需要结合状态机实现，不能只改一个固定电量值。
当前有效 XNU 尚无 ADSP/PAS/SMEM/GLINK 通路，所以这些协议事实尚未成为可用的电池服务。

本机 Recovery 确认双 CS35L41 和 WCD939x。所查公共 `pineapple-audio-overlay.dtsi` 包含 WSA884x 参考拓扑，
houji Android 配置则依赖设备专有 `mixer_paths_pineapple_mtp.xml`、`resourcemanager_pineapple_mtp.xml` 等文件。
因此声音仍须用本机固件/路由接通 GPR、AudioReach、I²C、时钟及功放，不能照抄公共参考板的 WSA 路由。

Wi-Fi 的 PCIe RC0 与 SMMU SID `0x1400/0x1401` 也有官方 DTS 对应；仍需供电复位、PHY、DMA、MHI/QMI 的执行链。
设备树使资源和协议更明确，没有自动补齐这些驱动。剩余验收见 [待完成项](roadmap.md)。
