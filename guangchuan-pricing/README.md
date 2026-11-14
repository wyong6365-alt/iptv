# 广川AI智能工程量清单识别与自主组价平台 V1.0

研发单位：山东广川建设工程有限公司

当前阶段：平台基础、山东省建设工程计价引擎、Excel 清单识别和操作界面已完成并通过测试；PDF 和扫描件识别、定额库与定额匹配、资源价格、报价导出、exe 打包尚未开发。

## 运行

```
cd frontend && npm install && npm run build   # 界面构建到 backend/gcpricing/static
cd ../backend && pip install -e ".[dev]"
python -m pytest                               # 运行测试
python -m gcpricing                            # 启动后用浏览器打开 http://127.0.0.1:8765
```

首次打开时创建管理员账号。数据默认保存在用户目录下的 `.gcpricing/`。

## Windows 桌面版（exe）

每次推送后，GitHub Actions 的“Guangchuan pricing desktop build”流程会在 Windows 构建机上运行测试、打包并自检，产物 `GuangchuanPricing.exe` 在该次运行页面底部的 Artifacts 中下载。

使用：双击 exe，稍等片刻会自动用默认浏览器打开界面，同时出现一个小控制窗口，关闭它即退出程序。数据保存在 `%LOCALAPPDATA%\GuangchuanPricing`，升级 exe 不影响数据。

exe 没有代码签名，首次运行时 Windows 可能提示“已保护你的电脑”，点“更多信息”→“仍要运行”。

## 设计文件

| 文件 | 内容 |
| --- | --- |
| [docs/01-architecture.md](docs/01-architecture.md) | 全专业架构设计：平台底座、专业适配器、清单保护、不可竞争费用锁定、计价引擎、AI 匹配、数据库、研发阶段 |
| [docs/02-capability-matrix.md](docs/02-capability-matrix.md) | 专业能力矩阵：16 个专业 × 11 项能力，状态判定规则，V1.0 目标 |
| [docs/03-quota-data-plan.md](docs/03-quota-data-plan.md) | 定额数据规划：计价体系族、候选计价依据清单、导入与校验流程、数据合法性 |
| [docs/04-test-plan.md](docs/04-test-plan.md) | 真实项目测试方案：样本要求、对照基准、指标、与第十七章验收标准的对应 |

已确认事项和遗留问题见 [01-architecture.md 第 14 节](docs/01-architecture.md#14-已确认事项与遗留问题)。
