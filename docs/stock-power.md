# 小米 14 原厂温控与交互调度核对

2026-10-31 从这台 houji 的 vendor/odm 分区只读提取配置，版本为
`OS3.0.307.0.WNCCNXM`。这是手机保留的原厂配置，不代表已在 XNU 执行原厂服务，
也不是其他机型的通用调参。临时 EROFS 挂载已卸载，没有修改这两个分区。
原始文件、解码副本、哈希和 Recovery 读数仅保留在私有验证目录。

## 原厂实际做了什么

| 输入 | 已核对的规则 | 移植边界 |
| --- | --- | --- |
| `thermal-map.conf` | 普通模式编号 0 对应 `thermal-normal.conf`；性能、游戏、相机等另有配置 | 不能把性能/不限频模式当作默认模式 |
| ODM 普通模式 | `VIRTUAL-SENSOR0` 使用 `pa_therm0`、`quiet_therm`、`charger_therm0`、`cpu_therm`、`battery`、`wifi_therm` 六路输入，每秒采样；还存在另一套充电器模型 | 不是 CPU/GPU TSENS 结温，不能用 95°C 结温替换其 25–50°C 阈值 |
| 普通模式 CPU | 第一档 25°C 对应小核 2035200 kHz、其余三簇 2630400 kHz；随后按各簇独立的触发/解除阈值继续收紧 | 这些是虚拟温度模型中的目标值，不能凭 Recovery 单次温度固定到整个 iOS 会话 |
| 普通模式 GPU | 配置给 `gpu` 的目标为 cooling state 2，触发/解除值为 15000/13000 | Recovery 未注册该 GPU cooling device，尚未验证 state 到 KGSL/HFI 的映射；没有把数字 2 直接当作 HFI level 2 |
| 小米 `perfboostselection.xml` | 针对 Settings 等白名单应用，启动覆盖项实际 `Timeout=600` ms；XML 注释仍写 2 秒，以字段值为准 | Android 包名和 Activity 回调不能当作 iOS 的应用启动通知 |
| 通用 `perfboostsconfig.xml` | pineapple 主启动项 2000 ms、Activity 启动 600 ms，预滚动项 80/100 ms；有独立滚动与恢复项 | 区分短时交互提示、负载调频和温控限频；不是持续保持最高频率 |
| 原厂桌面 120 Hz 滑动覆盖项 | 小核/大核/超大核/次大核最低请求为 1000/1190/1000/1190 MHz，并附调度器、总线与 L3 提示 | 这是请求值，仍需查有效 LUT；`Fps=120` 是配置选择条件，不是实际帧率证明 |

本机 Recovery 中能读到上述六路温度，说明传感器和原厂 Linux 通路存在。
PMIC 的 `cpu_therm` 是板上热敏电阻，和 `cpu-*-*-*` TSENS 不是同一传感器。
两个 `powerhint.xml` 及 `targetconfig.xml` 也已核对；不能只复制其中一个 XML 就得到完整原厂调度。

编码配置的离线解码参考
[mi-thermal-crypt 的固定源码](https://github.com/adithya2306/mi-thermal-crypt/blob/d4f518f76166d0a0c7d25d7a43fb50548065f056/mi-thermal-crypt.c)，
验证了 AES 填充和可打印 UTF-8。`perf/thermal-boost.conf` 不符合该编码，未将其当作已读懂的规则。
未运行下载的程序，也没有将解码配置写回手机。

## 当前落地范围

`HoujiDvfsPolicy.h` 原先在没有触控和渲染提示时，也会为最近有负载的性能域保留
50% 工厂上限的频率下限。轻量后台负载持续存在时，这个保底不会消失。
本次去掉该分支：提示过期后只按负载决定频率；持续高负载仍可立即升到有效上限。
触控/动画期间的 60% 下限、空闲域退出、降频滞后和 TSENS 优先级保持原有行为。
这是参照原厂“提示有生命周期、普通负载独立调频”的窄范围修正，**不是完整原厂调度移植**。

主机回归覆盖提示过期后的持续轻负载、重新触控、饱和负载和空闲域。
r255 已实测预升频 14 次、空闲期 CPU 请求下降；用户感到发热减少，但动画仍卡，
不能宣称帧率已改善。完整结果见[设备测试](device-tests.md)。
r253 已封存为未启动的对照镜像；它的触控预升频来自 sheng，不能改称原厂小米策略。

## 完整温控仍缺的执行链

1. [houji 官方 DTS](https://github.com/MiCode/kernel_devicetree/blob/d28b3972becd282c19d9d5b1bbd4ece3c6ad3989/qcom/houji-sm8650.dtsi)
   指定板级热敏电阻由 PMK8550 的 ADC5 Gen3/SDAM 通路读取，涉及 PM8550 和 PM8550B 通道。
   [同版本体系的 ADC 驱动](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/317e609aa4fb956c3aff565b62215e5a8041ca0c/drivers/iio/adc/qcom-spmi-adc5-gen3.c)
   需要 SPMI 所有权、请求握手、转换完成、错误检查、校准换算与状态确认，不能只读一个寄存器当成新温度。
2. 电池温度需要现有[设备树核对](device-tree.md#电量充电与音频的接入输入)中记录的 PMIC GLINK/ADSP 通路。
   当前 XNU 仍未接通这两部分，不能使用 Recovery 遗留读数、常量或 TSENS 冒充实时机身温度。
3. 接通后先验证各路单位、新鲜度和失效处理，再接普通模式的虚拟传感器及分档解除逻辑。
   最后合并 CPU/GPU 限频、亮度/刷新率、充电限制；性能提示不得覆盖温控上限。

目前只保留已工作的 TSENS 保护；没有关闭温控、提高温度阈值或盲写原厂 cooling state。
120 帧还取决于 CPU 工作量、GPU 渲染、显示完成与面板刷新链，原厂电源配置不能单独解决粉色和乱码。
