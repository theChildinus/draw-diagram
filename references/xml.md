# Draw.io XML 精确创作参考

用于修改已有 `.drawio`、绘制架构图或网络拓扑图，以及精确控制容器、字体、文本框、端口和连线。

## 1. 最小文件结构

~~~xml
<mxfile host="Electron">
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

### 普通矩形

~~~xml
<mxCell id="service" value="服务" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#626B73;strokeWidth=1.25;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="160" height="48" as="geometry"/>
</mxCell>
~~~

### 判断

~~~xml
<mxCell id="decision" value="是否通过？" style="rhombus;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#626B73;strokeWidth=1.25;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;" vertex="1" parent="1">
  <mxGeometry x="100" y="220" width="160" height="84" as="geometry"/>
</mxCell>
~~~

### 数据存储

~~~xml
<mxCell id="database" value="数据库" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#626B73;strokeWidth=1.25;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;" vertex="1" parent="1">
  <mxGeometry x="320" y="100" width="120" height="72" as="geometry"/>
</mxCell>
~~~

### 外部参与者

外部系统可以使用边框不同的通用矩形；不要只靠颜色区分。

~~~xml
<mxCell id="external" value="外部系统" style="rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=#F8F9FA;strokeColor=#626B73;strokeWidth=1.25;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;" vertex="1" parent="1">
  <mxGeometry x="40" y="100" width="140" height="64" as="geometry"/>
</mxCell>
~~~

## 3. 标签和字体

- 普通文本也使用 `html=1`，便于后续安全换行。
- HTML 标签必须在属性中转义：`<` → `&lt;`，`>` → `&gt;`，`&` → `&amp;`，`"` → `&quot;`。
- 换行使用 `&#xa;`，或在 `html=1` 时使用 `&lt;br&gt;`；不要写字面量 `\n`。
- 整体加粗使用 `fontStyle=1`，局部加粗才使用转义后的 `<b>`。
- 新建中文图优先使用 `fontFamily=PingFang SC`；同一张图保持一致。修改已有图时保留其可用字体。

短名称直接使用节点 `value` 并居中，多行说明左对齐。需要独立文本框时，让它成为所属图形的子节点，以便静态检查安全边界：

~~~xml
<mxCell id="owner" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#626B73;strokeWidth=1.25;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="220" height="100" as="geometry"/>
</mxCell>
<mxCell id="owner-label" value="对象名称" style="text;html=1;align=center;verticalAlign=middle;connectable=0;fontFamily=PingFang SC;fontSize=16;fontColor=#252B31;fontStyle=1;" vertex="1" parent="owner">
  <mxGeometry x="40" y="32" width="140" height="24" as="geometry"/>
</mxCell>
~~~

独立文本框必须满足 `../SKILL.md` 中的 `safeX`、`safeY` 公式。顶层标题和图注可以放在默认层，但仍设置 `connectable=0`。
UML 类成员行和表格单元格若由 `stackLayout` 或 `tableLayout` 管理，则属于结构化布局内容，不按叠加文本框的安全带公式检查；关系默认仍连接外层类或表格对象。

## 4. 连线

每条边都必须展开并包含相对几何：

~~~xml
<mxCell id="edge-1" value="调用" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#67727D;strokeWidth=1.25;endArrow=classic;endSize=7;endFill=1;fontColor=#4B5560;fontFamily=PingFang SC;fontSize=13;" edge="1" source="service" target="database" parent="1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
~~~

常用风格：

| 图型 | 推荐边样式 |
|---|---|
| 流程、架构、网络 | `edgeStyle=orthogonalEdgeStyle;rounded=0` |
| ER | `edgeStyle=entityRelationEdgeStyle` |
| 类图、时序消息 | 直线，不设置 `edgeStyle` |
| 同步调用 | `strokeColor=#67727D;strokeWidth=1.25` 实线 |
| 主链路 | `strokeColor=#404A53;strokeWidth=1.5`，保留实际关系线型 |
| 异步消息 | `strokeColor=#67727D;strokeWidth=1.25;dashed=1;dashPattern=6 4` |
| 监控或状态回传 | `strokeColor=#67727D;strokeWidth=1.25;dashed=1;dashPattern=1 4` |
| 次要依赖或辅助链路 | `strokeColor=#67727D;strokeWidth=1` 或 `1.25`，保留实际关系线型 |
| 异常、失败或超时 | 随主链或次要链路；需要突出故障时使用 `strokeColor=#DC2626`，保留实际关系线型、主次线宽和文字标签 |
| 需要强调的可观测性链路 | `strokeColor=#45637A;strokeWidth=1.5;dashed=1;dashPattern=1 4` |

- 边连接外框，不连接文本框。
- 不手写折点作为默认方案。先调整节点、端口和通道；局部问题只修局部路由。
- 只有确切的几何意图才设置 `exitX`、`exitY`、`entryX`、`entryY`。
- 跨容器边使用公共层 `parent="1"`，避免被容器裁切。
- 边标签保持短小，直接写在边的 `value` 上。

## 5. 容器和父子关系

### 带标题容器

普通归属边界使用细框和左上角标题；仅在需要表达泳道时显示分隔标题栏。

~~~xml
<mxCell id="service-group" value="服务域" style="rounded=0;container=1;html=1;fillColor=#FFFFFF;strokeColor=#8A949D;strokeWidth=1;align=left;verticalAlign=top;spacingLeft=12;spacingTop=8;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;fontStyle=1;" vertex="1" parent="1">
  <mxGeometry x="80" y="80" width="420" height="240" as="geometry"/>
</mxCell>
<mxCell id="api" value="API" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#626B73;strokeWidth=1.25;fontColor=#252B31;fontFamily=PingFang SC;fontSize=16;" vertex="1" parent="service-group">
  <mxGeometry x="28" y="52" width="140" height="64" as="geometry"/>
</mxCell>
~~~

- 子节点坐标相对于父容器。
- 容器标题区不放子节点。
- 容器本身不需要连接时，可以用 `container=1;pointerEvents=0` 的自定义容器。
- 需要连接容器本身时使用 `swimlane`，不要设置 `pointerEvents=0`。
- 用 `swimlane` 绘制普通归属边界时，设置 `swimlaneLine=0` 并使用白底，隐藏分隔标题栏的边线。
- 复杂嵌套只在层级本身有语义时使用，避免无意义分组。

大型背景容器默认直角。宽、高都不小于 `300 px` 的空白背景容器若启用小圆角，使用 `arcSize=4`，不能沿用流程起止符号等高圆角样式：

~~~xml
<mxCell id="region-bg" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#8A949D;strokeWidth=1;pointerEvents=0;connectable=0;" vertex="1" parent="1">
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

## 7. 多页和压缩页面

- `mxfile` 可以包含多页；静态校验器会逐页检查。
- 不修改压缩页面文本时，优先让 Draw.io CLI 或编辑器负责重新编码；静态校验器可以读取压缩页面。
