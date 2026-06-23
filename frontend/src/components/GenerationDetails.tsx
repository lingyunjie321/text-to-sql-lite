import { useState } from "react";

import type { QueryRunView } from "../adapters/queryRunAdapter";

interface GenerationDetailsProps {
  view: QueryRunView | null;
  technicalError: string | null;
}

export function GenerationDetails({ view, technicalError }: GenerationDetailsProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [developerOpen, setDeveloperOpen] = useState(false);

  return (
    <section className="generationDetails">
      <button className="detailsToggle" type="button" onClick={() => setOpen((value) => !value)}>
        生成详情
      </button>
      {open ? (
        <div className="detailsPanel">
          {view ? (
            <dl className="detailsList">
              <div>
                <dt>使用的数据表</dt>
                <dd>{view.details.usedTables.length > 0 ? view.details.usedTables.join("、") : "未命中具体表"}</dd>
              </div>
              <div>
                <dt>验证结果</dt>
                <dd>{view.details.validationResult}</dd>
              </div>
              <div>
                <dt>自动修复次数</dt>
                <dd>{view.details.repairCount}</dd>
              </div>
              <div>
                <dt>数据库类型</dt>
                <dd>{view.details.databaseType}</dd>
              </div>
              <div>
                <dt>执行时间</dt>
                <dd>{view.details.executionMs === null ? "无" : `${view.details.executionMs} ms`}</dd>
              </div>
              <div>
                <dt>返回行数</dt>
                <dd>{view.details.rowCount === null ? "无" : view.details.rowCount}</dd>
              </div>
            </dl>
          ) : (
            <p className="detailsEmpty">暂无生成详情。</p>
          )}

          <button
            className="developerToggle"
            type="button"
            onClick={() => setDeveloperOpen((value) => !value)}
          >
            查看开发者信息
          </button>
          {developerOpen ? (
            <div className="developerInfo">
              {technicalError ? (
                <div>
                  <h3>技术错误</h3>
                  <pre>{technicalError}</pre>
                </div>
              ) : null}
              {view ? (
                <>
                  <div>
                    <h3>模型路由</h3>
                    <p>
                      模型：{view.developerInfo.model ?? "无模型信息"}
                      {view.developerInfo.routingReason
                        ? `，原因：${view.developerInfo.routingReason}`
                        : ""}
                    </p>
                  </div>
                  <div>
                    <h3>Few-shot</h3>
                    <pre>{JSON.stringify(view.developerInfo.retrievedExamples, null, 2)}</pre>
                  </div>
                  <div>
                    <h3>Agent Trace</h3>
                    <ul className="traceList">
                      {view.developerInfo.trace.map((event) => (
                        <li key={`${event.node_name}-${event.start_time}`}>{event.node_name}</li>
                      ))}
                    </ul>
                    <pre>{JSON.stringify(view.developerInfo.trace, null, 2)}</pre>
                  </div>
                  <div>
                    <h3>原始异常</h3>
                    <pre>{JSON.stringify(view.developerInfo.errors, null, 2)}</pre>
                  </div>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
