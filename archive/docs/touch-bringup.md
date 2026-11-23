# 小米 14 触控适配

## 已确认的 Recovery 驱动链

OrangeFox 的 Linux 5.15 环境使用 `synaptics_tcm2`，绑定 `spi2.0`，
通过 `synaptics_tcm_touch` 输入设备 `/dev/input/event7` 上报触点。
只读信息接口识别为 S3910 A0B0-15.2、TouchCom v1、固件 4323384，
处于 Application Firmware 模式，10 点触摸，原生最大坐标 1199 × 2669。
Linux 输入轴扩大 100 倍，不能把 119999 × 266999 直接作为触控芯片坐标。

本机运行设备树的 SHA256 为
`04dad3a2a40758525e93109ef17954183500a86c7bdf77973b89e39f97723807`。
SPI SE 位于 `0xa90000`，模式 0，总线最高 15 MHz；Recovery 的时钟框架
报告功能时钟为 120 MHz，这不等于 SPI 线上以 120 MHz 传输。
MISO/MOSI/CLK/CS 分别为 GPIO48/49/50/51，reset 为 GPIO161，IRQ 为 GPIO162。
AVDD 是 pm_humu_l9 3.0 V，IOVDD 是 pm_humu_l12 1.8 V。
时钟、稳压器和 GPIO 状态均为软件读取，未经物理仪表测量。

Recovery 信息与内核日志保存在仓库外 `native-port/evidence/recovery-touch-r47`。
采集未写触控控制项、未卸载驱动，也未请求固件刷新。Recovery 的 Linux 模块
无法直接加载到 XNU，需要移植总线、TouchCom 协议以及 HID 上报链。

## 参考与边界

