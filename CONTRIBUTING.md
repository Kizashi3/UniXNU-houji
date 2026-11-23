# 贡献指南

改动以 `sources.lock.json` 指向的有效覆盖层和补丁为准。`archive/` 是历史参考，不要只修改归档副本来修复当前实现。

1. 说明实际故障、适用硬件与预期行为，尽量附最小复现。
2. 保留原版权和许可证，记录借鉴代码的仓库及提交。
3. 运行 `python3 tools/run-host-checks.py`；更新源码后同步 `source-manifest.json`，再运行源码检查。
4. 涉及硬件的改动需提供对应实机证据。将请求频率与实测频率、软件节拍与实际 FPS 分别报告。
5. 不提交 IPSW、系统卷、厂商固件、分区备份、SDK、生成的二进制或个人设备信息。

提交信息遵循 `@commitlint/config-conventional`，例如：

```text
fix(gpu): preserve reused buffers during retirement
feat(input): normalize system keyboard geometry
docs: clarify hardware validation scope
```

源码清单可用 `python3 tools/update-source-manifest.py` 更新。变更清单是发布校验，不替代代码审查。
