# 恢复原版系统应用

项目提供离线迁移和一次性注册工具，将 `/private/var/staged_system_apps` 中的
32 个原版系统应用恢复到 `/Applications`。原版应用由开发者自行准备，仓库不分发其文件。
已实机确认全部应用注册，以及计算器、时钟、图书和音乐的界面打开；完整功能仍受网络、
音频和图形兼容性限制。照片图库初始化失败的修复尚待设备验证。

## 参考与本机处理

[UniXNU PR #41](https://github.com/UniXNU/UniXNU/pull/41) 已合并 staged apps 的恢复：
在挂载 Data 前后搬运暂存应用，以便系统安装服务继续处理。本机没有应用目录被 Data
挂载遮住的问题，因此不直接移植 sheng 的 vnode 补丁。
[ios-sailfish](https://github.com/joranv1/ios-sailfish) 的 iOS 16 路径记录了首次安装失败，
通过迁移到 `/Applications` 恢复。本机采用这个目录方案，再调用系统的 Launch Services
重建接口；调用方式参考固定版本的
[Procursus uicache](https://github.com/ProcursusTeam/uikittools-ng/blob/6b84d79261186d070b54efa9a39850f108b52239/uicache.m)。

- `tools/restore-system-apps.py` 只操作离线副本，限定 OS build 和 32 个原版 bundle ID。
  完整预检后在同一文件系统内重命名，核对每个文件的字节、inode 和数字所有者；失败时撤回
  已完成的重命名。应用内容、签名、硬件能力标签不修改。
- `tools/build-system-apps.py` 构建 arm64 iOS 16 注册程序并绑定源码身份。
  `tools/register-system-apps.py` 添加独立启动项，同时更新已有 launchd 缓存；其他启动项保留。
  镜像打包者还必须验证新增文件的数字 root 所有权，工具本身不访问手机或提权。
- 注册程序以 mobile 运行，等待启动服务 8 秒，然后仅请求系统/内部应用数据库重建，
  不重建用户应用。90 秒超时退出，无 KeepAlive；成功后逐个验证注册地址和状态，全部通过
  才写完成标记，后续启动立即退出。保留现有应用数据与图标布局，不主动删除数据库。
- `UniXNU-system-apps.log` 记录每个应用的注册结果，离线日志采集器会保存本轮新增或变化内容。

主机检查覆盖目录冲突、内容/所有者保留、回滚、幂等及 launchd 缓存保留；它们不能证明
应用能在设备上打开。r284 实机记录为 `registered=32 expected=32`，完成标记匹配当前
源码身份；用户确认图标出现，计算器和时钟可打开。回收卷再次核对了全部原版 bundle，
字节、inode 和数字所有者均保持一致，暂存目录已空。其余应用的完整功能尚未验证；恢复
应用不等于启用尚未完成的网络、音频、传感器或 Metal 接口。

## 应用私有动态库

r284 记录到两次 BooksWidgetExtension 启动失败：BookCore 实际存在于应用的 Frameworks
目录，但 dyld 报告路径策略禁止 `@` 展开。本机 iOS 16 dyld 的实际调用为
`__mac_syscall("AMFI", 0x5a, {input, output_pointer})`，失败时返回零权限；原内核的
签名钩子注册名为 `SWEET AMFI`，没有对应的查询回调。
[Apple dyld-1042.1](https://github.com/apple-oss-distributions/dyld/blob/dyld-1042.1/dyld/DyldProcessConfig.cpp)
将输出 bit 0 定义为 `ALLOW_AT_PATH`。Bergamota 的
[iOS 18 调研](https://github.com/ry-diffusion/Bergamota/blob/develop/docs/IOS18_PORT.md)
也记录了该接口缺失的表现，但它的多权限、arm64e 方案未直接采用。

候选将策略名对齐 `AMFI` 并仅处理 `0x5a`：只对这 32 个系统 bundle 内的已标记平台程序
返回路径展开位；setugid、非零输入标志、非规范路径、其他程序及未知操作仍拒绝。
现有签名/页校验不变，不允许环境变量覆盖、库插入或自定义共享缓存。主机检查直接编译
实际回调，覆盖边界、路径拒绝和用户地址复制失败。r285 用户确认图书可打开；本轮没有
新增 `@` 路径拒绝报告，但终态内核日志未保留早期成功调用，不能量化回调次数。

## 媒体库与照片授权

r285 的三份 Music 崩溃均发生在 `MPMediaLibrary` 将空数据库路径转换为 C++ 字符串时。
回收卷中媒体数据库存在，副本的 SQLite 完整性检查通过。进一步读取统一日志可见：
TCC 根据原版 `com.apple.private.tcc.allow` 批准 `kTCCServiceMediaLibrary`，随后
沙箱扩展返回失败，TCC 把回复改成错误；Music 因而跳过资料库初始化。
这不是本轮 GPU 崩溃，也不需要修改 TCC 数据库或伪造音乐账号。

`HoujiTccCompatibility.h` 补上既有无沙箱模式的原生返回约定：iOS 16 自带
`libsystem_sandbox` 在 no-sandbox 请求中返回 `invalid` 字符串，消费端将它识别为
无需内核扩展的句柄 0。r286 错将媒体库请求按 generic 类型接入，设备仍在原位置崩溃。
进一步核对原版 tccd 的服务配置与调用，generic 仅用于相机、麦克风；媒体库实际调用
`sandbox_extension_issue_file(class, "/", 0)`，对应 op 5 的类型 0。
当前实现只对平台进程 tccd、精确 MediaLibrary 或 Photos 类、路径 `/`、无标志且无
目标进程的文件请求返回原生值。其他路径/类（包括 PhotosAdd）、generic/Mach 扩展、
定向请求、非平台或 setugid 调用仍失败。
TCC 先前的授权判断保留；此兼容处理没有实现沙箱隔离，也不能表述为完整的访问凭据系统。
实际回调的主机检查覆盖 ABI、身份、类名、资源路径、标志、目标、复制错误及输出边界。
命中计数进入固定日志前缀，避免终态消息覆盖。r287 已验证该请求实际命中两次，
本轮唯一新增启动的日志没有原先的扩展发放失败及 `app not authorized`，也没有新增
Music 崩溃报告；用户确认音乐能显示完整界面并停留。这只验证打开界面，尚未验证播放。

照片兼容的依据来自 r293：`assetsd` 因 `kTCCServicePhotos` 扩展发放失败反复退出，
MobileSlideShow 随后记录图库加载错误 `com.apple.photos.error Code=45002`，用户看到黑屏。
目标 iOS 16 tccd 的服务定义及调用已核对：Photos 同样使用
`sandbox_extension_issue_file("com.apple.tcc.kTCCServicePhotos", "/", 0)`，在授权成功后执行。
因此只扩展此精确类名，保持既有 ABI 和身份检查，分别统计音乐和照片命中次数。
主机检查已覆盖两类请求及相似名称拒绝；尚不能据此确认黑屏已消失，也不将其视为动画或
紫色阴影修复。设备复测需确认图库界面、后台服务存活，以及原错误是否消失。

## 已知图形问题

用户同时报告提醒事项桌面图标只剩顶部一条线。原版 `Assets.car` 在主机解码为完整的
180×180 图标，原始资源未损坏。r287 用户反馈图标恢复；r286/r287 未更改图形库，
因此将其记录为间歇性异常，不能据此标记渲染问题已解决。
用户还指出设置的开启动画比其他应用更卡；应比较不同应用的启动等待与共用的合成路径，
当前证据不能将两者全部归因于 GPU。
