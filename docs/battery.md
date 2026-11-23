# 电池接入

r263、r264 已通过本机原厂 ADSP 固件和 PMIC GLINK 发布真实 `IOPMPowerSource`，
读到电量 89%、USB 在线与充电中状态。用户确认电量/充电图标恢复正常，
并实测插拔数据线能切换充电与未充电状态。充电电流、持续净电量变化和温度保护仍需验证。
此前缺少电源设备时，状态栏的空电池不能代表实际电量；r258–r262 采样均未开启低电量模式。

原厂 Recovery 已能读取电量、充电状态、温度、电压和电流。r255 返回 Recovery 后的一次读数为
87%、33.3°C、4.218 V，USB 在线、状态为 Charging；这只证明 Recovery 路径正常。
`NSProcessInfo.lowPowerModeEnabled` 和 `thermalState` 已在 r258 中采集，结果见下文。
Apple 说明低电量模式会限制 ProMotion 刷新率；这不证明当前卡顿由电池信息引起，
也不代表本机已经建立 120 Hz 显示链路。

## 来源与依赖

参考固定版本 [UniXNU-sheng 08cde20e](https://github.com/UniXNU/UniXNU-sheng/tree/08cde20edc3254ed6f7df8d0f5384fb887786e8f/package)
的 ADSP、PMIC GLINK 与 `IOPMPowerSource` 路径，并对照
[小米内核电源驱动](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/317e609aa4fb956c3aff565b62215e5a8041ca0c/drivers/power/supply/qti_battery_charger.c)。
SMEM、SMP2P 的可移植解析器及许可证位于 `kernel/overlay/iokit/Kernel/houji-ufs-root/battery/`。

本机设备树确认 SMEM 为 `0x81d00000 + 0x200000`，ADSP IPC 为 `0x406000`，
ADSP 固件区为 `0x9df00000 + 0x4680000`、DTB 区为 `0x9de80000 + 0x80000`。
后面三个地址与 sheng 不同。固件认证启动、中断、SMEM/GLINK 通道和电池消息已在 r263 接通，
没有复用 sheng 的硬件地址、双电芯扩展属性或 USB 输入电流写入。

## 当前诊断候选

r256 已安装电源采集程序，但没有产生新的 iOS 日志；最后一个已提交的内核检查点
位于 CPU 调度初始化和新增 SMEM 探测之前，不能据此判定具体故障指令。
后续对照启动关闭 `houji_battery_probe`，保留用户态采集程序，并把 CPU 初始化后的
检查点移到 SMEM 探测之前。整段 SMEM 读取尚未通过真机验证，不应作为日常启动默认项。
r257 关闭探测后恢复了 SpringBoard 运行并保存了约 197 秒的终止记录，但没有电源采集文件。
离线检查确认程序及 plist 均为 root 所有，问题至少包括启动登记遗漏：系统 launchd 缓存中
没有这个新任务，启动程序内嵌的扫描目录也不包括 `/Library/LaunchDaemons`。
修复后的对照版继续关闭 SMEM 探测，单独验证采集任务的启动。

r258 已验证该启动修复：从系统运行约 48.70 秒到 177.55 秒，共取得 25 次采样。
所有 `IOServiceGetMatchingServices` 查询成功，但 `IOPMPowerSource` 与 IOPowerSources
列表都为空；`lowPowerModeEnabled` 均为 false，`thermalState` 均为 0。
这证明 r258 当时缺少电池电源设备，且该观察时段没有启用低电量模式；不能把卡顿归因于
“空电池必然开启低电量模式”。`thermalState` 是 iOS 报告的状态，不是实际传感器温度，
不能代替原生 TSENS 温控记录。真实电池数据上报在后续 r263 中实现。

- `houji_battery_probe=1` 只读取 SMEM 目录、目标分区和条目头，以及 340 字节的
  SMP2P 项；最多 8192 次对齐的 32 位读取，跳过无关分区与消息负载，并复查分区边界。
  已移除原来的 2 MiB 全区复制。r259 真机完成 102 次读取，解析错误为 0，随后运行
  SpringBoard 至约 193 秒并返回 Recovery。找到了 AP/ADSP 与公共分区，以及 32 字节
  GLINK 描述符和 16384 字节发送队列；未找到 SMP2P 入/出项及 DSP 接收队列。
  这确认了读取路径，并不表示 DSP 电池服务已经运行。
  没有 DSP 启动、共享内存分配、门铃确认或电池数值发布。
  旧的 ready 位不能作为 DSP 仍在运行的证明。
- `houji_battery_probe=2` 增加原厂固件只读资格检查：在 GPU/UFS 共存已验证后，由独立线程
  校验 UFS LUN 4 的 GPT，限定读取 `modem_a` 中的 `adsp` / `adsp_dtb` 分片。
  FAT/MDT 解析器来自同一固定上游版本；验证文件范围、装载区域和完整逻辑文件摘要。
  内存分配失败、损坏目录和越界读取有主机检查。r260 正常运行系统，但固件读取返回
  ENXIO：新增入口尚未接入底层存储命令白名单，LUN 4 的 TEST UNIT READY 被拒绝。
  修订版为单次命令增加受传输锁保护的授权：只允许 GPT 元数据与已校验 `modem_a`
  范围内的 READ(10)，任何返回路径都会清除授权。主机测试现在执行实际
  `RootCommands.h` 提交路径，覆盖该遗漏、边界拒绝及失败清理。r261 真机读回通过：
  DTB 逻辑文件为 73528 字节，ADSP 为 36698360 字节，两份完整 SHA-256 均与
  同一设备 Recovery 中读取的原厂分片重建结果一致，存储路径无错误。
  不回退到其他槽位，不写固件分区，不调用 PAS 或写入 DSP 内存。
- `houji_battery_probe=3` 在上述固件检查成功后，稀疏读取 cmd-db 的 LCX、LMX、XO
  资源，记录 AOSS 标识、RSC 版本及三个活动 TCS 的占用状态。只读取目录、名称和
  所选资源，不复制整个共享区；主机检查覆盖受限读取、边界和耗尽预算。
  这一步用来确认后续启动 ADSP 所需的资源，不发送电源请求或开启中断。
  r262 真机完成 125 次 cmd-db 读取，无错误：LCX/LMX/XO 分别有 8/5/4 个等级，
  RSC 版本为 3.2，AOSS 标识有效，三个活动 TCS 均为空闲且没有启用的命令。
- `houji_battery_probe=4` 在 r263 通过启动和电量显示测试。在只读检查成功后，
  使用本机保留区、PAS 1/36、IPCC 和 RSC 中断启动 ADSP，并接入 GLINK/QRTR。
  电源请求必须确认完成；超时不清除或重用不确定的 TCS。提交给 PAS 的元数据在
  本次临时启动内保留，失败不释放可能仍被安全世界使用的内存。
  QRTR 仅列出本机原厂注册文件确认的 ADSP 域，不沿用平板的 modem/CDSP 域。
  电池发布器需要完整且未过期的真实读数；断线或关键属性超时撤下电源设备。
  可选属性超时后在本次连接中跳过，防止迟到回复与下一轮相同请求混淆。
  电流极性仍需本机验证，因此暂不向 iOS 发布电流和推算的剩余时间。
  r263 的 ADSP 就绪用时为 470 ms，两个 GLINK 客户端建立连接；1245 次电池属性回复
  没有错误或超时，代理供电请求已在固件接管后释放。日志也暴露了重复启动检查点写盘，
  后续修订只记录阶段变化，并抑制读数未变化时的电源通知。通知订阅消息另外对齐
  小米原厂的类型与零初始化负载。r264 已验证这些修订：473 次属性回复无错误或超时，
  最终消息尾部没有重复阶段 13 检查点；用户再次确认电量和插拔切换正常。
  25 次 iOS 采样中，启动后的 24 次均有电源设备，记录了 89–90% 电量、
  AC/Battery 两种供电状态及充电状态切换；低电量模式始终为 false。
  电池温度记录为 33.5–35.6°C，不是芯片结温或温度保护已实现的证明。
- `tools/build-power-probe.py` 构建签名的 iOS 16 采集程序；安装与真机执行是单独步骤。
  启动项读取低电量模式、温度状态、`IOPMPowerSource` 及 IOPowerSources，最多采集 25 次，
  间隔 5 秒，写到 `/private/var/log/houji-power.jsonl`。只保留电源属性白名单，不调用电源设置接口。
  系统服务调用仍可能阻塞，采样次数有界不等于整个进程存在硬性退出时限。
- `tools/register-power-probe.py` 在离线镜像副本中将启动项移动到
  `/System/Library/LaunchDaemons`，并加入 `/System/Library/xpc/launchd.plist` 的
  `LaunchDaemons` 字典；保留已有任务、其他缓存内容和文件 inode/归属。
  主机检查覆盖实际登记操作和重复执行，运行成功仍需以真机新日志确认。
- `tools/capture-userland-logs.py` 从离线快照收集这个确切文件，并按内容与上一轮比较。
  主机检查覆盖 SMEM 异常边界及日志采集，不能代替 ADSP 或电池硬件测试。

服务在取得有效容量、在位和充电状态后才发布；未响应或失联标记不可用，
不能将未初始化值发布为 0%，也不能用固定百分比替代真实数据。

`HoujiBattmgr.c` 是只读协议组件，已接入 mode 4 候选的传输层。它只请求小米驱动公开的标准电池
及 USB 属性，按原始单位校验取值，完整的一轮关键属性成功后才发布快照；超时、断线
或过期读数不可用。主机测试覆盖消息边界、错误、过期数据和实际发布器的状态转换，
主机检查本身不能证明硬件工作；本机启动、显示和插拔的证据来自 r263、r264 实测。

来源：[Apple 低电量模式说明](https://support.apple.com/en-lamr/101604)、
[ProMotion 开发说明](https://developer.apple.com/documentation/quartzcore/optimizing-iphone-and-ipad-apps-to-support-promotion-displays)。