[UniXNU-OnePlus-Ace5 触控实现](https://github.com/tycykp/UniXNU-OnePlus-Ace5/tree/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/ios16/touch)
具有相近的 SoC、总线和触控协议，可用作协议参考。该机的 GPIO108 和 PMIC L4
供电方案与小米 14 不同，不可照搬。参考源码及许可证已按提交和文件 SHA 固定在
仓库外 `native-research/ace5-touch-reference-20261024`。

当前 XNU 的 SweetHID 已有 `sweet_hid_touch()` 数字化器上报接口，缺少物理控制器
到此接口的数据来源。坐标还需保持当前 iPhone X 画面居中的映射。

## r48 只读交接检查（已实机验证）

`houji_touch_probe=1` 仅允许读取固定的 GCC、六个 GPIO 和七个 SPI 状态寄存器。
时钟停止时不读取 SPI SE；结果缓存后由用户态采样器打印，不反复访问 MMIO。
没有 GPIO、时钟、SPI 命令、PMIC 或 DMA 写入。该检查不提供触控功能。

`native/touch/HoujiTouchProbe.h` 的回调接口只有读操作。主机 ASan／UBSan 检查覆盖
地址白名单、停止时钟的跳过路径及 23 个读取失败位置，均通过。
`scripts/apply-touch-probe.py` 以完整文件 SHA 拒绝未知或部分应用的源码状态。

触控测试前已完整保存 r47 成功启动后的 12 GiB 根卷，SHA256 为
`71fe1092ec769871b18d42b38b233a758363db771609a0d3740d64730b20ae99`。
本阶段不改变分区边界、恢复镜像或启动分区。

实机完成 36 次采样后自动返回 OrangeFox。运行编号和日志 CRC 匹配，
GCC branch=`80004000`（时钟关闭），vote=`423c0200`，
root command/config=`80000000/100000`。六个 GPIO 的配置均为 `1`，
没有启用 SPI 复用，也没有把 reset 配成输出。
探针按设计只读取 16 次，没有访问关闭时钟的 SPI SE；之后继续运行 Setup。
五个启动分区、六个 LUN 的 12 段 GPT 和 misc 保留区均未变化。

这证明当前启动链尚未完成触控硬件初始化，不证明后续协议和 HID 已能工作。
下一阶段需要建立正确的时钟、供电和引脚状态，再实际识别芯片及读取触点。

## 其他原生 iOS 参考

- [UniXNU-sheng 的分阶段触控示例](https://github.com/UniXNU/UniXNU/blob/bd127c008cdc584b83cf00eaea269e4f1adf3cc8/docs/zh/drivers/native-novatek-touch.md)：
  板级配置、GENI SPI、控制器协议和 HID 分开，逐阶段检查。
  Novatek 的固件和矩阵算法不适用于本机 Synaptics。
- [Xiaomi 17 Pro / pandora](https://github.com/UniXNU/UniXNU/blob/bd127c008cdc584b83cf00eaea269e4f1adf3cc8/docs/devices/pandora.md)：
  文档报告 iOS 16.7.16 下 Synaptics 经 GPI DMA 工作；需进一步核对其源码与本机差异。
- [Xiaomi Mi 10 / umi](https://github.com/UniXNU/UniXNU/blob/bd127c008cdc584b83cf00eaea269e4f1adf3cc8/docs/devices/umi.md)：
  ST FTS 经 GPI DMA I²C，维护者记录 GPIO 供电补齐后用户确认触控。
  其控制器和板级电源参数不适用于小米 14。

## r49 物理控制器识别成功，触点尚未启用

进一步固定并检查了 pandora 原仓库当前改名的
[data-a-live](https://github.com/ShueiTsuki/data-a-live/blob/66b556ca8c86c8830610f1458d3c39d57952f1bc/wsl/pandora_touch.c)。
它使用 S3910P，但 GPIO、电源、GCC、GPI 和 SMMU 参数不同。
本机 worker 基于 BSD-2-Clause-Patent 的 Ace 5 纯协议与 GPIO SPI 适配；
pandora 用于核对启动顺序、TouchCom 命令与 THP／触点报告差异。
未把其 APSL 内核源文件直接复制成 BSD 文件。

UEFI 在启用内核 worker 前，通过原厂 CmdDb 查询 `ldob9`／`ldob12`，
核对 VRM 地址、slave 和唯一性，使用原厂 RPMh HLOS client 2 依次申请
3000／1800 mV、HPM 模式和 enable。PMIC5 LDO HPM=7 由
[小米内核源码](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/shennong-u-oss/drivers/regulator/rpmh-regulator.c)
核对。接口版本、方法表位置及所需 wrapper 的参数寄存器也与本机原厂 PE 复核。
然后以 ClockDxe 申请三路触控时钟，SE 功能时钟 19.2 MHz。
这些请求成功不等于物理电压经过仪表测量。

内核 worker 默认关闭，只有 UEFI 全部返回成功才加 `houji_touch=1`。
它检查 SE 空闲、DMA 接口不活动、本机 AP GPI 实例 2／3 没有运行 SE4，
以及六个引脚归属，再临时切换为 GPIO SPI。复位时序为 10 ms 低、200 ms 等待。
先核对 S3910、固件 4323384、1199 × 2669 和 10 点，再安装并读回精确触点配置。
只有通过校验的真实报告才调用 SweetHID；没有模拟触控或触控固件刷新。
失败时释放触点、恢复引脚并保留 iOS 运行。

主机 ASan／UBSan 已检查双触点边界与抬起、无效帧不改状态、配置读回、
TouchCom 标记／填充以及 SPI mode 0 边沿。内核编译、原有双核汇编检查、
镜像检查及 51 个错误输入拒绝检查通过；r49 临时启动已返回 Booting OKAY。
用户再次确认 Hello 可显示、触摸无反应，随后手动返回 Recovery。
日志运行编号和 CRC 校验通过。原厂接口查询得到 ldob9=`0x41500`、
ldob12=`0x40900`，六个电源请求及三路时钟均返回 Success。
XNU 读到 GCC branch=`4000`、vote=`463c0200`，SPI firmware=`102`、
interface=`1`、status=`0`、DMA interface=`0`。GPI 和引脚检查通过，
GPIO SPI 已真实读到并核对 S3910 应用固件 4323384。

worker 停在 stage 3 / error 142：过严的 advertised maximum-write 检查。
该检查发生在触点配置和 HID 上报之前，最终 frames/events 均为 0。
五个启动分区、12 段 GPT 和 misc 保留区均未变化。

## r50 写入长度限制修正

参考固定版本的 Synaptics `syna_tcm_v1_set_max_rw_size()`：正值取设备和
主机限制的较小者；设备字段为 0 时保留配置的主机限制。
GPIO transport 的固定包缓冲可容纳 515 字节，消息内容仍最多 512 字节；
不采用不受限长度。新增 advertised/effective limit 和配置长度的持久计数，
避免早期 IOLog 被覆盖后无法知道停止原因。Recovery 原日志还确认 CRC=no、RC=no。

r50 完成 48 次采样并自动返回 Recovery。设备声明最大写入 1024 字节，
主机安全上限取 515；随后 Get Application Info 遇到当前接收器不支持的包，
stage 3 / error 163，触点帧和 HID 事件均为零。本轮用户只见苹果标志，
最后显示计数停在 swaps=10 / presents=7，不能把进程存活等同于界面呈现。

## r51 大帧排空

将非触点的 unsolicited 大帧在固定 8199 字节 BSS 缓冲中接收，最多 8192 字节
内容，逐一校验 continuation 和 EOM 后丢弃，不放在内核线程栈，也不解释为触点。
小报告仍限制为 512 字节。新增最后包头、丢弃帧数持久记录。

实机成功丢弃 1 帧大报告，Get Application Info 和 128 字节配置读取成功。
自定义配置的严格读回比对失败，stage 4 / error 240。用户确认回到 Hello，
最后显示计数 swaps=1626 / presents=1014；触点帧仍为零。自动 Recovery 返回，
日志运行编号／CRC、启动分区、GPT 和 misc 保留区校验通过。

## r52 芯片默认报告描述符（物理触控成功）

按 pandora 的原生 iOS 路径读取芯片原有配置，去掉 SET_TOUCH_REPORT_CONFIG。
新增有界的单循环位字段解释器，支持 active/all object 遍历、字节对齐、
非字节对齐的坐标、显式对象索引及有效触点数。只接受 finger/glove，
截断、重复编号、越界坐标和非法结构不更新已有触点状态。
解析出的真实字段再交给既有 contact state decoder 与 SweetHID。

ASan／UBSan 覆盖普通双触点、4/12 位混合字段、零触点、截断和非法循环。
完整配置字节会反复写入持久日志。编译、双核汇编与镜像检查通过。
用户已确认 Hello／设置界面可以实际操作。持久日志的运行编号和 CRC 校验通过，
最终 stage=5、error=0、frames=78、SweetHID 调用=78、IRQ polls=79，
丢弃 3 帧非触点报告。调用计数不等于独立测得的 IOHID 分发计数，
但本轮用户的实际操作同时确认了界面接收。

默认配置为 128 字节：全局元数据 144 位，每个触点 72 位，包含 ID、类型、
16 位 X／Y／Z 和 8 位宽高。未改写控制器固件，也未安装自定义报告配置。
五个启动分区、12 段 GPT、misc 保留区均与基线一致。成功运行后的完整 12 GiB
系统卷另存为 `phone-after-r52/ios16-phone.hfsx`，完整哈希与 96 个实机块匹配：
`3aaa1292ac91cba04b17d6978f63ad8053ab30956ae7f60edfc59c90c7c81437`。
