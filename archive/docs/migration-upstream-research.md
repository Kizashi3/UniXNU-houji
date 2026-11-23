# iOS 16 迁移等待：上游记录对照

核对日期：2026-10-24。目标系统为 16.7.16 / 20H392；以下结论区分项目自己的实机记录与本机验证。

## 一加 Ace 5

仓库：`tycykp/UniXNU-OnePlus-Ace5`，核对版本
`aaa100d19f6fb14e5897a7e496edf7838d4d4e9f`。

- [迁移等待实机记录](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/hardware/ios16-startup-repair-test.json)：
  SystemAppMigrator 等安装回调，appstored 等账户服务，accountsd 又等待数据迁移。
  同时记录到 AMSFairPlayGetDeviceType 等待，但作者没有确定未完成请求的接收方。
- [只读 AMFI 信任缓存查询](https://github.com/tycykp/UniXNU-OnePlus-Ace5/commit/f76176181af55c01835c58392fc405befbe450e2)：
  精确回答官方 cdhash 目录的成员查询。实机有成功查询，迁移仍停住，因此不能视为完整修复。
- [启动兼容配置](https://github.com/tycykp/UniXNU-OnePlus-Ace5/commit/6f5b6dbfb71e21120d75af38ce43cb110cb3b24e)：
  隔离不存在的基带／音频硬件依赖并调整启动 watchdog；没有对应的 CoreLocation 等待修复。
- [Hello 实机记录](https://github.com/tycykp/UniXNU-OnePlus-Ace5/commit/07453b09a4f1268f1eb459206c99c5015458c1e1)：
  用户确认显示 Hello / Setup，迁移进程退出，Setup 启动。
  该次采用预设迁移版本状态的干净根卷，不代表所有迁移插件完成。
- [实际基线代码](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/scripts/ios16_boot_baseline.py)：
  `LastSystemVersion=20H392`，`DMUserDataDisposition={SyntheticDidUpgrade:false, buildVersion:20H392}`。
  代码明确只用于新建根卷，拒绝覆盖既有迁移历史，保留 Setup 和激活状态。
  这是有实机记录的绕过方案，不能直接当成定位服务修复移植到当前使用中的卷。

## 小米 14 的已知现象

r36 长时间采样显示 CoreLocationMigrator 等待；locationd 的请求 1203 未收到回复 1303。
r42–r45 两个 A520 核心已在 iOS 用户态运行，等待仍存在，因此增加核心或继续增加内存没有消除这个等待。
r45 观测到 fairplayd.H2 正常退出，最后缺失的打开路径属于 FeatureFlags 搜索路径。
尚未证明这些缺失项导致退出，亦未证明 locationd 的请求发往 fairplayd。

目前查阅的记录没有提供与本机 CoreLocation 请求完全匹配、已验证的修复。

## r46 临时隔离实验

用户选择先隔离定位迁移插件，后续再适配定位。仅将：

`/System/Library/DataClassMigrators/CoreLocationMigrator.migrator`

移动到搜索目录以外的：

`/System/Library/HoujiDisabled-CoreLocationMigrator.migrator`

不写迁移完成偏好，不修改 Setup／激活配置。原始文件字节、权限和原有扩展属性保留；
macOS 对离线目录重命名附加的 `com.apple.macl` 已记录。
完整安装前快照位于本机 `native-port/ios-userland/phone-after-r45/`，
SHA256 为 `18948460fe177935232e6a099230a17d9e6ac8476fc1ff448b0a94e792ae651f`。

本次只改 12 GiB 根卷中的三个 128 MiB 块，安装后核对全部 96 块，并核对五个启动分区及十二段 GPT。
安装程序的回滚选项适用于启动 iOS 之前的部分安装恢复；启动后如需恢复旧状态，应使用完整快照，
避免旧文件系统目录与新用户数据不一致。

实机结果另记，不把成功安装或启动进程视为已进入界面。

### r46 结果

首次尝试只有 UEFI 快照，XNU 日志未提交，结论不确定。同一镜像复测后取得有效的
60/60 用户态采样，用户确认苹果标志与进度条；仍有迁移 wrapper 在运行，Setup 未出现。
locationd 的后台请求仍未收到回复。因此单独隔离 CoreLocationMigrator 不足以进入界面。

完整复测结束卷另存为 `native-port/ios-userland/phone-after-r46/`，
SHA256 为 `1a343c2a79706a898dbb69711661fc493a855e95b8c1192207a4fbc8badb0fe0`。

### r47 候选：先进入界面

用户随后明确要求参考其他项目，先屏蔽阻塞启动的功能。候选从原始、尚无迁移历史的
20H392 根卷重新制作，采用上述 Ace 5 的迁移版本基线；恢复完整原始迁移插件集合。

- 暂时从 launchd 任务缓存中移除四项 CommCenter 基带启动任务。
- 将 VirtualAudio.plugin 保存在 HAL 搜索目录外，停用三个 MediaToolbox 配置的录制服务。
- 采用同版本上游的 GUI 启动 watchdog 开发配置。
- 在新卷写入对应的迁移版本基线，跳过当前阻塞的首次迁移阶段。
- 保留 Setup、mobileactivationd 和默认激活配置，不伪造激活记录。

另外采用 Ace 5 的 LaunchServices 修复：其
[实机对照](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/hardware/ios16-service-repair.json)
显示添加 `/chosen/mac-address-wifi0` 后，lsd 的 MobileGestalt 网络控制器等待消失。
本机此前缺少该属性，r47 从现有 houji 平台 UUID 和明确的开发命名空间生成稳定的
本地管理单播地址。移除新增属性后，ADT 序列化字节与原先双核 8 GiB ADT 完全一致。
该地址服务于启动身份查询，不代表硬件 MAC 读回或 Wi-Fi 联网实现。

macOS 对忽略所有者的卷挂载会隐藏实际属主，不能用该挂载下的 stat 证明数字所有权。
候选已在启用所有权的卷挂载下修正并核对 13 个新建／修改配置和目录的真实 UID/GID；
`diskutil verifyVolume` 的完整 HFSX 检查返回 0。

候选 SHA256 为 `b98cdbecbecbcd550d8953a66a7d677315ce800eaecaa6fdd68ff68b939aea79`。
安装须核对全部 96 个 128 MiB 数据块及启动/GPT 备份。此候选尚不能视为已修复迁移、
定位、基带、音频、GPU 或完整 iOS 功能，实机结果后续另记。
