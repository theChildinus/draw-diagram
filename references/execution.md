# Draw.io macOS 执行参考

本文件只保留当前个人工作流需要的 macOS 能力。不要在运行时联网补充参考。

## 1. 定位 CLI

默认路径：

~~~sh
DRAW_DIAGRAM_CLI="/Applications/draw.io.app/Contents/MacOS/draw.io"
test -x "$DRAW_DIAGRAM_CLI"
~~~

若不存在，先检查 `command -v drawio`。仍找不到时：

- 可以直接创建或修改 XML 格式的 `.drawio`。
- 不能承诺 Mermaid 转换、自动布局或 CLI 导出。
- 说明缺少的能力，不自动安装软件。

### 1.1 候选文件和目标基线

创建或修改时始终使用与最终目标不同的候选 `.drawio`。已有目标先记录修改前 SHA-256，再复制到任务专用临时目录；新目标把预期状态记为 `missing`。只编辑和预览候选，不直接覆盖最终目标。

~~~sh
DRAW_DIAGRAM_TARGET="/absolute/path/name.drawio"
DRAW_DIAGRAM_CANDIDATE_DIR="$(mktemp -d)"
DRAW_DIAGRAM_CANDIDATE="$DRAW_DIAGRAM_CANDIDATE_DIR/name.drawio"

if test -f "$DRAW_DIAGRAM_TARGET"; then
  DRAW_DIAGRAM_TARGET_SHA="$(shasum -a 256 "$DRAW_DIAGRAM_TARGET" | awk '{print $1}')"
  cp "$DRAW_DIAGRAM_TARGET" "$DRAW_DIAGRAM_CANDIDATE"
else
  DRAW_DIAGRAM_TARGET_SHA="missing"
fi
~~~

目标哈希必须在创建候选之前取得。交付时若目标哈希不一致，说明目标在本轮之外发生了变化；停止并重新读取，不能覆盖。

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

直接生成或修改原生 Draw.io XML；按任务读取 `xml.md` 的结构、端口、文本框或容器部分。

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

以下情况不使用全图自动布局：

- 修改已有图。
- 用户指定了精确位置。
- 容器或空间位置本身表达语义。
- 只存在一个局部拥挤或连线问题。

自动布局后必须重新运行静态校验并导出预览；命令成功不代表布局合格。

## 5. 导出

手工检查时始终从候选 `.drawio` 导出到临时目录，并保留候选。最终需要保留的 SVG、PNG、PDF 由 `deliver_drawio.py --export` 或 `--export-page` 从同一份已验证候选快照生成，避免源文件与导出物不一致。

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
- `-t`：PNG 或 SVG 透明背景，仅在目标载体需要时使用。
- `-s`、`--width`、`--height`：仅在用户给出尺寸要求时使用。

SVG、PNG、PDF 即使嵌入 XML，也只是导出物；不要删除独立 `.drawio`。

### 5.1 临时视觉预览

按 `SKILL.md` 中的视觉风险范围查看候选。预览只写入任务专用临时目录：

~~~sh
DRAW_DIAGRAM_PREVIEW_DIR="$(mktemp -d)"
"$DRAW_DIAGRAM_CLI" -x -f png -b 10 -o "$DRAW_DIAGRAM_PREVIEW_DIR/preview.png" "/absolute/path/name.drawio"
~~~

完成后只清理刚创建且已确认路径的临时目录。日常验收不执行 `open`；只有 `SKILL.md` 规定的疑点或用户明确要求时，才打开一次候选文件。

### 5.2 原子交付和回执

完成候选修正和所需视觉检查后，从 Skill 目录执行：

~~~sh
DRAW_DIAGRAM_CANDIDATE_SHA="$(shasum -a 256 "$DRAW_DIAGRAM_CANDIDATE" | awk '{print $1}')"

python3 scripts/deliver_drawio.py \
  "$DRAW_DIAGRAM_CANDIDATE" \
  "$DRAW_DIAGRAM_TARGET" \
  --expected-target-sha256 "$DRAW_DIAGRAM_TARGET_SHA" \
  --check-rendered-edges \
  --export "/absolute/path/name.svg" \
  --visual-risk local \
  --visual-review passed \
  --reviewed-candidate-sha256 "$DRAW_DIAGRAM_CANDIDATE_SHA"
