# Run392 后的 provider 修复

修复目标：阻止 Legacy 在 `dot-pitch` 查询（第 188 槽）中解引用空的 AppleARMIODevice provider，并建立真实类型的显示 nub。

## 二进制审计

审计对象：`/home/yun/kernel-run392.macho`，SHA256 `c2286c4c74a2e223031b2459a5c7559035fdb52f184b4f17c3789d2d99dcdfc9`。

- Legacy start 对 provider 做 AppleARMIODevice 转换，将结果写入 `this+5096`；转换失败只告警后继续。
- 原版 AppleARMIODevice 构造代码 `0xfffffff0045f7b6c` 引用类名 `0xfffffff003dd719f`，记录实例大小 `0xd8`。分配函数 `0xfffffff0045f7ba0` 确实分配并构造实例，类非抽象。
- 实例虚表起点 `0xfffffff005c7df38`。第 21/86/87/14 槽分别指向当前源内核的 IOService::init/start/stop/free，地址为 `0xfffffff0078aef48`、`0xfffffff0078aef14`、`0xfffffff0078aef1c`、`0xfffffff0078af000`。
- 对应代码属于预链接 `com.apple.driver.AppleARMPlatform`。审计文件在 Ubuntu `/home/yun/display-analysis/armprovider.dis`。

## 实现

1. 仅当 display/publish 两个开关均为 1 时，通过 OSMetaClass 分配原版 AppleARMIODevice。如果其模块未加载则尝试加载 AppleARMPlatform；分配失败时使用原来的 generic nub。
2. 复用既有 display0 的 compatible、device_type、canvas 尺寸、DT 和 service 父节点；原版实例通过虚调用使用其已审计的 IOService 生命周期。
3. Legacy 发布前严格检查 `metaCast("AppleARMIODevice")`。不满足则停止 Legacy 发布，保留旧 framebuffer。
4. Apple Legacy start 返回成功后，核对其 `this+5096` 是否等于传入 provider。不一致则停止、detach、释放该服务，不主动 registerService。
5. 新增 client-open 记录及发布 checkpoint，让用户态打开时重新记录发布状态。

两处 ARM64 驱动对象编译检查通过；像素、队列、请求三组既有测试通过。stock clang 的 layout-only allocator builtin shim 不替代 Apple CI 工具链与真机验证。

## 下一轮验收

CPU swap 保持关闭。检查 `provider allocated class=AppleARMIODevice size=216`、`stage=provider-validated`、`stage=published`、`stage=client-open rc=0`。随后确认第 188 槽不再发生同一空指针 panic，并独立检查模式配置和 SpringBoard 生命周期。

如果出现 `native provider unavailable` 或 `publish-provider-incompatible`，应继续定位模块/元类加载，不能视作修复通过。即使成功发布，也不代表模式配置和首帧已通过。
