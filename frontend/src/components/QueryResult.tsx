import type { QueryCellValue } from "../api/types";
import type { QueryResultView } from "../adapters/queryRunAdapter";

interface QueryResultProps {
  result: QueryResultView | null;
}

export function QueryResult({ result }: QueryResultProps): JSX.Element {
  return (
    <section className="surface resultSection" aria-labelledby="resultTitle" role="region">
      <div className="sectionHeader resultHeader">
        <div>
          <h2 id="resultTitle">查询结果</h2>
          <p>{result ? "SQL 下方直接展示本次查询返回的数据" : "生成并执行后，查询结果会显示在这里。"}</p>
        </div>
        {result ? (
          <div className="resultMeta">
            <span>{result.rowCount} 行</span>
            <span>{result.executionMs} ms</span>
          </div>
        ) : null}
      </div>

      {!result ? <div className="emptyResult">暂无查询结果。</div> : null}
      {result && result.rowCount === 0 ? (
        <div className="emptyResult">查询成功，但没有返回数据。</div>
      ) : null}
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
