# 状态栏与显示历史

## 小米 14 状态栏

适配目标为 iOS 16.7.16、1200 × 2670 原生像素、400 × 890 逻辑尺寸及 3 倍缩放。
系统原有 `_UIStatusBarVisualProvider_FixedSplit` 按 iPhone 的刘海分区计算时钟和电量位置。
`userland/display/HoujiStatusBarGeometry.h` 调整普通竖屏分区的内容留白，不改变屏幕分辨率、
窗口尺寸、应用安全区或键盘逻辑。

布局参考来自 [houji Android 设备树](https://github.com/lolipuru/android_device_xiaomi_houji/blob/90f836ebc7b89a8dd22840b49db8c18cf7cabc2a/overlays/FrameworksResHouji/res/values/dimens.xml)
的 124 像素状态栏高度。以该区域中心作为内容对齐目标，结合原字体大写字母高度计算底部
留白；这不是对摄像头中心的实测。两侧分别向外移动最多 8 个逻辑点，保留至少 8 点外侧
留白，并保持分区宽度。原系统仍负责图标、字体、充电状态和布局约束。

安装前检查实际 Objective-C 方法签名。横屏、展开状态栏、外接屏、不同屏幕尺寸、不同
系统版本及异常几何保持原结果。主机检查执行实际适配函数，覆盖上述回退、宽度保持和
基线计算；目标 iOS 的导入与视觉对齐仍须分别验证。

## 闪屏与紫色区域

保留记录能确认以下顺序，不能据此认定因果：

- r206/r207 使用独立的 GPU 渲染面，等待完成后按原生尺寸复制到扫描面。用户确认文字
  清楚且闪屏消失。该改动隔离了渲染写入与显示读取，没有通过改背景颜色隐藏闪屏。
- r208–r210 继续使用同一显示方式；后续主要改动为查询等待、CPU 调度和交互升降频。
- r214 的记录已明确指出，单手模式及后台卡片阴影的紫色在该版以前就存在。因此不能
  将 r214 的异步呈现或 120 Hz 软件定时器视为已经确认的引入点。
- r217/r218 的颜色处理对照未获得改善；后续把诊断清屏色改绿也未使用户看到的紫色
  变绿。仍没有证据将紫色定位到那个诊断清屏值。

相关记录：[r208 性能记录](../archive/docs/native-runtime-performance-r208.md)、
[r214 显示与键盘记录](../archive/docs/unified-keyboard-refresh-r214.md)、
[r217/r218 颜色对照](../archive/docs/gpu-colour-timing-r217-r218.md)。保留 fence 与缓冲区
生命周期约束；在缺少引入点证据时，不能把取消同步作为颜色修复。
