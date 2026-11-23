# 离线跳过首次设置

参考 UniXNU 官方的[跳过首次设置说明](https://github.com/UniXNU/UniXNU/blob/bd127c008cdc584b83cf00eaea269e4f1adf3cc8/docs/zh/guide/skip-setup.md)
和[偏好合并脚本](https://github.com/UniXNU/UniXNU/blob/bd127c008cdc584b83cf00eaea269e4f1adf3cc8/scripts/seed-data-skip-setup.py)。
原脚本针对 APFS Data seed；本机是完整 HFSX 根卷，因此只采用其偏好合并规则，
没有对本机镜像直接运行 APFS seed 脚本。

## r53 候选

基于物理触控成功后的完整 r52 系统卷副本，合并修改
`private/var/mobile/Library/Preferences` 下的五个 plist：

- `com.apple.purplebuddy`：完成设置和全部步骤，SetupVersion=11，关闭 daemonize。
- `com.apple.purplebuddy.notbackedup`：关闭后续 MiniBuddy 提示。
- `com.apple.managedconfiguration.notbackedup`：关闭云配置可用标志。
- `com.apple.springboard`：沿用官方开发 watchdog 配置，关闭强制云配置和自动息屏。
- `com.apple.migration`：保留本机 iOS 16.7.16 的构建号 `20H392`，而非参考脚本的 iOS 17 构建号。

保留未知偏好字段；字典按键合并。五个文件最终 UID/GID 均为 501/501、权限 0600。
使用 owners-on 挂载，卸载后再次只读挂载，确认权限和文件内容确实持久化。
`diskutil verifyVolume` 的 HFS 检查通过。保留 Setup.app、mobileactivationd，
不写入激活记录，本轮不改变 Apple ADT 的生产／安全属性。

修改前完整 12 GiB 镜像：
`3aaa1292ac91cba04b17d6978f63ad8053ab30956ae7f60edfc59c90c7c81437`。
候选镜像：
`3368281fb273d04c1e2945ebe28ed143eb89a7268113b96877e27181ff15ebfc`。
128 MiB 分块仅 0、1、94 发生变化。仓库外 `native-port/ios-userland/skip-setup-r53`
保留偏好原文件、合并清单、文件系统检查结果、完整候选和逐块差异。

`scripts/install-skip-setup.py` 固定上述前后镜像、全部 96 个块和 3 个变更块。
安装前验证恢复环境、未挂载的 userdata、完整实机前像、五个启动分区和十二段 GPT；
写入后逐块直接读回并复核完整 96 块及启动分区、GPT、misc。
启动前可用 `--rollback` 回滚这三个块；**iOS 再次运行后不得仅回滚这三个块**，
应使用完整 r52 系统卷副本，避免把旧 HFS 目录与新用户数据混用。

写入后的完整 96 块读回一致，五个启动分区、十二段 GPT 和完整 misc 均未变化。
r53 内核和镜像构建、双核汇编检查及 52 项错误输入拒绝检查通过，
已使用 `fastboot boot` 临时启动；触控集成的七个源码与 r52 成功快照逐字节相同。

这项配置只用于越过首次设置。它不提供 Wi-Fi、网络连接或 Apple 在线服务。
r53 用户确认仍在 Setup；照片显示“连接 Mac 或装有 iTunes 的 PC”。
自动返回 OrangeFox，日志运行编号及 CRC 有效。偏好单独修改尚未进入桌面，
下一步核对运行后偏好，并以官方四字段开发板 ADT 做独立验证。


## r54 开发板设备树验证

r53 运行后的完整系统卷 SHA256：
`7184bc6371d928227f3c7b37c28d8c588a73a5c739ecc5ac4acd7d5e9c9e6bf4`。
原始不可变备份与实机全部 96 个块一致。只读挂载需要回放 HFS 日志，
因此仅对本地 inspection 副本作读写挂载；原备份和手机均未因此修改。
副本核对五个偏好文件均保留预期标志及 501/501 权限。

`scripts/make-development-adt.py` 在成功 r52 ADT 的副本中，仅加入官方说明的
四个 `/chosen` little-endian u32 属性：
`certificate-production-status=0`、`effective-production-status-ap=0`、
`certificate-security-mode=1`、`effective-security-mode-sep=1`。
删除这四个新增字段后，序列化结果与原始 ADT 逐字节一致。
未添加 ECID、未改变平台 UUID、CPU、内存、显示及触控节点，未创建激活记录。

候选 ADT SHA256：
`22797687bb4d9e3d0df71c7034a5e7961daca563796c3f8dfa4cd97ad95f2541`。
本轮未重新写系统卷。用户实机确认：**已到桌面，设置可操作**。
因此 r53 偏好完成标志加 r54 开发板 tuple 的组合已能在本机离线越过 Setup。
没有实现 Wi-Fi，也不代表 Apple 在线服务已经可用。

实机返回后日志运行编号及 CRC 校验通过；触控 stage=5、error=0，
82 个物理报告、82 次 SweetHID 调用。五个启动分区、十二段 GPT 和 misc 保留区
均未变化。r54 镜像 SHA256：
`1c9349cb2ebed4e5a098dc9f9d3db8e9f8b3af1dcec82d595d9d32fb493fa712`。


## 成功基线与备份

r54 完成后只读保存了完整 12 GiB 手机系统卷，全部 96 块与实机一致，
保存前后设备块索引稳定：
`909c95e9586cf74ec2f957c95bc7dea66a3196f4b7ba6bc09f01f48430bbb130`。
仓库外 `native-port/ios-userland/phone-after-r54/ios16-phone.hfsx` 为不可变副本。
`native-port/native-ios-candidate/known-good-r54.json` 索引镜像、内核、ADT、
系统卷、源码清单和实机结果。r52、r53 全量快照及五个偏好原文件也保留。
恢复根卷时须使用同一时点的完整 12 GiB 镜像，不能在用户态运行后仅回滚旧目录块。

当前手机已按诊断计划回到 OrangeFox。这是 48 次采样后的主动恢复返回，
不是桌面启动失败。仍使用临时 `fastboot boot`，不从 Android 启动或格式化 data。
