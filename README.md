# draw-diagram

在 Codex 中用 `$draw-diagram` 新建、修改、检查和导出可编辑的 Draw.io 工程图。它包含绘图规则、本机执行说明和 Python 校验脚本，适合根据代码、接口文档或明确的设计绘制架构图、流程图、时序图、ER 图、网络拓扑图、类图和状态图。

最终保留 `.drawio` 源文件，便于继续编辑；需要放进文档或演示材料时，再导出 SVG、PNG 或 PDF。思维导图、甘特图、数据图表和 UI 线框图不在稳定支持范围内。

## 使用前提

完整绘图流程需要以下环境，软件应安装在 **Codex 实际执行命令的那台 Mac** 上。

| 条件 | 用途与要求 |
|---|---|
| 本地 Codex 环境 | 能发现本 skill、读取项目材料、执行 shell/Python、写入目标目录，并查看导出的图片以完成视觉检查。远程或云端任务不能直接使用另一台 Mac 上的 draw.io。 |
| macOS | 当前工作流面向 macOS；未提供 Windows、Linux 的完整使用流程。 |
| Python 3.9 或更高版本 | 运行校验和交付脚本。脚本只使用 Python 标准库，无需 `pip install`。 |
| draw.io Desktop 及其 CLI | CLI 即命令行工具，用于导出、渲染检查、Mermaid 转换和按需自动布局。可从 [draw.io 官方发布页](https://github.com/jgraph/drawio-desktop/releases)安装 macOS 版本。仅打开网页版不足以运行这些脚本。 |
| 图中使用的字体 | 新建中文图默认使用 `PingFang SC`，纯英文图默认使用 `Helvetica`；修改已有图时保留其可用字体。 |
| Git | 用于下方的克隆安装和后续更新；直接下载仓库文件时不需要 Git。 |

本 skill 不依赖其他绘图 skill，也不要求额外配置 API Key 或 MCP 服务。绘图规范和参考资料随仓库提供；Codex 本身的账号、联网和工具访问仍按其运行环境配置。

### 检查本机工具

在终端执行：

```bash
python3 --version
DRAW_DIAGRAM_CLI="/Applications/draw.io.app/Contents/MacOS/draw.io"
test -x "$DRAW_DIAGRAM_CLI"
"$DRAW_DIAGRAM_CLI" --help
```

`test -x` 成功时没有输出，退出码为 `0`。检查 CLI 帮助中是否包含所需功能：

- 渲染检查使用 SVG 导出、`--embed-svg-fonts`、`--theme`，以及**从 1 开始**的 `--page-index`。
- Mermaid 创作需要支持 `.mmd` / `.mermaid` 输入并转换为可编辑图形。
- 自动布局需要支持 `--layout`；手工编辑 XML 不依赖自动布局。

项目未声明最低 draw.io 版本，请按实际 CLI 能力检查。脚本先查默认应用路径，再查 `PATH` 中的 `drawio`；安装在其他位置时，可通过 `--drawio-cli` 指定可执行文件。

没有可用 CLI 时，仍可编辑 XML 并做静态校验，但无法完成需要渲染检查、预览或导出的完整交付。仅有脚本校验结果不能算视觉验收通过。

## 安装到 Codex

首次安装可将整个仓库放入用户级 skill 目录，使它在不同项目中可用。下面的命令安装远程默认分支：

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/theChildinus/draw-diagram.git \
  "$HOME/.agents/skills/draw-diagram"
```

如果正在阅读其他分支的 README，请在 `git clone` 中加入 `--branch 分支名`，安装与说明一致的版本。目标目录已经存在时，先确认其中是否有个人修改，再更新已有副本。

只供一个项目使用时，也可以将完整目录放到项目的 `.agents/skills/draw-diagram/`。安装后应能在 Codex 的 skill 列表中找到 `Draw Diagram`；未出现时重启 Codex。目录与发现规则见 [Codex 官方 skill 文档](https://learn.chatgpt.com/docs/build-skills)。

必须保留 `SKILL.md`、`agents/`、`references/` 和 `scripts/`，不要只复制 README。已有安装若由其他目录管理，继续使用 Codex 实际识别的那份，避免同名副本混用。

## 如何调用

在 **Codex 对话中**明确写出 `$draw-diagram`，后面描述任务。它不是终端命令；只说“帮我画图”不会自动调用这个 skill。此行为由 [agents/openai.yaml](agents/openai.yaml) 中的 `allow_implicit_invocation: false` 控制。

通常需要交代：图要回答什么问题、给谁看、依据哪些文件，以及保存位置和导出格式。引用本地文件时使用实际绝对路径，或在 Codex 中附上对应文件；下面的 `/path/to/project` 都需要替换。

### 根据代码新建架构图

```text
$draw-diagram 根据 /path/to/project 的代码画一张请求处理架构图，
给新加入的开发同事看，突出入口、核心处理步骤和数据存储。
从上到下阅读，保存为 /path/to/project/docs/请求处理架构.drawio，
并导出同名 SVG。不能从代码确认的关系请先指出。
```

新图默认采用白底、白色或浅灰节点、灰色细线，少量低饱和蓝色突出核心对象。需要沿用公司配色、指定画布或最终展示尺寸时，在请求中说明。

### 修改已有图

```text
$draw-diagram 修改 /path/to/project/docs/请求处理架构.drawio，
依据 /path/to/project/docs/重试设计.md 补上超时后的重试分支。
保留现有配色、字体和其余布局，更新同名 SVG。
```

修改时请提供原始 `.drawio`。只有截图时，可以据此重建，但无法保证保留原图的分组、端口和编辑结构。

### 只检查，或只导出

```text
$draw-diagram 检查 /path/to/project/docs/请求处理架构.drawio，
检查结构、连线和最终显示效果，只报告问题，暂不修改文件。
```

```text
$draw-diagram 将 /path/to/project/docs/请求处理架构.drawio 的第 2 页
导出为 /path/to/project/docs/请求处理架构-第2页.png，保留源文件。
```

多页文件导出 SVG 或 PNG 时，需要明确页码和各页输出路径；多页 PDF 可以导出全部页面。

## 绘图与交付过程

Codex 会先核对材料中的节点、职责、关系和方向，再安排布局。标准流程图、时序图、ER 图、类图和状态图优先用 Mermaid 作为临时输入，转换后继续编辑 `.drawio`；复杂架构、网络拓扑和已有图修改直接处理 XML。通常无需提前指定创作方式。

修改已有图时，会先记录原文件的 SHA-256（内容校验值），另建候选文件。候选通过检查后，由 `scripts/deliver_drawio.py` 写入最终路径；期间原文件若被其他操作改动，交付会停止，避免覆盖新内容。

检查分为三个部分：

| 检查 | 解决的问题 |
|---|---|
| 静态校验 | XML 能否解析、ID 是否唯一、边端点是否存在、独立文本框是否超出安全边界等。 |
| 渲染后连线检查 | 用 CLI 实际导出 SVG，检查可见连线缺失、共用端口、重叠、间距、交叉、穿节点和过短线段。交付脚本会为包含连线的新图或路由输入变化自动开启此检查。 |
| 视觉检查 | 根据改动范围查看局部或整图，检查文字、换行、裁切、遮挡、字体和整体可读性。脚本不能替代这一步。 |

所有错误都需要修正。候选新增或变差的警告会阻止交付，只有逐项检查后才能按 `fingerprint`（诊断标识）接受；未变化的存量警告会保留记录。视觉检查结果必须与最终候选文件的 SHA-256 对应。

交付内容是可编辑 `.drawio` 和所需的导出物。临时 Mermaid 文件和预览图无需长期维护；SVG、PNG、PDF 即使嵌入了图形数据，也不能替代独立源文件。详细参数见 [本机执行与交付说明](references/execution.md)。

## 手动运行校验

日常使用可以让 Codex 执行上述流程。需要自行排查时，在包含 `SKILL.md` 的仓库或安装目录中运行以下命令，并将示例路径替换为真实文件。

静态校验不会修改输入文件：

```bash
python3 scripts/validate_drawio.py '/absolute/path/to/diagram.drawio'
```

需要机器可读诊断，或希望警告也返回失败退出码时：

```bash
python3 scripts/validate_drawio.py '/absolute/path/to/diagram.drawio' --json
python3 scripts/validate_drawio.py '/absolute/path/to/diagram.drawio' --strict-warnings
```

检查实际渲染的连线；临时 SVG 会自动清理：

```bash
python3 scripts/validate_drawio.py '/absolute/path/to/diagram.drawio' \
  --check-rendered-edges
```

指定其他安装位置的 CLI：

```bash
python3 scripts/validate_drawio.py '/absolute/path/to/diagram.drawio' \
  --check-rendered-edges --drawio-cli '/absolute/path/to/draw.io'
```

校验器退出码 `0` 表示没有错误，默认仍可能有警告；`1` 表示发现错误，或开启 `--strict-warnings` 后发现警告；`2` 表示文件读取、解析或 CLI 执行等故障。

维护脚本时，可查看参数并运行现有测试：

```bash
python3 scripts/validate_drawio.py --help
python3 scripts/deliver_drawio.py --help
python3 -m unittest discover -s tests -v
```

## 常见问题

| 现象 | 处理方法 |
|---|---|
| Codex 找不到 skill | 检查目录下是否直接包含 `SKILL.md`、完整文件是否安装，以及 skill 是否被禁用；必要时重启 Codex。 |
| `Draw.io Desktop CLI not found` | 确认安装位置、可执行权限和 `PATH`，或用 `--drawio-cli` 指定可执行文件。只设置 `DRAW_DIAGRAM_CLI` shell 变量不会改变 Python 脚本的查找顺序。 |
| CLI 不认识参数，或不能转换 Mermaid | 查看该版本的 `--help`。缺少 Mermaid 或布局功能时可改用 XML；缺少渲染检查所需功能时，需要先准备兼容的 CLI。 |
| 可见连线没有可解析路径 | 核对导出页、SVG 中的图元和 CLI 输出，不能把漏检的边当作通过。 |
| 共用端口、重叠或间距不足 | 按 [XML 连线规则](references/xml.md) 分配独立端口和通道；真实分支用明确连接点表示，公共干线只画一次。 |
| 校验通过，文字仍拥挤或被截断 | 查看实际尺寸的预览，精简文字、扩大节点或调整局部布局后重验。 |
| 交付提示目标哈希不匹配 | 目标在候选准备期间发生了变化，重新读取最新文件并合并改动后再检查。 |

## 仓库内容

- [SKILL.md](SKILL.md)：完整工作流、绘图规则和验收要求。
- [agents/openai.yaml](agents/openai.yaml)：显示名称与显式调用策略。
- [references/execution.md](references/execution.md)：CLI、候选文件、导出与交付命令。
- [references/xml.md](references/xml.md)、[references/mermaid.md](references/mermaid.md)：两种创作方式的具体写法。
- [references/style.json](references/style.json)：新图默认样式；[references/cases.json](references/cases.json)：可选结构案例。
- [scripts/](scripts/)：静态与渲染校验器、候选交付脚本；[tests/](tests/)：对应回归测试。

参考案例只用于借鉴结构，图中的事实和关系仍应来自当前材料。
