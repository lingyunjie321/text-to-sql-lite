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
  Save,
  Settings2,
  Sparkles,
  Table2,
  ThumbsDown,
  ThumbsUp,
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
  QueryRunSummaryPayload,
  QueryRunResponse,
  RuntimeConfigCreateRequest,
  RuntimeConfigResponse,
  RuntimeMode,
  RuntimeOptionsResponse,
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

type SidePanel = "runtime" | "demo" | "debug" | "history" | null;

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
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [historyItems, setHistoryItems] = useState<QuerySession[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<SidePanel>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfigResponse | null>(null);
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

  useEffect(() => {
    let active = true;
    client
      .listRuns()
      .then((response) => {
        if (active) {
          setHistoryItems(response.items.map(adaptPersistedRunSummary));
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
        targetDialect: selectedDataSource.dialect,
        ...(runtimeConfig ? { runtimeConfigId: runtimeConfig.runtime_config_id } : {})
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
        targetDialect: selectedDataSource.dialect,
        ...(runtimeConfig ? { runtimeConfigId: runtimeConfig.runtime_config_id } : {})
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
    setActionMessage(null);
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

  async function applyRuntimeConfig(nextConfig: RuntimeConfigResponse): Promise<void> {
    setRuntimeConfig(nextConfig);
    setSchema(await client.getSchema(nextConfig.runtime_config_id));
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

  async function saveCurrentSql(): Promise<void> {
    if (!currentSession || !draftSql.trim()) {
      return;
    }
    try {
      const name = currentSession.question.trim() || "保存的 SQL";
      await client.createSavedQuery(
        currentSession.raw.trace.length > 0
          ? {
              name,
              request_id: currentSession.id,
              tags: []
            }
          : {
              name,
              question: currentSession.question,
              sql: draftSql.trim(),
              tags: []
            }
      );
      setActionMessage("SQL 已保存");
      setRuntimeError(null);
    } catch (error: unknown) {
      setRuntimeError(errorToUserMessage(error));
      setTechnicalError(errorToTechnicalDetail(error));
    }
  }

  async function submitFeedback(rating: "up" | "down", issueType: string): Promise<void> {
    if (!currentSession) {
      return;
    }
    try {
      await client.recordFeedback(currentSession.id, {
        rating,
        issue_type: issueType
      });
      setActionMessage("反馈已记录");
      setRuntimeError(null);
    } catch (error: unknown) {
      setRuntimeError(errorToUserMessage(error));
      setTechnicalError(errorToTechnicalDetail(error));
    }
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
                <button type="button" onClick={() => openPanel("runtime")}>
                  <Database size={16} />
                  运行配置
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

        <RunSummary
          view={currentView}
          runtimeError={runtimeError}
          actionMessage={actionMessage}
          onSaveSql={() => {
            void saveCurrentSql();
          }}
          onPositiveFeedback={() => {
            void submitFeedback("up", "accurate");
          }}
          onNegativeFeedback={() => {
            void submitFeedback("down", "inaccurate");
          }}
        />

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
      {activePanel === "runtime" ? (
        <RuntimeConfigPanel
          client={client}
          currentConfig={runtimeConfig}
          onApply={(nextConfig) => {
            void applyRuntimeConfig(nextConfig)
              .then(closePanel)
              .catch((error: unknown) => {
                setRuntimeError(errorToUserMessage(error));
                setTechnicalError(errorToTechnicalDetail(error));
              });
          }}
          onClear={() => {
            setRuntimeConfig(null);
            void client
              .getSchema()
              .then(setSchema)
              .catch((error: unknown) => {
                setRuntimeError(errorToUserMessage(error));
                setTechnicalError(errorToTechnicalDetail(error));
              });
          }}
          onClose={closePanel}
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
  runtimeError,
  actionMessage,
  onSaveSql,
  onPositiveFeedback,
  onNegativeFeedback
}: {
  view: QueryRunView | null;
  runtimeError: string | null;
  actionMessage: string | null;
  onSaveSql: () => void;
  onPositiveFeedback: () => void;
  onNegativeFeedback: () => void;
}): JSX.Element {
  const statusIcon =
    view?.sqlStatus === "failed" || runtimeError ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />;
  const usedTables = view?.details.usedTables ?? [];
  const tableText = usedTables.length > 0 ? `使用表：${usedTables.join("、")}` : "使用表：等待生成";
  const repairText = `自动修复 ${view?.details.repairCount ?? 0} 次`;
  const canAct = view !== null && view.sql.trim().length > 0;

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
      {view ? (
        <div className="summaryActions">
          <button className="secondaryButton compactButton" type="button" disabled={!canAct} onClick={onSaveSql}>
            <Save size={15} />
            保存 SQL
          </button>
          <button className="secondaryButton compactButton" type="button" onClick={onPositiveFeedback}>
            <ThumbsUp size={15} />
            结果有用
          </button>
          <button className="secondaryButton compactButton" type="button" onClick={onNegativeFeedback}>
            <ThumbsDown size={15} />
            结果不准确
          </button>
          {actionMessage ? <span className="actionMessage">{actionMessage}</span> : null}
        </div>
      ) : null}
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

function RuntimeConfigPanel({
  client,
  currentConfig,
  onApply,
  onClear,
  onClose
}: {
  client: TextToSqlClient;
  currentConfig: RuntimeConfigResponse | null;
  onApply: (config: RuntimeConfigResponse) => void;
  onClear: () => void;
  onClose: () => void;
}): JSX.Element {
  const [options, setOptions] = useState<RuntimeOptionsResponse | null>(null);
  const [databaseMode, setDatabaseMode] = useState<RuntimeMode>("preset");
  const [databasePresetId, setDatabasePresetId] = useState("");
  const [databaseDriver, setDatabaseDriver] = useState<"sqlite" | "postgresql" | "mysql">("sqlite");
  const [sqlitePath, setSqlitePath] = useState("");
  const [dbHost, setDbHost] = useState("");
  const [dbPort, setDbPort] = useState("5432");
  const [dbName, setDbName] = useState("");
  const [dbUser, setDbUser] = useState("");
  const [dbPassword, setDbPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [lightForm, setLightForm] = useState<ModelFormState>(() => makeModelForm());
  const [strongForm, setStrongForm] = useState<ModelFormState>(() => makeModelForm());
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    client
      .getRuntimeOptions()
      .then((nextOptions) => {
        if (!active) {
          return;
        }
        setOptions(nextOptions);
        setDatabasePresetId(nextOptions.database_presets[0]?.id ?? "");
        setLightForm((form) => ({ ...form, presetId: nextOptions.model_presets.light[0]?.id ?? "" }));
        setStrongForm((form) => ({ ...form, presetId: nextOptions.model_presets.strong[0]?.id ?? "" }));
      })
      .catch((error: unknown) => {
        if (active) {
          setFormError(errorToUserMessage(error));
        }
      });
    return () => {
      active = false;
    };
  }, [client]);

  const canSave = options !== null && !isSaving && isRuntimeRequestComplete(buildRuntimeRequest());

  async function saveRuntimeConfig(): Promise<void> {
    const request = buildRuntimeRequest();
    if (!isRuntimeRequestComplete(request)) {
      setFormError("请完整配置数据库、轻量模型和强模型。");
      return;
    }

    setIsSaving(true);
    setFormError(null);
    try {
      onApply(await client.createRuntimeConfig(request));
    } catch (error: unknown) {
      setFormError(errorToUserMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  function buildRuntimeRequest(): RuntimeConfigCreateRequest {
    return {
      database:
        databaseMode === "preset"
          ? { mode: "preset", preset_id: databasePresetId }
          : {
              mode: "custom",
              config:
                databaseDriver === "sqlite"
                  ? {
                      driver: "sqlite",
                      sqlite_path: sqlitePath.trim(),
                      display_name: displayName.trim() || undefined,
                      target_dialect: "sqlite"
                    }
                  : {
                      driver: databaseDriver,
                      host: dbHost.trim(),
                      port: Number(dbPort),
                      database_name: dbName.trim(),
                      username: dbUser.trim(),
                      password: dbPassword,
                      display_name: displayName.trim() || undefined,
                      target_dialect: databaseDriver === "postgresql" ? "postgres" : "mysql"
                    }
            },
      models: {
        light: buildModelSelection(lightForm),
        strong: buildModelSelection(strongForm)
      }
    };
  }

  return (
    <SidePanelFrame title="运行配置" onClose={onClose}>
      <div className="runtimeStack">
        {currentConfig ? (
          <section className="runtimeSummary">
            <strong>当前配置：{currentConfig.database.display_name}</strong>
            <span>
              light {currentConfig.models.light.provider}/{currentConfig.models.light.model}
            </span>
            <span>
              strong {currentConfig.models.strong.provider}/{currentConfig.models.strong.model}
            </span>
            <button className="secondaryButton" type="button" onClick={onClear}>
              清除运行配置
            </button>
          </section>
        ) : null}

        <section className="runtimeSection">
          <h3>数据库</h3>
          <div className="segmentedControl" aria-label="数据库配置模式">
            <button
              className={databaseMode === "preset" ? "isActive" : ""}
              type="button"
              onClick={() => setDatabaseMode("preset")}
            >
              系统预设
            </button>
            <button
              className={databaseMode === "custom" ? "isActive" : ""}
              type="button"
              onClick={() => setDatabaseMode("custom")}
            >
              自定义
            </button>
          </div>

          {databaseMode === "preset" ? (
            <label className="formField">
              <span>数据库预设</span>
              <select value={databasePresetId} onChange={(event) => setDatabasePresetId(event.target.value)}>
                {(options?.database_presets ?? []).map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.display_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="formGrid">
              <label className="formField">
                <span>数据库类型</span>
                <select
                  value={databaseDriver}
                  onChange={(event) => setDatabaseDriver(event.target.value as "sqlite" | "postgresql" | "mysql")}
                >
                  <option value="sqlite">SQLite</option>
                  <option value="postgresql">PostgreSQL</option>
                  <option value="mysql">MySQL</option>
                </select>
              </label>
              {databaseDriver === "sqlite" ? (
                <label className="formField">
                  <span>SQLite 路径</span>
                  <input value={sqlitePath} onChange={(event) => setSqlitePath(event.target.value)} />
                </label>
              ) : (
                <>
                  <label className="formField">
                    <span>地址</span>
                    <input value={dbHost} onChange={(event) => setDbHost(event.target.value)} />
                  </label>
                  <label className="formField">
                    <span>端口</span>
                    <input value={dbPort} inputMode="numeric" onChange={(event) => setDbPort(event.target.value)} />
                  </label>
                  <label className="formField">
                    <span>数据库名</span>
                    <input value={dbName} onChange={(event) => setDbName(event.target.value)} />
                  </label>
                  <label className="formField">
                    <span>用户名</span>
                    <input value={dbUser} onChange={(event) => setDbUser(event.target.value)} />
                  </label>
                  <label className="formField">
                    <span>密码</span>
                    <input
                      type="password"
                      value={dbPassword}
                      onChange={(event) => setDbPassword(event.target.value)}
                    />
                  </label>
                </>
              )}
              <label className="formField">
                <span>显示名称</span>
                <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
              </label>
            </div>
          )}
        </section>

        <ModelConfigSection
          title="轻量模型"
          alias="light"
          form={lightForm}
          presets={options?.model_presets.light ?? []}
          onChange={setLightForm}
        />
        <ModelConfigSection
          title="强模型"
          alias="strong"
          form={strongForm}
          presets={options?.model_presets.strong ?? []}
          onChange={setStrongForm}
        />

        {formError ? <div className="runtimeError">{formError}</div> : null}

        <div className="panelActions">
          <button className="secondaryButton" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="primaryButton"
            type="button"
            disabled={!canSave}
            onClick={() => {
              void saveRuntimeConfig();
            }}
          >
            <Database size={16} />
            {isSaving ? "保存中" : "保存运行配置"}
          </button>
        </div>
      </div>
    </SidePanelFrame>
  );
}

interface ModelFormState {
  mode: RuntimeMode;
  presetId: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  apiKeyEnv: string;
}

function makeModelForm(): ModelFormState {
  return {
    mode: "preset",
    presetId: "",
    provider: "openai_compatible",
    model: "",
    baseUrl: "",
    apiKey: "",
    apiKeyEnv: ""
  };
}

function ModelConfigSection({
  title,
  alias,
  form,
  presets,
  onChange
}: {
  title: string;
  alias: "light" | "strong";
  form: ModelFormState;
  presets: RuntimeOptionsResponse["model_presets"]["light"];
  onChange: (form: ModelFormState) => void;
}): JSX.Element {
  function update(patch: Partial<ModelFormState>): void {
    onChange({ ...form, ...patch });
  }

  return (
    <section className="runtimeSection">
      <h3>{title}</h3>
      <div className="segmentedControl" aria-label={`${title}配置模式`}>
        <button className={form.mode === "preset" ? "isActive" : ""} type="button" onClick={() => update({ mode: "preset" })}>
          系统预设
        </button>
        <button className={form.mode === "custom" ? "isActive" : ""} type="button" onClick={() => update({ mode: "custom" })}>
          自定义
        </button>
      </div>

      {form.mode === "preset" ? (
        <label className="formField">
          <span>{alias} 预设</span>
          <select value={form.presetId} onChange={(event) => update({ presetId: event.target.value })}>
            {presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.display_name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="formGrid">
          <label className="formField">
            <span>Provider</span>
            <select value={form.provider} onChange={(event) => update({ provider: event.target.value })}>
              <option value="openai_compatible">OpenAI Compatible</option>
              <option value="mock">Mock</option>
            </select>
          </label>
          <label className="formField">
            <span>模型名</span>
            <input value={form.model} onChange={(event) => update({ model: event.target.value })} />
          </label>
          <label className="formField">
            <span>Base URL</span>
            <input value={form.baseUrl} onChange={(event) => update({ baseUrl: event.target.value })} />
          </label>
          <label className="formField">
            <span>API Key</span>
            <input type="password" value={form.apiKey} onChange={(event) => update({ apiKey: event.target.value })} />
          </label>
          <label className="formField">
            <span>API Key 环境变量</span>
            <input value={form.apiKeyEnv} onChange={(event) => update({ apiKeyEnv: event.target.value })} />
          </label>
        </div>
      )}
    </section>
  );
}

function buildModelSelection(form: ModelFormState): RuntimeConfigCreateRequest["models"]["light"] {
  if (form.mode === "preset") {
    return { mode: "preset", preset_id: form.presetId };
  }
  return {
    mode: "custom",
    provider: form.provider.trim(),
    model: form.model.trim(),
    base_url: form.baseUrl.trim() || undefined,
    api_key: form.apiKey,
    api_key_env: form.apiKeyEnv.trim() || undefined
  };
}

function isRuntimeRequestComplete(request: RuntimeConfigCreateRequest): boolean {
  const databaseReady =
    request.database.mode === "preset"
      ? Boolean(request.database.preset_id)
      : request.database.config?.driver === "sqlite"
        ? Boolean(request.database.config.sqlite_path?.trim())
        : Boolean(
            request.database.config?.host?.trim() &&
              request.database.config.port &&
              request.database.config.database_name?.trim() &&
              request.database.config.username?.trim() &&
              request.database.config.password?.trim()
          );
  return databaseReady && isModelSelectionComplete(request.models.light) && isModelSelectionComplete(request.models.strong);
}

function isModelSelectionComplete(selection: RuntimeConfigCreateRequest["models"]["light"]): boolean {
  if (selection.mode === "preset") {
    return Boolean(selection.preset_id);
  }
  return Boolean(
    selection.provider?.trim() &&
      selection.model?.trim() &&
      (selection.api_key?.trim() || selection.api_key_env?.trim())
  );
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

function adaptPersistedRunSummary(summary: QueryRunSummaryPayload): QuerySession {
  const succeeded = summary.status === "success";
  const raw: QueryRunResponse = {
    request_id: summary.request_id,
    status: summary.status,
    final_sql: summary.final_sql ?? "",
    result: null,
    attempts: summary.attempts,
    selected_model: summary.selected_model ?? null,
    routing_reason: summary.routing_reason ?? null,
    linked_schema: { tables: [] },
    retrieved_examples: [],
    rag_context: {
      reference_sql: [],
      documents: [],
      metrics: [],
      semantic_models: []
    },
    repair_history: [],
    errors: summary.error_message
      ? [
          {
            message: summary.error_message
          }
        ]
      : [],
    trace: []
  };
  return {
    id: summary.request_id,
    question: summary.question,
    dialect: summary.target_dialect,
    raw,
    view: {
      requestId: summary.request_id,
      sqlStatus: succeeded ? "generated_valid" : "failed",
      statusText: succeeded ? "SQL 已生成并通过验证" : "未能生成可执行 SQL",
      sql: summary.final_sql ?? "",
      result: null,
      repairNotice: null,
      details: {
        usedTables: [],
        validationResult: succeeded ? "通过" : "未通过",
        repairCount: summary.attempts,
        databaseType: summary.target_dialect,
        executionMs: null,
        rowCount: summary.row_count ?? null
      },
      developerInfo: {
        model: summary.selected_model ?? null,
        routingReason: summary.routing_reason ?? null,
        retrievedExamples: [],
        trace: [],
        errors: raw.errors
      },
      userError: summary.error_message ? { message: summary.error_message } : null
    }
  };
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
