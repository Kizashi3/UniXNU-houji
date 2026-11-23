# Full host graph 离线验证

生产候选位于 `native/gpu/xnu/full-host-graph/`，未在手机启用。

```sh
python3 tests/full-host-graph/run_core_tests.py
python3 tests/full-host-graph/run_native_graph_tests.py
```

需要本机保存的 GMU/SQE/AQE 原厂文件；脚本核对固定哈希，文件不复制进仓库。
两个入口分别使用 `build/core` 与 `build/native`，可并行运行。
前者运行真实C planner、内容/双页表审计与失败路径；后者运行真实Native Memory/Cpu，只替代架构与IOKit边界。
均开启ASan/UBSan。CPU准备结果不证明GPU、CP、ZAP或桌面执行。

Native对象约250KiB，opaque graph另32KiB，禁止在XNU栈上分配。
设备入口还需填完整foreign ledger、另行取得设备引用并验证实际MMIO/SMC绑定；host模型的空foreign ledger不提供设备资格。
