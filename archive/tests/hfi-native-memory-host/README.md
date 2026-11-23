# Houji firmware memory Native host test

最终结果：**2743 个边界／失败 profile，known-gaps=0，ASan/UBSan 通过**。

这是纯离线 CPU 内存准备测试。真实 production `.inc`、NativeAdrenoMemory、NativeAdrenoFirmware、SHA-256、C bridge 与原有 firmware/table planner 被编译执行；不接触设备、固件执行、SMC、MMIO、TTBR 或 stream。没有修改 P、实际 XNU、分支或依赖。

## 复现

```sh
python3 /tmp/houji-fw-native-test/run_native_test.py
```

可选参数：`--repo` 指向 P，`--bridge` 指向 C ABI 候选目录，`--generated` 指向既有私有 firmware header 目录。默认分别为：

```text
${HOUJI_PORT_ROOT}
/tmp/houji-hfi-inactive-candidate
${HOUJI_ARTIFACTS}/native-port/native-ios-candidate/r149-generated
```

只使用已经存在的 `HoujiGmuFirmwareImage.h`，没有下载或增加网络二进制。数组长度 78588 字节，SHA-256：

```text
9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72
```

`build/snapshot` 保存本轮输入副本；`build/verification.json` 记录所有原始输入 SHA-256、完整编译／运行命令、架构替换边界和结果。`build/test-output.txt` 为本轮实际输出。运行器会覆盖自己的 build 目录。`pre-content-verifier-evidence` 另存接入内容验证前准确复现 5 个 HFI 缺口的诊断输出及源 hash；它不是最终通过证据。

## 边界

- 从现有 `Adreno740/tests/check_page_geometry.py` 的 Python AST 提取原始 `prefix` 字符串，复用 `XnuMemoryFixture.h`。
- 只替换真实 MRS、DC、DSB、AT 和 IOKit 分配／pmap 边界。CPU.cpp 的架构指令替换为可观测 peer，业务判断原样保留。真实 `.inc`、Memory.cpp、Firmware.cpp、Sha256.cpp、C bridge 和 vendor C sources 原样复制编译。
- fixture 仅增加第 N 次 descriptor allocation 失败边界。AT 从 fixture 实际 descriptor 地址、物理段和 pmap 属性独立计算 PAR，不从 production `info` 反取预期 PA／属性。alias 使用不可解引用的独立虚拟地址，只模拟 AT。
- Native fixture 使用 C++17 编译，因为上游 fixture 有 inline globals。C bridge 的独立 suite 另覆盖纯 C11、C++14 链接和 standalone pedantic C++14 header。
- cache/DC/DSB/AT 是 host peer；本测试不能代替实际 CPU/MMU 属性与屏障执行证据。`CPU-published` 只表示 CPU PoC，`DMA-eligible=0`，不会安装设备映射。

## 通过范围

基线 CPU16K、36 位高 PA（从 `0x8c5d10000` 起），精确 8 ranges + table，9 个独立 BO：

| BO | GPU4K pages | logical bytes | CPU owned bytes | descriptor |
| --- | ---: | ---: | ---: | --- |
| FW0 | 19 | 77824 | 81920 | WB |
| FW1 | 27 | 110592 | 114688 | WB |
| FW2 | 19 | 77824 | 81920 | WB |
| FW3 | 37 | 151552 | 163840 | WB |
| FW4 | 2 | 8192 | 16384 | WB |
| HFI | 18 | 73728 | 81920 | NC |
| log | 16 | 65536 | 65536 | NC |
| VRB | 1 | 4096 | 16384 | NC |
| table | 10 | 40960 | 49152 | WB |
| 合计 | 149 | 610304 (596 KiB) | 671744 (656 KiB) | 41 CPU pages |

每次 Own 检查完整 owned backing 中每个 GPU4K 的 descriptor 和 known-aperture alias R/W AT。基线共 2624 AT，其中 alias 1312；6 张实际 inactive table、139 leaves、3072 次实际 descriptor read，17 个空 HFI queue，FW records15／reservations5，RAM payload77808／TCM deferred540。所有 logical holes、ring／padding、log／VRB、table spare 和 CPU rounded tail 均验证为期望内容／零。全部 device references 为 0，不自动释放成功或不确定拥有的 BO，once 再调用不重做准备。

2743 profiles 包括：

- 禁用 bootarg 和三个 recovery/root/log gate；9 个 allocation 位置；10 个 NC pmap 属性写位置。
- 全部 2624 个 descriptor／alias AT 的逐次失败；8 个 PAR 属性破坏位置；6 个 WB CPU publish 的真实维护失败。
- 8 个有 rounded tail 的 BO；actual root table 和 unused table page 篡改。
- 61 个发布边界内容篡改：FW payload／holes，HFI 全局 header、全部 17 个 queue header 和 ring、cursor／logical padding，log／VRB。对应内容码 2/3/4/5/6；全部拒绝 complete 并保留 quarantine。
- descriptor NC + inactive alias WB 可以如实通过；alias Device、未知 Normal 属性、PA 错、R/W 属性不一致，以及 physical-aperture 起点／长度／尾端越界均拒绝。
- 新内容 API 的 size／alignment／length／null／output-alias／storage-copy／uninitialized／not-prepared guards，正常只读调用不改 RAM、state、callbacks、AT 或 barrier 数量。
- 真实 Native firmware SHA 验证拒绝错误 payload 和截断长度。

## 最终源版本

```text
HoujiGpuFirmwareMemoryProbe.inc
0868cf841dcdbbf5c2db864beca93e2ae66646bce05a822bcba6d8c9dd0db247
houji_hfi_inactive.c
d76a434598e6fd4d0f17529bf7cd4622245db8e2a1eaf0eaf837a4fa89e85ada
houji_hfi_inactive.h
0963b22919a8173ded121154a5ad33435e40f5659f1af2b98d974dd1c2b2fa39
test_native_peer.cpp
ce6fac0dfcfde0fd48863543958fffe6d08020dfe102983432d85c3d250eb81a
run_native_test.py
0da2406d62d9835e291262c19257b227dafc068b5375485dbfb2b24876567e3a
build/verification.json
84ee3d3aa3e32d13ec8eceecea16aef0e09f19e2579c054498613d2441605bc1
```

## 只读 review

本轮发现的三个实际缺口均已由 root 修复并用最新 hash 重编：known-aperture alias 缺少 bounded AT；最终 audit 未复核发布后的 FW/HFI/log/VRB；内容验证尚未执行时日志可能默认呈现成功。最终版本显式声明 phystokv/gPhys，先验证整个 owned physical aperture，再逐 4K 只读 AT；内容 API 复用两个现有 parser/planner，只读 RAM；`content_attempted` 和初始 `UINT32_MAX` 区分尚未执行与成功。

对最终 `.inc` 没有剩余必修 finding。成功只代表 inactive CPU preparation；已观察到的 WB physical alias 不构成 DMA 资格，正式 firmware/HFI 执行仍需单独的 alias/cache ownership、SCM、设备页表与 stream 确权门。成功 BO 和失败 quarantine 均保持拥有至显式 reset。
