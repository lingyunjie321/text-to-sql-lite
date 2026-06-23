import { useState } from "react";

import type { QueryRunView } from "../adapters/queryRunAdapter";
import { ErrorMessage } from "./ErrorMessage";

interface SqlWorkspaceProps {
  view: QueryRunView | null;
  draftSql: string;
  isEditing: boolean;
  isLoading: boolean;
  runtimeError: string | null;
  onDraftSqlChange: (sql: string) => void;
  onCopy: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onRunEditedSql: () => void;
  onRegenerate: () => void;
}

export function SqlWorkspace({
  view,
  draftSql,
  isEditing,
  isLoading,
  runtimeError,
  onDraftSqlChange,
  onCopy,
  onEdit,
  onCancelEdit,
  onRunEditedSql,
  onRegenerate
}: SqlWorkspaceProps): JSX.Element {
  const [repairOpen, setRepairOpen] = useState(false);
  const hasSql = draftSql.trim().length > 0;

  return (
    <section className="surface sqlSection" aria-labelledby="sqlTitle">
      <div className="sectionHeader sqlHeader">
        <div>
          <h2 id="sqlTitle">SQL</h2>
          <p>{view?.statusText ?? "生成后可在这里查看、复制或编辑 SQL。"}</p>
        </div>
        <div className="sqlActions">
          {isEditing ? (
            <>
              <button className="secondaryButton" type="button" onClick={onCancelEdit}>
                取消修改
              </button>
              <button
                className="primaryButton"
                type="button"
                disabled={!hasSql || isLoading}
                onClick={onRunEditedSql}
              >
                运行修改后的 SQL
              </button>
            </>
          ) : (
            <>
              <button className="secondaryButton" type="button" disabled={!hasSql} onClick={onCopy}>
                复制
              </button>
              <button className="secondaryButton" type="button" disabled={!hasSql} onClick={onEdit}>
                编辑
              </button>
              <button
                className="secondaryButton"
                type="button"
                disabled={isLoading || !view}
                onClick={onRegenerate}
              >
                重新生成
              </button>
            </>
          )}
        </div>
      </div>

      {runtimeError ? <ErrorMessage message={runtimeError} /> : null}

      {view?.repairNotice ? (
        <div className="repairNotice">
          <div className="repairSummary">
            <span>{view.repairNotice.summary}</span>
            <button className="inlineButton" type="button" onClick={() => setRepairOpen((open) => !open)}>
              查看详情
            </button>
          </div>
          {repairOpen ? (
            <div className="repairDetails">
              <p>{view.repairNotice.error}</p>
              <p>{view.repairNotice.explanation}</p>
              <div className="repairSqlGrid">
                <pre>{view.repairNotice.beforeSql || "无修复前 SQL"}</pre>
                <pre>{view.repairNotice.afterSql || "无修复后 SQL"}</pre>
              </div>
            </div>
          ) : null}
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
    </section>
  );
}
