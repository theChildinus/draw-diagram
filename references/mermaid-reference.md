# Mermaid 临时创作参考

来源：`jgraph/drawio-mcp/shared/mermaid-reference.md`。
同步日期：2026-08-13。

仅用于新建标准流程图、时序图、ER 图、类图和状态图。Mermaid 文件是临时输入，转换后的 `.drawio` 才是事实源。

## 通用规则

- 第一条非指令行必须是正确的图型关键字：`flowchart`、`sequenceDiagram`、`erDiagram`、`classDiagram` 或 `stateDiagram-v2`。
- 节点 ID 使用简短 ASCII 标识，不含空格和尾部标点；显示文字放在标签中。
- 中文、括号、冒号、连字符或其他特殊字符出现在标签中时，使用双引号。
- 一行写一条语句。
- 标签保持短小。复杂说明移到节点职责、图注或细节图。
- 不为了匹配固定配色堆叠大量 `style`。转换后需要精确样式时编辑 Draw.io XML。
- Mermaid 适合自动排版，不适合精确文本框、端口、厂商图标和复杂嵌套容器。

## 流程图

~~~mermaid
flowchart TD
  start["收到请求"] --> validate{"校验通过？"}
  validate -->|"是"| execute["执行任务"]
  validate -->|"否"| reject["返回错误"]
  execute --> finish((结束))
  reject --> finish
~~~

方向：`TD`/`TB` 从上到下，`LR` 从左到右，`BT` 和 `RL` 为反向。

常用形状：

- `A["矩形"]`
- `A("圆角矩形")`
- `A{"判断"} `
- `A[("数据存储")]`
- `A((结束))`

常用边：

- `-->` 有向实线
- `---` 无箭头实线
- `-.->` 有向虚线
- `<-->` 双向关系，仅在事实确实双向时使用
- `A -->|"条件"| B` 边标签

使用 `subgraph` 表达一个必要的区域边界；层级多、容器精确或跨区连线复杂时改用 XML。

## 时序图

~~~mermaid
sequenceDiagram
  autonumber
  participant U as 用户
  participant A as API
  participant S as 服务
  U->>A: 提交请求
  A->>S: 执行
  S-->>A: 返回结果
  A-->>U: 响应
~~~

- `->>`：实线请求。
- `-->>`：虚线返回。
- `activate S` / `deactivate S`：显式生命周期。
- `alt` / `else` / `end`：条件分支。
- `opt` / `end`：可选分支。
- `loop` / `end`：循环。
- `par` / `and` / `end`：并行。
- `Note over A,S: 说明`：跨参与者说明。

参与者过多或消息标签过长时，拆分主流程和细节时序，不压缩字号。

## ER 图

~~~mermaid
erDiagram
  USER ||--o{ ORDER : 创建
  ORDER ||--|{ ORDER_ITEM : 包含
  USER {
    string id PK
    string name
  }
  ORDER {
    string id PK
    string user_id FK
  }
~~~

基数：

- `|o`：零或一。
- `||`：恰好一。
- `}o`：零或多。
- `}|`：一或多。

属性格式为 `type name [PK|FK|UK]`。实体、字段和关系必须来自当前数据模型或明确设计。

## 类图

~~~mermaid
classDiagram
  class Task {
    +String id
    +run() void
  }
  class BuildTask
  Task <|-- BuildTask : 继承
~~~

关系：

- `<|--`：继承。
- `*--`：组合。
- `o--`：聚合。
- `-->`：关联。
- `..>`：依赖。
- `..|>`：实现。

可见性：`+` public、`-` private、`#` protected、`~` package。只展示当前问题需要的成员，避免把完整代码清单塞入类图。

## 状态图

~~~mermaid
stateDiagram-v2
  [*] --> Pending
  Pending --> Running : start
  Running --> Succeeded : complete
  Running --> Failed : error
  Succeeded --> [*]
  Failed --> [*]
~~~

- 使用 `stateDiagram-v2`。
- `[*]` 根据方向表示开始或结束。
- 转换标签格式：`A --> B : event [guard] / action`。
- 复合状态使用 `state Name { ... }`。
- 状态和转换必须来自真实状态机、协议或明确设计。

## 有限样式能力

只在简单图中使用少量类样式：

~~~mermaid
flowchart LR
  A["开始"]:::primary --> B["完成"]
  classDef primary fill:#DBEAFE,stroke:#2563EB,color:#0F172A
~~~

转换后仍须检查字体族、字号层级、文本框边界、连线和箭头。无法通过时不要继续堆 Mermaid 样式，转到 XML 局部精修。

## 转换后的处理

1. 删除或清理临时 `.mmd`，不把它作为第二事实源。
2. 检查转换生成的 `fontFamily`，必要时在 `.drawio` XML 中统一为当前图的目标字体。
3. 运行静态校验器。
4. 用 CLI 导出临时预览。
5. 首次失败时可以调整一次方向、分组或标签长度后重新转换。
6. 第二次仍有问题时直接编辑 `.drawio` XML，不反复重排。
