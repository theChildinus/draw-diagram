# Draw.io macOS 执行参考

来源：`jgraph/drawio-mcp` 的 `drawio` Skill、`shared/mermaid-reference.md` 和 `shared/xml-reference.md`。
同步日期：2026-08-13。

本文件只保留当前个人工作流需要的 macOS 能力。不要在运行时联网补充参考。

## 1. 定位 CLI

默认路径：

~~~sh
DRAW_DIAGRAM_CLI="/Applications/draw.io.app/Contents/MacOS/draw.io"
test -x "$DRAW_DIAGRAM_CLI"
~~~

若不存在，先检查 `command -v drawio`。仍找不到时：

- 可以直接创建或修改 XML 格式的 `.drawio`。
- 不能承诺 Mermaid 转换、ELK/`libavoid` 布局或 CLI 导出。
- 说明缺少的能力，不自动安装软件。

## 2. Mermaid 转换

在临时目录创建 `.mmd`，转换成功后只保留目标 `.drawio`：

~~~sh
"$DRAW_DIAGRAM_CLI" -x -f xml -o "/absolute/path/name.drawio" "/temporary/path/name.mmd"
~~~

不要直接从 `.mmd` 导出 PNG、SVG 或 PDF。始终先转为 `.drawio`，再从 `.drawio` 导出。

转换后：

1. 运行 `scripts/validate_drawio.py`。
2. 检查转换结果的 `fontFamily`。Draw.io Mermaid 转换可能写入英文默认字体；与当前图字体要求不一致时，在 `.drawio` XML 中统一替换为目标字体。
3. 需要精修时直接编辑 `.drawio` XML，不维护 Mermaid 和 Draw.io 两份源。
4. 临时 `.mmd` 放在明确的临时目录中，任务结束后清理该临时目录。

## 3. XML 创建和修改

直接生成或修改原生 Draw.io XML。完整读取 `drawio-xml-reference.md` 后再写。

适用场景：

- 修改已有 `.drawio`。
- 架构图和网络拓扑图。
- 复杂容器、泳道、精确端口、独立文本框或厂商图标。
- Mermaid 转换后需要满足字体、文本框、连线或编辑性约束。

修改已有文件前保留其内容和视觉体系。不要通过全图自动布局解决局部问题。

## 4. 自动布局

自动布局只用于新建图，最多尝试一次。把结果写到临时文件，校验和回看后再替换目标。

### 移动节点并重新布线

~~~sh
"$DRAW_DIAGRAM_CLI" -x -f xml --layout verticalFlow -o "/temporary/path/layout.drawio" "/absolute/path/source.drawio"
"$DRAW_DIAGRAM_CLI" -x -f xml --layout horizontalFlow -o "/temporary/path/layout.drawio" "/absolute/path/source.drawio"
~~~

常用预设：

| 名称 | 用途 |
|---|---|
| `verticalFlow` | 从上到下的流程或分层链路 |
| `horizontalFlow` | 从左到右的流程或调用链 |
| `verticalTree` | 从上到下的层级树 |
| `horizontalTree` | 从左到右的层级树 |
| `radialTree` | 放射状层级 |
| `organic` | 网络关系初稿 |

### 只重新路由连线

~~~sh
"$DRAW_DIAGRAM_CLI" -x -f xml --layout libavoid -o "/temporary/path/routed.drawio" "/absolute/path/source.drawio"
~~~

`libavoid` 保留节点位置，只对连线做正交避障。它适合已经手工排好节点的架构图和网络图。不要在 flow/tree 布局后默认再叠加 `libavoid`。

以下情况不使用全图自动布局：

- 修改已有图。
- 用户指定了精确位置。
- 容器或空间位置本身表达语义。
- 只存在一个局部拥挤或连线问题。

自动布局后必须重新运行静态校验并导出预览；命令成功不代表布局合格。

## 5. 导出

始终从 `.drawio` 导出，并保留源文件。

~~~sh
"$DRAW_DIAGRAM_CLI" -x -f svg -e -b 10 -o "/absolute/path/name.svg" "/absolute/path/name.drawio"
"$DRAW_DIAGRAM_CLI" -x -f png -e -b 10 -o "/absolute/path/name.png" "/absolute/path/name.drawio"
"$DRAW_DIAGRAM_CLI" -x -f pdf -e -b 10 -o "/absolute/path/name.pdf" "/absolute/path/name.drawio"
~~~

参数：

- `-x`：导出模式。
- `-f`：目标格式。
- `-e`：在支持的导出物中嵌入 Draw.io XML。
- `-b 10`：增加 10 px 边距。
- `-t`：PNG 透明背景，仅在目标载体需要时使用。
- `-s`、`--width`、`--height`：仅在用户给出尺寸要求时使用。

SVG、PNG、PDF 即使嵌入 XML，也只是导出物；不要删除独立 `.drawio`。

## 6. 按视觉风险预览

先按 `SKILL.md` 判断验收等级：

- 无视觉变化：只运行静态校验，不执行导出命令，不调用图片查看能力。
- 局部视觉变化：合并同一轮修改后只导出一次，优先查看受影响区域；需要时裁剪临时 PNG，不重复查看整图。
- 全局视觉变化：新建图、全图布局、画布、字体或配色调整、多个区域联动，或局部预览无法判断时，导出并查看整图。

需要预览时使用临时目录，避免在项目中留下检查文件：

~~~sh
DRAW_DIAGRAM_PREVIEW_DIR="$(mktemp -d)"
"$DRAW_DIAGRAM_CLI" -x -f png -b 10 -o "$DRAW_DIAGRAM_PREVIEW_DIR/preview.png" "/absolute/path/name.drawio"
~~~

按验收等级检查 `preview.png` 的受影响区域或整图。完成后只清理刚创建且已确认路径的临时目录。

默认不要执行 `open`。只有下列情况才打开编辑器：

- 独立文本框的点击区域无法静态确认。
- 复杂分组、容器或端口仍有疑点。
- 导出结果与 XML 结构预期不一致。
- 用户明确要求打开。

需要时只打开一次：

~~~sh
open -a draw.io "/absolute/path/name.drawio"
~~~

## 7. 推荐执行顺序

1. 创建或修改 `.drawio`。
2. 运行静态校验器。
3. 判断本次变化属于无视觉变化、局部视觉变化还是全局视觉变化。
4. 只有需要视觉预览时才用 CLI 导出临时 PNG。
5. 局部变化只检查受影响区域；全局变化检查整图。
6. 按分级修正路径调整，再次运行静态校验，并按仍存在的风险决定是否复查。
7. 生成用户实际需要的导出格式。
8. 交付 `.drawio` 与所需导出物，并说明实际采用的验收等级。

## 8. 常见故障

| 现象 | 处理 |
|---|---|
| CLI 不存在 | 继续使用 XML 创建 `.drawio`；说明不能转换 Mermaid、自动布局或导出 |
| Mermaid 转换为空白 | 检查首行图型关键字、节点 ID、引号和特殊字符 |
| Mermaid 直接导出失败 | 使用 Mermaid → `.drawio` → 导出物的两步路径 |
| 布局没有效果 | 检查预设名称和 Draw.io Desktop 版本；必要时回到手工 XML 布局 |
| XML 无法打开 | 检查特殊字符转义、根节点、唯一 ID、边的 `mxGeometry` |
| 连线穿过节点 | 先调整节点和端口；需要保留位置时尝试一次 `libavoid` |
| 字体或换行异常 | 使用目标环境可用字体，精简文字或扩大节点，再导出复查 |
| 导出文件为空或损坏 | 先静态校验 `.drawio`，再重新导出 |
