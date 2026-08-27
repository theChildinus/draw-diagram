# draw-diagram

一个用于 Codex 的 Draw.io 工程图 skill。它把个人绘图规范、事实核对、XML 结构检查和最终视觉验收组织成一套可重复的工作流。

## 重要：只显式调用

这个 skill 只应在用户明确调用 `$draw-diagram` 时使用，不会隐式接管普通绘图请求。

## 支持范围

稳定支持以下可编辑工程图：

- 架构图
- 流程图
- 时序图
- ER 图
- 网络拓扑图
- 类图
- 状态图

第一版面向 macOS 和本机 Draw.io Desktop CLI。`.drawio` 是唯一可编辑事实源；SVG、PNG、PDF 都是按需生成的导出物。

## 工作方式

1. 先核对代码、配置、接口或其他权威材料，明确图中事实和证据缺口。
2. 先列节点、边界、关系和当前图的主阅读路径，再选择 Mermaid 或 XML。
3. 标准流程图、时序图、ER 图、类图和状态图优先使用 Mermaid 作为临时创作输入；复杂架构图、网络拓扑图和精确排版使用 XML。
4. 新图默认使用白底、低饱和角色色、圆角节点和简洁正交连线；修改已有图时保留其有效视觉体系。
5. 转换后以 `.drawio` 为准，不维护两份独立事实源。
6. 先做静态校验；几何变化增加渲染后连线检查，再按视觉风险检查字体、换行、裁切、遮挡、对齐、连线和箭头方向。

## 验证

从 skill 根目录运行：

```bash
python3 scripts/validate_drawio.py \
  '/absolute/path/to/diagram.drawio'
```

输出 JSON 或把警告视为失败：

```bash
python3 scripts/validate_drawio.py --json \
  '/absolute/path/to/diagram.drawio'

python3 scripts/validate_drawio.py --strict-warnings \
  '/absolute/path/to/diagram.drawio'
```

修改了节点、端口或连线几何时，检查 Draw.io 实际导出的 SVG：

```bash
python3 scripts/validate_drawio.py --check-rendered-edges \
  '/absolute/path/to/diagram.drawio'
```

运行校验器单测：

```bash
python3 scripts/test_validate_drawio.py
```

脚本检查 Draw.io XML 结构、文本框几何，以及渲染后的连线交叉和穿节点问题。通过这些检查仍不等于文字和整体视觉验收通过。

## 硬性验收

- 事实、节点、关系、方向和边界与当前证据一致。
- XML 可解析，ID 唯一，所有边的 `source` 和 `target` 都存在。
- 同一层级使用一致的字体、字号和字重。
- 文本框不遮挡边框或连接端口，并设置 `connectable=0`。
- 连线只连接真实图形，不连接标题、说明或独立文本框。
- 箭头方向清楚，导出结果没有异常换行、裁切、遮挡或字体替换。
- 交付时保留可编辑的 `.drawio` 文件。

## 目录说明

```text
SKILL.md                    工作流、边界和验收规则
agents/openai.yaml          Codex 显示信息和显式调用策略
references/                 执行、XML、Mermaid 和绘图规范
references/default-visual-style.json  新图默认视觉规范
scripts/validate_drawio.py            XML、文本框和渲染连线校验器
scripts/test_validate_drawio.py       校验器单元测试
```

参考案例只提供结构模式，不能替代当前项目的事实，也不能直接复制历史项目内容或视觉样式。
