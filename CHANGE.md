# 变更记录

## 0.1.0

- 重构自更新机制：Linux/Windows 走 app 自身两进程模型，macOS 走 Sparkle 2.x（PyObjC）
- 修复 macOS codesign 与 Sparkle 的 bundle ambiguous 死锁（保留符号链接 + inside-out 签名）
- 新增 macOS 公证（notarytool + stapler）与 appcast 生成（EdDSA 签名）
- 修复 CFBundleVersion 缺失导致 Sparkle 无法定位 bundle 的问题
