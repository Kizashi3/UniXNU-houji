# UniXNU houji 后续移植计划（2026-11-14）

## 已核实的起点

Ubuntu `/home/yun/mrk` 原分支 `merged-root-kernel`、提交 `27029cc`，工作区原先干净。`/tmp/console-log-1114-2253.txt` 确认 `stage=registered-not-published`、`base=0xfffffff006a45540`、`owner=com.apple.iokit.IOMobileGraphicsFamily`、`fam=1`。因此当前任务是发布已经注册的子类。

交接文档中的操作建议作为背景；以下步骤以实际代码和验证结果为准。

## 本轮实现

隔离分支：`codex/legacy-publish-20261114`。

- 保留原有 checkpoint 回调，另设带 `IOService *provider` 的发布回调。
- 同时要求 `houji-legacy-display=1` 和 `houji-legacy-publish=1`。默认不发布。
- 确认子类已注册后，依次 new、init、attach、start、setName、registerService；发布前后输出检查点。
- 仅成功执行 start/registerService 后跳过旧 HoujiFramebuffer，返回失败则保留旧路径；HID 初始化仍执行。
- start 失败时清理本后端的 timer/GOP 映射，detach/release；stop/free 中也做幂等清理。
- 将 CI 的 Legacy 编译/重链接设为必需步骤，避免该步骤失败却把旧内核当作本轮成功产物。

本地验证：两处驱动以 ARM64 Apple 目标编译为对象文件成功，像素、队列、请求校验三组既有测试通过，`git diff --check` 通过。本地 stock clang 使用 allocator builtin 的 layout-only shim；这不替代 Apple 工具链完整链接与真机验证。

## 分阶段推进

| 阶段 | 工作 | 进入下一阶段的证据 |
| --- | --- | --- |
| P1a 发布 | CI 完整编译、重链接，核对提交及符号；临时启动发布镜像 | 日志同时出现 `stage=published` 和 `Legacy published; old framebuffer skipped`；确认 IORegistry 服务可匹配、用户客户端可打开 |
| P1b 模式协商 | 跟踪 backboardd/CADisplay 模式配置与 SpringBoard 生命周期 | 有实际模式配置成功的证据；`FBSDisplayMode cannot be configured as requested` 消失，SpringBoard 连续存活至少 120 秒 |
| P2 扫描后端 | 验证 GOP 物理地址、1200×2670 尺寸、stride、像素格式、60 Hz 定时及 refresh 属性 | `stage=hardware`，尺寸/映射正确，vsync 持续推进，无 panic、泄漏或重复服务 |
| P3 首帧 | 在前述基础上启用受控 CPU swap；先单 surface、全帧 BGRA，再扩展经审计的请求类型 | `stage=cpu-present frame=…` 持续增加，屏幕出现 iOS 用户态内容；swap 完成通知与队列状态正确 |
| P4 输入与电源 | 建立 IOHIDSystem 和触摸报告链，随后实现亮灭屏、暂停恢复 | Setup 可交互，坐标/方向一致；多次亮灭屏和冷启动通过 |

P1 的“published”只表示服务已注册，不能单凭它判定模式墙已解决。338 槽布局也不代表全部硬件接口已实现；若触发未审计槽，按 panic 回溯定位并审计对应调用约定。

## 首轮启动矩阵与回退

保持已验证根卷和其余启动参数不变；每轮只改一组显示参数。

1. 对照：`houji-legacy-display=1 houji-legacy-publish=0 houji-legacy-cpu=0 houji-legacy-sync-cpu=0`。
2. 发布：`houji-legacy-display=1 houji-legacy-publish=1 houji-legacy-cpu=0 houji-legacy-sync-cpu=0`。
3. 发布与模式协商稳定后，才试 `houji-legacy-cpu=1 houji-legacy-sync-cpu=1`。

记录每个镜像的源码提交、CI run、内核 SHA256、完整启动参数、镜像 SHA256及日志路径。使用单独命名的临时启动镜像，保留 run391 镜像作为基线。发布失败先读 `publish-allocation-failed`、`publish-init-failed`、`publish-attach-failed`、`publish-start-failed`；若卡在 `publish-start`，重点检查 Apple start 内部对属性、provider 和未实现虚方法的依赖。

回退：移除 `houji-legacy-publish=1` 或设为 0，并启动基线镜像。内核异常不能保证在本轮启动中回退；旧服务的保留只覆盖正常返回的失败路径。

## 当前外部条件

本轮首次检查时，Ubuntu 的 `adb devices` 与 `fastboot devices` 都没有发现设备。完整 CI、镜像打包、临时启动及真机验收需分别记录结果；本地对象编译通过不代表已经接管显示。

VM 磁盘约剩 5.2 GiB，`/tmp` 约剩 3.0 GiB。打包前核对空间，采用新的中间目录；旧目录是否可清理由其归属和内容决定。