~~~

候选 SHA-256 必须在最后一次修改和最终预览之后计算。按实际任务选择参数：

- `--expected-target-sha256`：必填。已有目标使用创建候选前记录的 SHA-256；新目标显式使用 `missing`。
- `--check-rendered-edges`：强制检查可见连线。包含连线的新图，或相对基线有路由输入变化时，脚本自动开启，不依赖传入该参数。自动检查不会替代真实视觉预览。
- `--visual-risk none --visual-review not-performed`：确认没有视觉变化，不需要预览。
- `--visual-risk local|global --visual-review passed`：实际检查了最终候选的局部或整图预览且没有可见缺陷，同时必须传入匹配的 `--reviewed-candidate-sha256`。
- 局部或全局变化若使用 `--visual-review not-performed`，以及任何使用 `--visual-review failed` 的交付都会被拒绝。
- `--accept-warning <fingerprint>`：只接受一个候选中新出现或测量结果变差的警告；逐项判断后可重复使用。存量且未恶化的警告不需要重复接受，也不存在整批放行参数。
- `--export PATH`：单页 SVG/PNG，或 PDF；多页 PDF 自动使用全部页面。
- `--export-page PAGE=PATH`：从多页文件明确导出某一页的 SVG、PNG 或 PDF；需要多页图片时重复使用并为每页提供不同路径。
- `--max-issues N`：限制失败回执带回的诊断数量，默认 `10`；完整 XML、SVG 和命令日志不会进入回执。

命令把目标基线和候选分别复制到目标同目录的私有暂存文件，比较节点几何、边端点、端口、折点、父层级、可见性及路由样式；忽略普通标签和非视觉文件元数据。路由变化不能声明无视觉变化。随后对固定候选执行静态校验、所需渲染检查和请求的导出。

候选存在警告时，同样检查固定目标基线，并按诊断 `fingerprint` 区分存量、新增和变差；端口和并行通道间距变小也属于恶化。所有错误、未接受警告、视觉门禁、页码及目标哈希检查通过后才替换目标和导出物。每个文件原子替换，捕获到多文件交付错误时回滚，但不保证操作系统崩溃时的跨文件事务。

紧凑 JSON 回执固定包含：

- `status` 与 `committed`。
- 候选、目标修改前后及导出物的 SHA-256 和字节数。
- 校验页数、错误数、警告数、渲染连线检查、是否自动触发及警告基线差分。
- 最多 `--max-issues` 条带 `fingerprint`、`subject`、`evidence`、`supported_fixes` 的诊断。
- 每个导出物的页范围，以及调用者提供的视觉风险、检查状态和已检查候选哈希。

退出码 `0` 表示已交付；`1` 表示候选、警告、视觉检查或目标前置条件不满足；`2` 表示文件、Draw.io CLI、导出或交付过程故障。非零退出不能称为交付成功。

## 6. 常见故障

| 现象 | 处理 |
|---|---|
| CLI 不存在 | 继续使用 XML 创建 `.drawio`；说明不能转换 Mermaid、自动布局或导出 |
| Mermaid 转换为空白 | 检查首行图型关键字、节点 ID、引号和特殊字符 |
| Mermaid 直接导出失败 | 使用 Mermaid → `.drawio` → 导出物的两步路径 |
| 布局没有效果 | 检查预设名称和 Draw.io Desktop 版本；必要时回到手工 XML 布局 |
| XML 无法打开 | 检查特殊字符转义、根节点、唯一 ID、边的 `mxGeometry` |
| 连线穿过节点 | 先调整节点、端口和局部路由；不要用全图自动布局修复单条连线 |
| 共用锚点或线段重叠 | 按 `xml.md` 第 4 节重新分配端口和通道；真实分支只绘制一次干线并标明连接点 |
| 可见连线缺少渲染路径 | 检查导出页、SVG 单元标识和路径支持情况；不能把未解析的边当作校验通过 |
| 字体或换行异常 | 使用目标环境可用字体，精简文字或扩大节点，再导出复查 |
| 导出文件为空或损坏 | 先静态校验 `.drawio`，再重新导出 |
