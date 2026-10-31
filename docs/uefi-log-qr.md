# UEFI 日志文件与二维码标记

设备仓库提交 `d2358f8` 包含 UEFI loader 补丁。补丁让 UniXNU 在启动菜单显示固定二维码，并把 UEFI 阶段日志写入：

```text
\EFI\UniXNU\logs\boot.log
```

日志使用当前 loader 所在的 FAT 卷；如果该镜像来自固件卷，loader 会遍历可用的 `SimpleFileSystem` 卷寻找可写卷。文件写入失败只关闭文件日志，启动流程继续。

在 Ubuntu 的 UniXNU 源码树应用补丁：

```bash
cd ~/桌面/仓库/UniXNU-houji
./scripts/apply-uefi-log-qr.sh ~/UniXNU
cd ~/UniXNU
UNIXNU_EDK2=~/桌面/仓库/Mu-Silicium/Mu_Basecore package/build.sh -b DEBUG -t CLANGPDB
```

补丁已在 Ubuntu 用 EDK II AArch64 构建通过。用可写 QEMU FAT 目录启动后，已实际生成 `EFI/UniXNU/logs/boot.log`，并通过菜单及 Hello payload 检查。

## 与 GitHub Actions 内核 workflow 的关系

重新运行 `houji-kernel.yml` 会构建带持久保留内存日志补丁的 XNU kernel artifact。它不会把日志直接写入手机，也不会自动把 UEFI 补丁编进镜像。要获得完整链路，需要：

1. 运行 workflow，取得新的 XNU kernel artifact。
2. 在 Ubuntu 应用本页的 UEFI 补丁并重新构建/打包 UEFI 镜像。
3. 真机只使用 `fastboot boot` 临时启动。
4. UEFI 日志从 FAT 的 `EFI/UniXNU/logs/boot.log` 读取；XNU 停止后的日志再进入 TWRP，运行 `twrp-export-xnu-logs.sh`。

不需要清除数据、格式化 UFS，且不执行 `fastboot flash`、`erase` 或 `format`。
