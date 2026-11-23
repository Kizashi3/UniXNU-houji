# 启动日志采集状态与落盘方案

当前 UEFI/XNU 仍没有可用的实时 USB 日志通道。已保存的日志可在重启后自动读取；
屏幕上的全部输出不会自动进入 ADB。ADB 在 Android 或 OrangeFox 运行，进入
UEFI/XNU 后该服务停止。

## 已验证与未验证

| 路径 | 本机结果 | 下一步 |
| --- | --- | --- |
| 原 ramoops/pstore | 标记写入画面已确认，返回 Android 后 pstore 为空 | 原区 A7000000–A73FFFFF 与启动固件保留区重叠；未验证保留，不能作为可用通道 |
| XNU USB CDC ACM | 原型未在 Mac 枚举，SMMU 预检还没有有效 USB SID 路由 | 先补齐供电、时钟、SMMU 与控制器初始化，不能只开 Mac 串口脚本 |
| 原生 XNU 固定文件＋重启后 ADB 取回 | r25 已跨 Android 重启取回；r26 已跨 OrangeFox 重启取回并核验 CRC、运行编号和裸 FAT 数据 | 正常检查点可用，实时 USB 和任意 panic 自动落盘仍未实现 |
| 磁盘日志＋Linux USB 读取器 | 上游流程和源码已核对；houji 已使用 OrangeFox 内核/USB 作为读取环境 | 独立 CDC 镜像尚未适配，现有 ADB 读取路径已可用 |
| 原厂 logfs＋Android ADB | r22 实机创建并跨重启取回 UniXNU.log，11,609 字节、233 行；完整快照和前后 SHA 一致 | 接入全局 UEFI/XNU 日志并增加后续轮次提交；当前只覆盖应用诊断文字 |

当前首选读取环境是已实机验证的 houji OrangeFox root ADB。它使用手机自己的
Linux 内核与 USB 驱动，不依赖 Android 正常启动，也不要求解密 userdata 才能
读取独立的 logfs。`capture-logfs.py --recovery` 启用这个读取路径。
以下按轮次保留的检查记录描述当时状态；r118 和当前自动轮询方式见文末。

