# 许可证说明

这是混合许可证的源码快照；本说明不替代或重新许可文件原有条款。

- 带 SPDX 标识的文件按各自标识及原版权声明使用。
- `archive/native/ufs-read`、`archive/native/ufs-root` 及内核中的对应实现保留原 BSD-2-Clause LICENSE。
- Touch/Ace5Gmu 与 AdrenoFirmware 保留 BSD-2-Clause-Patent 声明及许可证文本。
- ArmSmmu4K 保留其 LICENSE 和固定来源清单。
- UEFI 覆盖层保留源文件头部声明和 `uefi/LICENSE`；Mu-Silicium/Mu 依赖须保留各自许可证。
- XNU 补丁和公开源码覆盖层继续适用文件原有版权和许可证，APSL 文本见 `kernel/APPLE_LICENSE`。HFS、HID、libpthread、BearSSL 等代码保留各自声明。
- AdrenoMetal、NativeAdreno 和 AdrenoPM4 的许可保留在 `graphics/metal/AdrenoMetal/LICENSE`、`graphics/include/*LICENSE` 及原文件头中。
- metal2vulkan 的许可文本位于 `graphics/runtime/LICENSE*`，其中各组件的 LGPL/GPL 适用范围应结合对应上游文件与 Cargo 配置判断。
- Mesa 的许可说明见 `graphics/turnip/LICENSE.rst`；新增和修改的后端文件继续保留原声明。
- 没有明确许可标识的文件需要结合原始来源核对；本次源码上传不视为已完成逐文件许可证审计。

本仓库不附带 iOS 系统镜像、厂商固件、SDK、KDK 或设备分区备份。`kernel/firmware-inputs.json` 仅记录外部输入的长度和哈希，未包含其字节。
