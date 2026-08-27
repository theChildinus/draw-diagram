# Draw.io XML 精确创作参考

XML 结构来源：`jgraph/drawio-mcp/shared/xml-reference.md`；配色和视觉语义遵循本 Skill 的 `default-visual-style.json` 与 `drawio-guidelines.md`。
同步日期：2026-08-13。

用于修改已有 `.drawio`、绘制架构图或网络拓扑图，以及精确控制容器、字体、文本框、端口和连线。

## 1. 最小文件结构

~~~xml
<mxfile host="Electron" version="26.0.0">
  <diagram id="page-1" name="Page-1">
    <mxGraphModel adaptiveColors="auto" grid="1" gridSize="10" page="1" pageScale="1" pageWidth="1169" pageHeight="827">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
~~~

- `id="0"` 是根，`id="1"` 是默认层。
- 普通图形放在 `parent="1"`，容器子节点放在对应容器下。
- `adaptiveColors="auto"` 允许 Draw.io 根据主题调整默认颜色。
- 所有 ID 唯一，且不要在 XML 中添加注释。

## 2. 常用节点

### 圆角矩形

~~~xml
<mxCell id="service" value="服务" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DBEAFE;strokeColor=#2563EB;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=12;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="160" height="64" as="geometry"/>
</mxCell>
~~~

### 判断

~~~xml
<mxCell id="decision" value="是否通过？" style="rhombus;whiteSpace=wrap;html=1;fillColor=#DBEAFE;strokeColor=#2563EB;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=12;" vertex="1" parent="1">
  <mxGeometry x="100" y="220" width="140" height="88" as="geometry"/>
</mxCell>
~~~

### 数据存储

~~~xml
<mxCell id="database" value="数据库" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#CCFBF1;strokeColor=#0F766E;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=12;" vertex="1" parent="1">
  <mxGeometry x="320" y="100" width="120" height="72" as="geometry"/>
</mxCell>
~~~

### 外部参与者

外部系统可以使用边框不同的通用矩形；不要只靠颜色区分。

~~~xml
<mxCell id="external" value="外部系统" style="rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor=#F1F5F9;strokeColor=#64748B;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=12;" vertex="1" parent="1">
  <mxGeometry x="40" y="100" width="140" height="64" as="geometry"/>
</mxCell>
~~~

## 3. 标签和字体

- 普通文本也使用 `html=1`，便于后续安全换行。
- HTML 标签必须在属性中转义：`<` → `&lt;`，`>` → `&gt;`，`&` → `&amp;`，`"` → `&quot;`。
- 换行使用 `&#xa;`，或在 `html=1` 时使用 `&lt;br&gt;`；不要写字面量 `\n`。
- 整体加粗使用 `fontStyle=1`，局部加粗才使用转义后的 `<b>`。
- 新建中文图优先使用 `fontFamily=PingFang SC`；同一张图保持一致。修改已有图时保留其可用字体。

单一居中标题直接使用节点 `value`。需要独立文本框时，让它成为所属图形的子节点，以便静态检查安全边界：

~~~xml
<mxCell id="owner" value="" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="220" height="100" as="geometry"/>
</mxCell>
<mxCell id="owner-label" value="对象名称" style="text;html=1;align=center;verticalAlign=middle;connectable=0;fontFamily=PingFang SC;fontSize=13;fontStyle=1;" vertex="1" parent="owner">
  <mxGeometry x="40" y="32" width="140" height="24" as="geometry"/>
</mxCell>
~~~

独立文本框必须满足 `drawio-guidelines.md` 中的 `safeX`、`safeY` 公式。顶层标题和图注可以放在默认层，但仍设置 `connectable=0`。
UML 类成员行和表格单元格若由 `stackLayout` 或 `tableLayout` 管理，则属于结构化布局内容，不按叠加文本框的安全带公式检查；关系默认仍连接外层类或表格对象。

## 4. 连线

每条边都必须展开并包含相对几何：

~~~xml
<mxCell id="edge-1" value="调用" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#334155;strokeWidth=1.5;endArrow=classic;endFill=1;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=12;" edge="1" source="service" target="database" parent="1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
~~~

常用风格：

| 图型 | 推荐边样式 |
|---|---|
| 流程、架构、网络 | `edgeStyle=orthogonalEdgeStyle;rounded=1` |
| ER | `edgeStyle=entityRelationEdgeStyle` |
| 类图、时序消息 | 直线，不设置 `edgeStyle` |
| 同步调用 | `strokeColor=#334155;strokeWidth=1.5` 实线 |
| 主链路 | `strokeColor=#334155;strokeWidth=2`，保留实际关系线型 |
| 异步消息 | `strokeColor=#334155;strokeWidth=1.5;dashed=1;dashPattern=6 4` |
| 监控或状态回传 | `strokeColor=#64748B;strokeWidth=1.5;dashed=1;dashPattern=1 4` |
| 次要依赖或辅助链路 | `strokeColor=#64748B;strokeWidth=1` 或 `1.5`，保留实际关系线型 |
| 异常、失败或超时 | `strokeColor=#DC2626;strokeWidth=1.5`，保留实际关系线型并带文字标签 |
| 需要强调的可观测性链路 | `strokeColor=#0E7490;strokeWidth=1.5;dashed=1;dashPattern=1 4` |