重叠是本机地址布局事实；尚未直接观测哪个启动阶段覆盖了旧 pstore 标记，
因此不把“启动固件覆盖”写成已经证明的唯一原因。ramoops 官方说明也要求该
RAM 区真正跨重启保留：[Linux ramoops 文档](https://docs.kernel.org/admin-guide/ramoops.html)。

## 优先采用的磁盘流程

上游 [Sheng 无人值守流程](https://unixnu.com/zh/devices/sheng-unattended-test) 先通过
NativeUfs 将消息缓冲、诊断文本及快照写到磁盘，之后启动 Linux 读取器，通过
USB CDC shell 取回。USB 出现在 Linux 读取阶段；它不是 XNU 的实时 CDC 后端。

已读取并固定的源码：UniXNU-sheng `251b291a` 的 BootLog.c、BootDiagExport.c、
linux-log/init、read-sheng-log.py，以及 NativeUfs `af785c17`。BootLog 每两秒
提交一轮，文本和消息先写、头部后写，再同步设备缓存。写入窗口在 NativeUfs
完成根布局检查后才开放，GPT 变化时停止。houji 必须重新确定布局、LUN 和边界，
不能对当前挂载的 Android userdata 直接启动这个写入器。

Android 仍可用时，先通过已有 root ADB 读取同一窗口，省去独立读取器的启动。
清空 Android 之前，再将 houji 的 Linux 读取器验证到能枚举 USB 和只读导出。
用户允许清空系统与数据，但这不会自动使当前 userdata 尾部成为空闲区。

## 本机只读采集工具

[capture-android-boot-log.py](../scripts/capture-android-boot-log.py) 支持上游 SHLOG001
v1–v4 的 32 MiB 消息/文本窗口，不读取窗口外的诊断文件或 GPU cache export。

```sh
python3 scripts/capture-android-boot-log.py --adb-port 5038 \
  --output /absolute/path/to/new-private-capture
```

ADB 端口按实际连接选择 5037/5038/5047。脚本固定设备序列号，核对 houji、root、
userdata 的块设备、大小及起始位置，并根据只读 GPT 备份计算范围。先读 4 KiB；
没有 SHLOG001 时返回状态 2，只保存结果和摘要哈希，不复制未知用户数据。发现
日志头后继续核验版本、绝对 LBA、窗口大小、消息区与文本环的边界，再读取完整
窗口，并检查采集前后头部一致。所有输出留在新的本机私有目录。

已保存窗口也可完全离线解码：

```sh
python3 scripts/capture-android-boot-log.py --decode /absolute/path/log.bin \
  --output /absolute/path/to/new-decoded-capture
```

输出固定为 log.bin、header.json、msgbuf.txt、slots.txt、latest.txt，设备提供的
tag 不用作文件路径；不会执行串口 shell、自动重启或向块设备写入。

`tests/check-android-boot-log.py` 已验证损坏/越界头拒绝、文本环回绕顺序和固定
输出路径。本机 `log-reader-adb-preflight-r1/capture.json` 记录了实际读取 4096
字节且无日志头。这个结果只证明读取和拒绝路径，不证明跨重启日志已经可用。

## 2026-10-24 原厂 logfs 的实际检查

Android 当前把 `/dev/block/sda13`（8 MiB，by-name/logfs）以 vfat 挂载到
`/dev/logfs`。实际剩余 4836 KiB，有六个 64 KiB 的 UefiLog 文件。已先只读
备份完整分区到本地私有 `native-port/logfs-backup-20261024/logfs.bin`，本地
SHA256 与读取前、读取后的手机端 SHA256 相同，manifest 单独记录。尚未对该
分区写文件或改动 FAT。恢复整个分区必须先停止挂载；不能在线覆盖正在使用的 FAT。

六份文件均已解出并检查，没有本次端口的 `HOUJI` 或 DarwinBoot 输出；它们是
原厂启动链日志。发现这些文件不代表 UniXNU 的 Console/SerialPort 已接入日志。
原 `rawdump` 则受厂商 ramdump/dload 属性控制，未把它当作空闲日志空间。

新增 [capture-logfs.py](../scripts/capture-logfs.py)：

```sh
python3 scripts/capture-logfs.py --adb-port 5047 \
  --output /absolute/path/to/new-private-logfs-capture
```

工具先核对 root、houji、固定序列号、sda13 的大小和 vfat 挂载，仅读取白名单的
六个原厂文件及预留文件名 `UniXNU.log`，不创建手机端文件、不重启。固定本地
文件名、单文件大小限制、前后 SHA 与私有新目录限制均生效。
`evidence/logfs-adb-capture-r1/capture.json` 记录实机成功取回六份文件，但
`native_log_file_present=false`。`UniXNU.log` 只是后续 UEFI 日志的候选名称，
目前没有手机端写入器，不能据此宣称日志问题已解决。

原厂 FAT 适合通过 SimpleFileSystem 保存少量 UEFI 文本。上游的 SHLOG001
整个窗口为 32 MiB，不能原样写进 8 MiB logfs，也不能直接覆盖 FAT 数据结构。
XNU 的持续消息记录仍须另外确定文件或扇区窗口，并验证 NativeUfs 的边界保护。

## r21 logfs 文件写入测试

r20 已真实读取六个 UFS GPT 头且 CRC 全部通过，物理存储读取路径已打通。
r21 使用重新备份的原厂 logfs FAT，创建自己的 UniXNU.log；仅允许物理
LUN0 的 [0x1000,0x1800) 范围写命令，GPT 和分区 GUID/CRC 不符则不开放。
已有文件时拒绝覆盖。完整备份位于 native-port/logfs-backup-before-persistent-log-r21。

本轮捕获应用自身的 HOUJI 文字与命令门诊断，不含其他模块直接输出的
全部 DebugLib 日志，也不含 XNU 消息缓冲。成功条件是手机端 Flush/Close/
读回通过后，重启 Android，capture-logfs.py 独立取回同一文件并核对内容。
只有完成这个跨重启验证才能把该路径标为可用；编译或文件 API 返回成功
单独都不够。全局 UEFI 与 XNU 持续日志仍需后续接入。

首次 r21 启动预检发现原厂日志更新使旧快照 SHA 改变，已在重启前拒绝。
随后重新备份到 logfs-backup-before-persistent-log-r21-pretrial，读取前/本地/
读取后均为 1d1af9cd3894f72095052596e9dd01e67f98d0dc55635098f14cf1d53888f32b；
仅更新本地备份绑定，固件和 FAT 字节不变。旧快照保留。

## r22 跨重启验证成功

补入原 EDK PartitionDxe 后，实际日志确认 LoadImage/StartImage、主 LUN
非递归连接、唯一 logfs 分区匹配、FAT 连接及 OpenVolume 全部 Success。
手机返回 Android 后，通过 root ADB 独立取回 UniXNU.log，共 11,609 字节、
233 行，全部为 HOUJI 诊断行，从本轮 r22 标记到 snapshot end 完整；
设备读取前、本地和读取后 SHA256 均为
643e6a4a69ffdb1c0813133b2cfae615bf1d6e25ffced8c9ef49f8d2eb8c092b。
证据在 native-port/evidence/logfs-adb-capture-r22。

五个引导分区、slot/build/vbmeta digest 均保持原基线，六个 LUN 的
主/备 GPT 共 12 个原始范围逐字节哈希与备份相同。当前这条路径已实际
保存文件，不能再称为只有原厂日志。但它仍是结束前提交的应用快照，
尚不包含 Freeze 后的写入状态、所有 OEM DebugLib 输出、早期崩溃落盘
或 XNU 持续消息。现有文件保留；再次运行同一写入测试会拒绝覆盖。

r23 增加提交前的 payload 字节数和 CRC32 footer。Mac 读取器已验证
实际 payload=18,919 字节、CRC32=66557540，与 UEFI 保存值一致；
损坏、截断、错误长度、尾随数据和不匹配版本的离线用例会拒绝完整性确认。
HCI/SMMU inventory 完整保存，没有发生读取异常。
r24 使用相同日志路径保存进入 XNU 前的检查点，然后关闭写门进入内核；
该文件不能被解释为包含 ExitBootServices 后的 XNU 结果。


## r25 内核固定文件快照

r24 原生 GPT 读取已在照片证实，但 UEFI 日志在 ExitBootServices 前关闭，
因此无法包含随后 XNU 的 READ PASS。r25 新增独立 XnuLog.bin，64 KiB 文件
预分配在原 FAT，内核只修改其已有数据块。前置备份、双 FAT/文件归属、唯一
运行编号、正文与头部 CRC、提交头最后写、flush 和完整读回共同约束此路径。
读取器保存原始二进制，并仅在校验通过后导出 XnuLog.txt；可通过 --xnu-run-id
绑定 allocation/layout.json 中本轮编号，拒绝将旧文件当作新结果。
当前只能保存到明确的正常上下文检查点，不是实时 USB 串口，也不是任意 panic
均可持久化的处理器。尤其 UFS/SMMU 尚未可用或传输已隔离时，不能尝试写日志。
实机验证状态见 bringup.md；未验证前保持候选标记。


r25 实机验证已通过：手机自动回 Android 后独立取回 10,583 字节内核快照，
正文 CRC=15753b53、头部 CRC=4f9a592f、本轮编号完全匹配。O_DIRECT 读取
得到的文件数据也与 ADB 文件逐字节一致。可直接查看保存的 XnuLog.txt，
不再需要用照片确认这一个检查点；更早期崩溃或 UFS 传输故障仍可能需要屏幕。

## r26 自动返回恢复环境并取回日志

实际镜像 b359990f92d7e5a38e1e9828abca688c5b684868f08686b0389a3a6e65dc41cb
从 root OrangeFox 临时启动后，XNU 顺序完成日历初始化与 HFS 注册。三个正常
检查点连续提交同一预分配文件，后续提交核对上一次完整文件 CRC，未重新分配 FAT。
最终 payload=13,047 字节，CRC32=b684045e，头 CRC32=f9e7f2db，运行编号
为 de0003061a104c7086d7c80a0e9a17f9。重启后 ADB 文件和 O_DIRECT 原始 FAT
数据逐字节相同，记录在 native-port/evidence/logfs-recovery-r26。

XNU 在日志读回成功后，仅对 misc 的首个 4 KiB 页设置 boot-recovery 和
不含 wipe 的 recovery 参数。恢复环境返回后，BCB 前 864 字节已被正常清除，
864 字节之后的 reserved、A/B 信息及 misc 其余内容与本轮事前备份逐字节相同。
这次成功验证了自动进入恢复环境，尚未挂载 iOS 根卷。
## 当前 houji 抓取流程（2026-10-25）

目前使用已验证的 `logfs` 文件写入 → 自动返回 OrangeFox → root ADB 只读抓取。
这是下文早期调研之后已经落地的路径；早期关于“尚未写入”“Android 仍可用”的
说明属于对应历史阶段。当前 userdata 已是 iOS 卷，不进入 Android、不格式化 data。

`scripts/watch-native-recovery.py` 在临时启动成功后轮询已有的三个 ADB 服务；
发现本机 root rescue 后立即执行 `capture-logfs.py`，没有额外的启动宽限等待。
抓取同时核对本轮运行编号、文件前后摘要和 native CRC，保留失败或不完整的证据。
`UniXNU.log` 是 UEFI 应用快照；`XnuLog.bin` 是否有效须单独检查，不能混为一谈。

r118 已在 84.481 秒自动取回：native payload=101371、CRC=09bcde53，有效；
最后保存点在启动 SQE/CP 前。XNU 文件本轮尚未提交，不能推断已进入内核或已经
执行 GPU。五个引导分区、十二段 GPT 和 misc 保留区已另行只读校验不变。

2026-10-25 重新核对 [sheng 示例](https://unixnu.com/zh/devices/sheng-unattended-test)
和 [通用指南](https://unixnu.com/zh/porting/log-capture)：它们的 USB CDC 用于
**重启后的 Linux 读取器**，仍然先依赖写入器完成持久化，不是 UEFI/XNU 的实时
USB 日志。sheng 的 SM8550 内核、DTB、PMIC、32 MiB userdata 窗口不能直接套到
houji 的 SM8650 和现有 8 MiB logfs。换传输方式不会补出崩溃前未写入的记录。
通用 UEFI 二维码导出需要菜单和 Advanced Logger 可运行，同样不能恢复硬件停止后
尚未收集的输出。继续使用现有 ADB 读取器，避免为 GPU 调试另开 USB 驱动工作。



## r125–r126 的临界区可见性

r125 的大字仍是 `5004/03d02020/1`，属于写调用之前的正常 trace。
r126 对照关闭正常 trace 的 framebuffer 写入，也在 recorder 运行时使 ProbePrint
仅追加 CPU 缓冲、不进入 ConOut。异常终态700f和 recorder 停止后的输出保留。
这不建立跨复位持久性：79.448秒恢复后只读到了最后一个 CRC 有效的准备快照，
后续易失 RAM ring 仍未取回，不能把缺少后续文件等同于已确定某条精确指令阻塞。
后台 watcher 自动检测、8文件抓取及原生CRC检查成功，无需固定等几分钟。

## r137 的未提交 XNU 日志

r137 照片确认已进入 8 GiB 内核窗口，CPU0 为 `TG0=2/TG1=1` 的 16 KiB 页配置；
随后 CPU1 虽有 CPU_ON 返回 0，init/timer/IPI 仍全为 0，在 `SweetCPU.cpp:157`
超时 panic，没有到达 CPU descriptor 探针或原生 UFS 日志检查点。
后台在约 127.618 秒完成自动返回 OrangeFox 后的抓取，但具体触发复位的机制未证实。

本轮 `UniXNU.log` 的 payload 17497 字节、CRC32=`026F70C6` 有效；
`XnuLog.bin` 的运行编号匹配，`committed=false/valid=false`，仍为初始标记。
watcher 的 `complete` 只确认本轮身份、native CRC 和文件稳定，不能当作 XNU
提交成功。CPU1 panic 来自照片，不能声称它已经落盘；本轮也没有 GPU 执行证据。
见[r137 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r137-result.json)、
[实际 capture](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r137/capture.json)和
[watcher 记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r137-watch.json)。

## r138 正常检查点提交与自动返回通过

r138 补入两个有类型启动变量的 PoC 发布后，实际通过八核 bound worker/timer/IPI
检查，最终全部核心 `TCR=226511A511`、CPU 页为 16 KiB。独占 descriptor 的四个
子范围观察、实际 NativeAdrenoMemory 两个 4096 logical／16384 owned BO 的属性、
24 次 AT 翻译采样、邻 backing 保持及释放均通过；该轮没有 GPU 映射、DMA 或图形执行。
BO0 报告 `pmap-attrs=2/6/0 sampled-mask=3`，第三格未采样，不能当作恢复失败；
release 内部验证默认属性后才释放，没有 free 后采样。

正常 checkpoint3 完成日志提交／读回、BCB 核验和 PSCI 返回，后台在约 41.481 秒
完成 OrangeFox 抓取。`XnuLog.bin` 为 `committed=true/valid=true`、运行编号匹配，
正文 38974 字节，CRC32=`B586E25C`，头 CRC32=`322BEB1A`；UEFI native payload
17497 字节、CRC32=`CD99A78E`。五个启动分区、12 处 GPT 和 misc 保留区未变。
这次有独立的 XNU 提交证据，不只依赖 watcher 的 `complete` 状态。
见[r138 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r138-result.json)、
[原始 XNU 快照](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138/XnuLog.txt:457)、
[capture 完整性](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138/capture.json)和
[watcher 记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138-watch.json)。

新增 `houji_panic_recovery=1` 本轮没有触发，仍不能算作实机验证的 panic 返回。
该候选只通过 96 项 host 检查与 ARM64 object 检查，使用真实 PSCI SYSTEM_RESET；
panic 中不访问文件系统、不提交未保存日志、不改写 BCB，依赖主机事前备份并核验
的 no-wipe BCB。硬件卡死 watchdog 尚未接入，正常检查点成功不能保证所有异常都恢复。
见[panic 候选源与检查归档](${HOUJI_ARTIFACTS}/native-port/evidence/xnu-panic-recovery-r138/capture.json)。

## r139 页表检查提交及受控 panic 返回

r139 实际完成 CPU16K backing 上未启用的 GPU4K 页表构建与 1536 次物理
descriptor 审计；连同独立查找共 1554 次 CPU 读取，三个表页／四个叶页通过，
相邻 IOVA 无映射，两个 BO 已释放且无 quarantine。本轮没有激活硬件 GPU 页表、
执行 DMA、挂载 HFS 或运行桌面加速。

`XnuLog.bin` 为 `committed=true/valid=true`，运行编号
`2a0669146843459bb1d0639d07ec58c1` 匹配，正文 41846 字节、CRC32=`692CA9BB`，
头 CRC32=`283F3CA7`；native payload 17497 字节、CRC32=`E465E256`。
后台约 44.513 秒自动取回 OrangeFox，五个启动分区、12 处 GPT 及 misc 保留区未变。

本轮选中专用受控 panic 终止分支，正常上下文先核验 no-wipe BCB，再写入 armed
意图并成功提交／读回日志，之后才调用 panic。实际链接的 panic／PSCI 出口已核对，
正常 checkpoint reset 分支未选中；**快照早于故意 panic，未包含 panic 文本**。
armed 字样只能证明提交前已准备好该分支，不能单独证明后续执行，更不表示 panic
本身会保存日志或改写 BCB。该轮自动回收不覆盖硬件卡死，尚无 hardlock watchdog。

见[r139 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r139-result.json)、
[实际表审计](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/XnuLog.txt:501)、
[提交前 armed 记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/XnuLog.txt:504)、
[capture](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/capture.json)和
[watcher](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139-watch.json)。

## r140 交接只读复核及捕获标题问题

r140 已通过 UEFI power-only 交接与 XNU fresh RO 复核。Loader 只复制经 CRC／
完整性检查的 1376 字节标量记录，XNU 从 `/chosen` 的精确长度 `OSData` 重新解码，
在新建 Device 映射上按前置访问门顺序只读观察；没有 EFI 指针或 GPU 资源所有权转移。
每次读取分别保留 `attempted/returned/valid` 和原始值、首错，partial stream/bank
观察是否有效应查逐次 READ 行，不能把未读取的零值解释成冷状态。

`LOAD … before Device RO load` 只是读取前意图；只有 `returned=1/valid=1` 才证明
读取已返回且样本有效。只读映射或访问本身仍可能停止，候选没有新增可恢复异常框架，
也没有建立新的实时 USB／跨复位日志通道。原始时钟配置、软件查询和名义推导均不
称作实测频率。源码层摘要见[handoff runtime manifest](../native/gpu/xnu/handoff-runtime-manifest.json)；
实际复核 131 次读取全部返回且有效，`complete=1/observer=0/recheck=0`。
XNU 提交正文 61440 字节、CRC=`FBFE52AC`、头 CRC=`A5A9CD1C`，运行编号
`53b2d349a87d41fd8066478fc9556b6f` 匹配；首次约 43.094 秒发现自动返回。
native 正文 CRC=`E099019C` 有效，但实际 App 完整捕获标题仍为 r139，导致
监听器三次取得相同的有效快照后按轮次标题不符拒绝自动通过。原始捕获均已保留，
没有修改日志标题或伪装监听器成功；后续准备必须以固定的已验证 App／镜像／源码
证明该历史标题错配，新镜像会同时检查完整捕获标题和启动标题。
本轮没有 GPU 执行、DMA 或桌面加速结论。见[r140 实机结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r140-result.json)。

## r146–r147 外部 GMU 测试末尾记录

r146 最后有效文件快照确认启用的私有 bank2/SID5 及保存前的独立 NO SUBMISSION
复核。该快照早于保存返回和保存后复核，不能用它断言之后发生过 CM3 release。
一旦已有可能执行的事件，仍禁止为了多抓日志而打开文件写入；reset=1 本身也不
证明所有 DMA 已排空。后台监听能取回已提交的快照，不能恢复重启时丢失的末尾 RAM。

r147 在原有不安全失败出口增加四行缓存记录，停留 8 秒后沿原 panic/PSCI 返回。
`STOP1` 是 core/native 首错；`STOP2` 是最新已完成 raw observer 的状态，`SRC`
0/1 表示正常 NO SUBMISSION 保存前/后，2/3 表示失败保存前/后，4 为普通 Fresh；
`STOP3` 是最后事件的 attempted/returned、release/possible-execution/reset；
`STOP4` 是已缓存的邮箱前四字。这些行只保证送往已有屏幕日志出口，不保证已落盘，
也不构成硬件卡死 watchdog。需要一次现场观察来补齐缺失的末尾状态。
