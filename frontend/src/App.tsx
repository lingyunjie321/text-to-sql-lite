import {
  AlertCircle,
  CheckCircle2,
  Clipboard,
  Code2,
  Database,
  FileText,
  History,
  Menu,
  Play,
  RotateCw,
  Settings2,
  Sparkles,
  Table2,
  Wrench,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { adaptQueryRun, type QueryRunView } from "./adapters/queryRunAdapter";
import type { TextToSqlClient } from "./api/client";
import { ApiClientError, createTextToSqlClient } from "./api/client";
import type {
  DialectName,
  QueryCellValue,
  QueryRunResponse,
  SchemaResponse,
  TableSchemaPayload,
  TraceEventPayload
} from "./api/types";
import "./styles.css";

interface AppProps {
  client?: TextToSqlClient;
}

interface DataSourceOption {
  id: string;
  label: string;
  dialect: DialectName;
}

interface QuerySession {
  id: string;
  question: string;
  dialect: DialectName;
  view: QueryRunView;
  raw: QueryRunResponse;
}

type SidePanel = "demo" | "debug" | "history" | null;

const DATA_SOURCES: DataSourceOption[] = [
  { id: "sqlite-demo", label: "SQLite Demo", dialect: "sqlite" }
];

const DEFAULT_CLIENT = createTextToSqlClient();

const EXAMPLE_QUESTIONS = ["列出订单金额", "按地区统计销售额", "查找最近的高价值订单"];

const DEMO_SCENARIOS = [
  {
    id: "success",
    title: "复杂查询一次成功",
    description: "展示 Schema Linking、Top-K 示例、模型路由和一次成功执行。",
    question: "统计每个地区订单金额最高的 3 个客户，返回地区、客户名称、总金额和地区内排名。"
  },
  {
    id: "repair",
    title: "错误字段自动修复",
    description: "先生成带错误字段的 SQL，再通过反思和修复闭环恢复。",
    question: "统计每个地区的订单总金额。"
  },
  {
    id: "termination",
    title: "达到终止条件",
    description: "连续修复失败后停止在第三次尝试，证明循环不会无限运行。",
    question: "触发一个无法修复的查询"
  }
];

export function App({ client = DEFAULT_CLIENT }: AppProps): JSX.Element {
  const [question, setQuestion] = useState("");
  const [selectedDataSourceId, setSelectedDataSourceId] = useState(DATA_SOURCES[0].id);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [currentSession, setCurrentSession] = useState<QuerySession | null>(null);
  const [draftSql, setDraftSql] = useState("");
  const [isEditingSql, setIsEditingSql] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [technicalError, setTechnicalError] = useState<string | null>(null);
  const [historyItems, setHistoryItems] = useState<QuerySession[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<SidePanel>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);

  const selectedDataSource = useMemo(
    () => DATA_SOURCES.find((source) => source.id === selectedDataSourceId) ?? DATA_SOURCES[0],
    [selectedDataSourceId]
  );
  const schemaTables = useMemo(() => summarizeSchemaTables(schema), [schema]);

  useEffect(() => {
    questionRef.current?.focus();
  }, []);

  useEffect(() => {
    let active = true;
    client
      .getSchema()
      .then((nextSchema) => {
        if (active) {
          setSchema(nextSchema);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setTechnicalError(errorToTechnicalDetail(error));
        }
      });
    return () => {
      active = false;
    };
  }, [client]);

  const currentView = currentSession?.view ?? null;
  const canSubmit = question.trim().length > 0 && !isLoading;
  const hasSql = draftSql.trim().length > 0;

  async function runQuestion(nextQuestion = question): Promise<void> {
    const trimmedQuestion = nextQuestion.trim();
    if (!trimmedQuestion || isLoading) {
      return;
    }

    setQuestion(trimmedQuestion);
    await runRequest(async () => {
      const response = await client.runQuery({
        question: trimmedQuestion,
        targetDialect: selectedDataSource.dialect
      });
      applyResponse({
        response,
        question: trimmedQuestion,
        dialect: selectedDataSource.dialect
      });
    });
  }

  async function runEditedSql(): Promise<void> {
    const sql = draftSql.trim();
    if (!sql || isLoading) {
      return;
    }

    await runRequest(async () => {
      const response = await client.runEditedSql({
        sql,
        targetDialect: selectedDataSource.dialect
      });
      applyResponse({
        response,
        question: currentSession?.question ?? "手动执行 SQL",
        dialect: selectedDataSource.dialect
      });
    });
  }

  async function runRequest(action: () => Promise<void>): Promise<void> {
    setIsLoading(true);
    setLoadingMessage("正在理解问题与 Schema…");
    setRuntimeError(null);
    const timer = window.setTimeout(() => {
      setLoadingMessage("正在生成、验证并执行 SQL…");
    }, 260);

    try {
      await action();
      setTechnicalError(null);
    } catch (error: unknown) {
      setRuntimeError(errorToUserMessage(error));
      setTechnicalError(errorToTechnicalDetail(error));
    } finally {
      window.clearTimeout(timer);
      setIsLoading(false);
      setLoadingMessage(null);
    }
  }

  function applyResponse({
    response,
    question: sessionQuestion,
    dialect
  }: {
    response: QueryRunResponse;
    question: string;
    dialect: DialectName;
  }): void {
    const view = adaptQueryRun(response, dialect);
    const nextSession: QuerySession = {
      id: response.request_id,
      question: sessionQuestion,
      dialect,
      view,
      raw: response
    };
    setCurrentSession(nextSession);
    setDraftSql(view.sql);
    setIsEditingSql(false);
    setHistoryItems((items) => [nextSession, ...items.filter((item) => item.id !== nextSession.id)].slice(0, 8));
  }

  function openPanel(panel: SidePanel): void {
    setMenuOpen(false);
    setActivePanel(panel);
  }

  function closePanel(): void {
    setActivePanel(null);
  }

  function copySql(): void {
    if (!draftSql) {
      return;
    }
    void navigator.clipboard?.writeText(draftSql).catch((error: unknown) => {
      setRuntimeError("复制失败，请手动选择 SQL 文本。");
      setTechnicalError(errorToTechnicalDetail(error));
    });
  }

  function selectHistoryItem(item: QuerySession): void {
    setQuestion(item.question);
    setCurrentSession(item);
    setDraftSql(item.view.sql);
    setIsEditingSql(false);
    setRuntimeError(null);
    closePanel();
  }

  return (
    <div className="appShell">
      <header className="appHeader">
        <div className="brandCluster">
          <div className="brandMark" aria-hidden="true">
            <Database size={18} />
          </div>
          <div>
            <div className="productName">Text to SQL</div>
            <div className="productSubline">自然语言数据查询工作台</div>
          </div>
        </div>

        <div className="headerControls">
          <label className="visuallyHidden" htmlFor="dataSource">
            当前数据源
          </label>
          <select
            id="dataSource"
            className="dataSourceSelect"
            value={selectedDataSourceId}
            onChange={(event) => setSelectedDataSourceId(event.target.value)}
          >
            {DATA_SOURCES.map((source) => (
              <option key={source.id} value={source.id}>
                {source.label}
              </option>
            ))}
          </select>
          <div className="menuWrap">
            <button
              className="iconButton"
              type="button"
              aria-label="打开工作台菜单"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <Menu size={19} />
            </button>
            {menuOpen ? (
              <nav className="menuPopover" aria-label="工作台菜单">
                <button type="button" onClick={() => openPanel("demo")}>
                  <Play size={16} />
                  演示中心
                </button>
                <button type="button" onClick={() => openPanel("debug")}>
                  <Settings2 size={16} />
                  开发者调试
                </button>
                <button type="button" onClick={() => openPanel("history")}>
                  <History size={16} />
                  历史记录
                </button>
              </nav>
            ) : null}
          </div>
        </div>
      </header>

      <main className="workspaceLayout">
        <section className="queryHero" aria-labelledby="queryTitle">
          <div className="queryCopy">
            <h1 id="queryTitle">问数据，拿结果</h1>
            <p>描述你想看的数据，系统会选择相关 Schema 和示例生成只读 SQL。</p>
          </div>

          <div className="queryComposer">
            <textarea
              ref={questionRef}
              className="queryTextarea"
              aria-label="用自然语言描述你需要的数据"
              value={question}
              placeholder="例如：统计每个地区的订单总金额"
              disabled={isLoading}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault();
                  if (canSubmit) {
                    void runQuestion();
                  }
                }
              }}
            />
            <div className="composerFooter">
              <div className="exampleButtons" aria-label="示例问题">
                {EXAMPLE_QUESTIONS.map((example) => (
                  <button
                    className="exampleButton"
                    key={example}
                    type="button"
                    disabled={isLoading}
                    onClick={() => setQuestion(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
              <div className="submitGroup">
                {loadingMessage ? <span className="loadingText">{loadingMessage}</span> : null}
                <button
                  className="primaryButton"
                  type="button"
                  disabled={!canSubmit}
                  onClick={() => {
                    void runQuestion();
                  }}
                >
                  <Sparkles size={17} />
                  生成并验证
                </button>
              </div>
            </div>
          </div>
        </section>

        <SchemaHint tables={schemaTables} hasError={technicalError !== null && schema === null} />

        <RunSummary view={currentView} runtimeError={runtimeError} />

        <section className="mainGrid">
          <SqlPanel
            view={currentView}
            draftSql={draftSql}
            isEditing={isEditingSql}
            isLoading={isLoading}
            hasSql={hasSql}
            onDraftSqlChange={setDraftSql}
            onCopy={copySql}
            onEdit={() => setIsEditingSql(true)}
            onCancelEdit={() => {
              setDraftSql(currentView?.sql ?? "");
              setIsEditingSql(false);
            }}
            onRunEditedSql={() => {
              void runEditedSql();
            }}
            onRegenerate={() => {
              void runQuestion();
            }}
          />
          <ResultPanel view={currentView} />
        </section>
      </main>

      {activePanel === "demo" ? (
        <DemoPanel
          isLoading={isLoading}
          onClose={closePanel}
          onRunScenario={(scenarioQuestion) => {
            closePanel();
            void runQuestion(scenarioQuestion);
          }}
        />
      ) : null}
      {activePanel === "debug" ? (
        <DebugPanel session={currentSession} technicalError={technicalError} onClose={closePanel} />
      ) : null}
      {activePanel === "history" ? (
        <HistoryPanel items={historyItems} onClose={closePanel} onSelect={selectHistoryItem} />
      ) : null}
    </div>
  );
}

function SchemaHint({ tables, hasError }: { tables: SchemaTableSummary[]; hasError: boolean }): JSX.Element {
  const previewTables = tables.slice(0, 4);
  return (
    <section className="schemaHint" aria-label="Schema 提示">
      <div className="schemaHintTitle">
        <Table2 size={17} />
        {hasError ? "Schema 暂不可用" : `当前可查询 ${tables.length} 张表`}
      </div>
      <div className="schemaChips">
        {previewTables.length > 0 ? (
          previewTables.map((table) => (
            <span className="schemaChip" key={table.name} title={table.description ?? undefined}>
              {table.name}
              <small>{table.columnCount} 列</small>
            </span>
          ))
        ) : (
          <span className="schemaEmpty">正在读取数据表信息</span>
        )}
      </div>
    </section>
  );
}

function RunSummary({
  view,
  runtimeError
}: {
  view: QueryRunView | null;
  runtimeError: string | null;
}): JSX.Element {
  const statusIcon =
    view?.sqlStatus === "failed" || runtimeError ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />;
  const usedTables = view?.details.usedTables ?? [];
  const tableText = usedTables.length > 0 ? `使用表：${usedTables.join("、")}` : "使用表：等待生成";
  const repairText = `自动修复 ${view?.details.repairCount ?? 0} 次`;

  return (
    <section className={`runSummary ${view?.sqlStatus === "failed" || runtimeError ? "isWarning" : ""}`}>
      <div className="summaryStatus">
        {statusIcon}
        <div>
          <strong>{runtimeError ?? view?.statusText ?? "准备生成 SQL"}</strong>
          {view?.userError ? <span>{view.userError.message}</span> : <span>{tableText}</span>}
        </div>
      </div>
      <div className="summaryMetrics">
        <span>{repairText}</span>
        <span>{view?.details.executionMs === null || !view ? "耗时 --" : `耗时 ${view.details.executionMs} ms`}</span>
        <span>{view?.details.rowCount === null || !view ? "返回 --" : `返回 ${view.details.rowCount} 行`}</span>
      </div>
    </section>
  );
}

function SqlPanel({
  view,
  draftSql,
  isEditing,
  isLoading,
  hasSql,
  onDraftSqlChange,
  onCopy,
  onEdit,
  onCancelEdit,
  onRunEditedSql,
  onRegenerate
}: {
  view: QueryRunView | null;
  draftSql: string;
  isEditing: boolean;
  isLoading: boolean;
  hasSql: boolean;
  onDraftSqlChange: (sql: string) => void;
  onCopy: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onRunEditedSql: () => void;
  onRegenerate: () => void;
}): JSX.Element {
  return (
    <section className="surface sqlSurface" aria-labelledby="sqlTitle">
      <div className="panelHeader">
        <div>
          <h2 id="sqlTitle">SQL 工作区</h2>
          <p>{view ? "只读 SQL 可复制、编辑或重新运行。" : "生成后可查看、编辑、复制或重新运行 SQL。"}</p>
        </div>
        <StatusPill status={view?.sqlStatus ?? "empty"} />
      </div>

      {view?.repairNotice ? (
        <div className="repairBanner">
          <Wrench size={17} />
          <div>
            <strong>{view.repairNotice.summary}</strong>
            <span>{view.repairNotice.explanation}</span>
          </div>
        </div>
      ) : null}

      <textarea
        className="sqlEditor"
        aria-label="SQL 编辑器"
        value={draftSql}
        readOnly={!isEditing}
        placeholder="生成后的 SQL 会显示在这里"
        spellCheck={false}
        wrap="off"
        onChange={(event) => onDraftSqlChange(event.target.value)}
      />

      <div className="panelActions">
        {isEditing ? (
          <>
            <button className="secondaryButton" type="button" onClick={onCancelEdit}>
              取消修改
            </button>
            <button className="primaryButton" type="button" disabled={!hasSql || isLoading} onClick={onRunEditedSql}>
              <Play size={16} />
              运行修改后的 SQL
            </button>
          </>
        ) : (
          <>
            <button className="secondaryButton" type="button" disabled={!hasSql} onClick={onCopy}>
              <Clipboard size={16} />
              复制 SQL
            </button>
            <button className="secondaryButton" type="button" disabled={!hasSql} onClick={onEdit}>
              <Code2 size={16} />
              编辑 SQL
            </button>
            <button className="secondaryButton" type="button" disabled={isLoading || !view} onClick={onRegenerate}>
              <RotateCw size={16} />
              重新生成
            </button>
          </>
        )}
      </div>
    </section>
  );
}

function ResultPanel({ view }: { view: QueryRunView | null }): JSX.Element {
  const result = view?.result ?? null;
  return (
    <section className="surface resultSurface" aria-labelledby="resultTitle" role="region">
      <div className="panelHeader">
        <div>
          <h2 id="resultTitle">查询结果</h2>
          <p>{result ? "本次只读 SQL 的执行结果。" : "生成并执行后，结果表会显示在这里。"}</p>
        </div>
        {result ? (
          <div className="resultMeta">
            <span>{result.rowCount} 行</span>
            <span>{result.executionMs} ms</span>
          </div>
        ) : null}
      </div>

      {!result ? <div className="emptyState">暂无查询结果。</div> : null}
      {result && result.rowCount === 0 ? <div className="emptyState">查询成功，但没有返回数据。</div> : null}
      {result && result.rowCount > 0 ? (
        <div className="tableScroller">
          <table className="resultTable">
            <thead>
              <tr>
                {result.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, index) => (
                <tr key={index}>
                  {result.columns.map((column) => (
                    <ResultCell key={column} value={row[column] ?? null} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function ResultCell({ value }: { value: QueryCellValue }): JSX.Element {
  if (value === null) {
    return <td className="cellNull">NULL</td>;
  }
  if (typeof value === "number") {
    return <td className="cellNumeric">{value}</td>;
  }
  return <td>{String(value)}</td>;
}

function DemoPanel({
  isLoading,
  onClose,
  onRunScenario
}: {
  isLoading: boolean;
  onClose: () => void;
  onRunScenario: (question: string) => void;
}): JSX.Element {
  return (
    <SidePanelFrame title="演示中心" onClose={onClose}>
      <div className="demoList">
        {DEMO_SCENARIOS.map((scenario) => (
          <article className="demoCard" key={scenario.id}>
            <div>
              <h3>{scenario.title}</h3>
              <p>{scenario.description}</p>
              <small>{scenario.question}</small>
            </div>
            <button
              className="primaryButton"
              type="button"
              disabled={isLoading}
              onClick={() => onRunScenario(scenario.question)}
            >
              <Play size={16} />
              运行{scenario.title}
            </button>
          </article>
        ))}
      </div>
    </SidePanelFrame>
  );
}

function DebugPanel({
  session,
  technicalError,
  onClose
}: {
  session: QuerySession | null;
  technicalError: string | null;
  onClose: () => void;
}): JSX.Element {
  const [rawOpen, setRawOpen] = useState(false);

  return (
    <SidePanelFrame title="开发者调试" onClose={onClose}>
      {!session ? (
        <div className="emptyState">还没有运行记录。先在主页面生成一次 SQL。</div>
      ) : (
        <div className="debugStack">
          <section className="debugSection">
            <div className="debugHeader">
              <h3>Agent Trace</h3>
              <span>{session.raw.trace.length} 个节点</span>
            </div>
            <ol className="traceTimeline">
              {session.raw.trace.map((event, index) => (
                <TraceItem event={event} index={index} key={`${event.node_name}-${event.start_time}-${index}`} />
              ))}
            </ol>
          </section>

          <section className="debugSection">
            <h3>模型与上下文</h3>
            <div className="debugFacts">
              <span>模型：{session.view.developerInfo.model ?? "无模型信息"}</span>
              <span>{session.view.developerInfo.routingReason ?? "无路由说明"}</span>
              <span>修复次数：{session.view.details.repairCount}</span>
            </div>
          </section>

          <section className="debugSection">
            <h3>Top-K 示例</h3>
            {session.view.developerInfo.retrievedExamples.length > 0 ? (
              <ul className="exampleList">
                {session.view.developerInfo.retrievedExamples.map((example, index) => (
                  <li key={`${example.natural_language ?? "example"}-${index}`}>
                    <strong>{example.natural_language ?? "未命名示例"}</strong>
                    <span>{example.score === null || example.score === undefined ? "无分数" : `score ${example.score}`}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="emptyState compact">没有返回 Top-K 示例。</div>
            )}
          </section>

          {session.raw.repair_history.length > 0 ? (
            <section className="debugSection">
              <h3>修复历史</h3>
              <div className="repairHistory">
                {session.raw.repair_history.map((repair, index) => (
                  <div className="repairHistoryItem" key={`${repair.error_type ?? "repair"}-${index}`}>
                    <strong>第 {repair.attempt ?? index + 1} 次修复</strong>
                    <span>{repair.explanation ?? repair.reason ?? repair.error_type ?? "已根据错误反馈调整 SQL。"}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {technicalError ? (
            <section className="debugSection">
              <h3>技术错误</h3>
              <pre>{technicalError}</pre>
            </section>
          ) : null}

          <section className="debugSection">
            <button className="secondaryButton" type="button" onClick={() => setRawOpen((open) => !open)}>
              <FileText size={16} />
              查看原始 JSON
            </button>
            {rawOpen ? <pre>{JSON.stringify(session.raw, null, 2)}</pre> : null}
          </section>
        </div>
      )}
    </SidePanelFrame>
  );
}

function TraceItem({ event, index }: { event: TraceEventPayload; index: number }): JSX.Element {
  const statusClass = event.status === "success" ? "isSuccess" : "isError";
  return (
    <li className={`traceItem ${statusClass}`}>
      <div className="traceIndex">{index + 1}</div>
      <div className="traceBody">
        <div className="traceTitle">
          <strong>{event.node_name}</strong>
          <span>{event.outcome}</span>
        </div>
        <div className="traceMeta">
          <span>{event.node_type}</span>
          <span>{event.duration_ms} ms</span>
        </div>
      </div>
    </li>
  );
}

function HistoryPanel({
  items,
  onClose,
  onSelect
}: {
  items: QuerySession[];
  onClose: () => void;
  onSelect: (item: QuerySession) => void;
}): JSX.Element {
  return (
    <SidePanelFrame title="历史记录" onClose={onClose}>
      {items.length === 0 ? (
        <div className="emptyState">还没有生成记录。</div>
      ) : (
        <ul className="historyList">
          {items.map((item) => (
            <li key={item.id}>
              <button className="historyItem" type="button" onClick={() => onSelect(item)}>
                <span>{item.question}</span>
                <small>
                  {item.view.statusText} · {item.view.details.repairCount} 次修复
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </SidePanelFrame>
  );
}

function SidePanelFrame({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}): JSX.Element {
  return (
    <div className="panelBackdrop" role="presentation" onClick={onClose}>
      <aside className="sidePanel" role="dialog" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="sidePanelHeader">
          <h2>{title}</h2>
          <button className="iconButton" type="button" aria-label="关闭面板" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="sidePanelBody">{children}</div>
      </aside>
    </div>
  );
}

function StatusPill({ status }: { status: QueryRunView["sqlStatus"] | "empty" }): JSX.Element {
  const labelByStatus = {
    empty: "待生成",
    generated_valid: "已验证",
    repaired_valid: "已修复",
    failed: "未通过"
  };
  return <span className={`statusPill ${status}`}>{labelByStatus[status]}</span>;
}

interface SchemaTableSummary {
  name: string;
  columnCount: number;
  description: string | null;
}

function summarizeSchemaTables(schema: SchemaResponse | null): SchemaTableSummary[] {
  if (!schema) {
    return [];
  }
  return Object.entries(schema.tables).map(([name, table]) => ({
    name: table.name ?? name,
    columnCount: countColumns(table),
    description: table.description ?? null
  }));
}

function countColumns(table: TableSchemaPayload): number {
  return Object.keys(table.columns).length;
}

function errorToUserMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.userMessage;
  }
  return "暂时无法完成生成，请稍后重试。";
}

function errorToTechnicalDetail(error: unknown): string {
  if (error instanceof ApiClientError) {
    return JSON.stringify(error.technicalDetails ?? error.message, null, 2);
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