线宽规则只在当前图或当前页内生效。`main_path` 表示该图/页为回答主要问题所需的核心阅读链，不表示某个组件或关系在其他图中也必须使用 `2 pt`。当前核心链路使用 `strokeWidth=2`，普通同步、辅助、状态回传和异常路径通常使用 `1.5`；异步或回传关系即使属于主链，也保留原有虚线或点线样式。

规则：

- 边连接外框，不连接文本框。
- 当前图/页的主链需要强调时只把 `strokeWidth` 增加到 `2`，不另造一种颜色；不要把另一张图或另一页的主链判定复制过来。视觉线型只使用实线、虚线和点线；图中出现三类以上关系语义时增加图例。连线颜色不跟随起点或终点的节点类别。
- 不手写折点作为默认方案。先调整节点、端口和通道；需要保留节点位置时可尝试一次 `libavoid`。
- 只有确切的几何意图才设置 `exitX`、`exitY`、`entryX`、`entryY`。
- 跨容器边使用公共层 `parent="1"`，避免被容器裁切。
- 边标签保持短小，直接写在边的 `value` 上。

## 5. 容器和父子关系

### 带标题容器

~~~xml
<mxCell id="service-group" value="服务域" style="swimlane;startSize=28;html=1;fillColor=#F8FAFC;strokeColor=#64748B;fontColor=#0F172A;fontFamily=PingFang SC;fontSize=14;fontStyle=1;" vertex="1" parent="1">
  <mxGeometry x="80" y="80" width="420" height="240" as="geometry"/>
</mxCell>
<mxCell id="api" value="API" style="rounded=1;whiteSpace=wrap;html=1;fontFamily=PingFang SC;fontSize=13;" vertex="1" parent="service-group">
  <mxGeometry x="28" y="52" width="140" height="64" as="geometry"/>
</mxCell>
~~~

- 子节点坐标相对于父容器。
- 容器标题区不放子节点。
- 容器本身不需要连接时，可以用 `container=1;pointerEvents=0` 的自定义容器。
- 需要连接容器本身时使用 `swimlane`，不要设置 `pointerEvents=0`。
- 复杂嵌套只在层级本身有语义时使用，避免无意义分组。

大型背景容器不要沿用普通卡片的 `arcSize=10–14`。宽、高都不小于 `300 px` 的空白背景容器若启用圆角，使用 `arcSize=4`，或者关闭圆角：

~~~xml
<mxCell id="region-bg" value="" style="rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#CBD5E1;pointerEvents=0;connectable=0;" vertex="1" parent="1">
  <mxGeometry x="40" y="100" width="720" height="520" as="geometry"/>
</mxCell>
~~~

### 隐形分组

~~~xml
<mxCell id="group-1" value="" style="group;" vertex="1" parent="1">
  <mxGeometry x="80" y="80" width="420" height="240" as="geometry"/>
</mxCell>
~~~

隐形分组用于共同移动，不承担边界语义，也不连接边。

## 6. 层

新增层是 `parent="0"` 且没有 `vertex`、`edge` 的 `mxCell`：

~~~xml
<mxCell id="annotations-layer" value="Annotations" parent="0"/>
~~~

仅在用户需要切换物理/逻辑、现状/目标或注释等独立视图时使用额外层。普通图不要为了组织 XML 而增加层。

## 7. 图标

- 默认只用通用形状。
- 用户明确指定 AWS、Azure、Kubernetes 等体系时，优先复用当前文件中已验证的内置图标 style，或使用能够确认名称的 Draw.io 内置库。
- 官方图标保留官方原色和比例，不重染、不拉伸、不旋转；功能类别、归属和状态放在外围容器、边框、标签或角标中。
- 本 Skill 不联网搜索形状。
- 无法确认准确 style 时回退到通用形状并说明，不猜测图标名称。

## 8. XML 安全

- XML 必须能被标准解析器解析。
- 属性中的 `&`、`<`、`>`、`"` 必须转义。
- 禁止 XML 注释。
- 所有边都有存在的 `source` 和 `target`。
- 所有边都有 `<mxGeometry relative="1" as="geometry"/>`。
- `mxfile` 可以包含多页；静态校验器会逐页检查。
- 不修改压缩页面文本时，优先让 Draw.io CLI 或编辑器负责重新编码；静态校验器可以读取压缩页面。

## 9. 精修顺序

1. 先修事实、节点和关系。
2. 再修容器尺寸和节点对齐。
3. 再修字体、文字长度和独立文本框。
4. 再修端口、连线路由、标签和箭头。
5. 静态校验。
6. 导出预览并检查最终显示尺寸。

如果局部修正需要越来越多覆盖层、折点或嵌套文本框，删除问题区域并按正确结构重建，不继续叠补丁。
