import { useEffect, useRef } from "react";

const EXAMPLES = ["列出订单金额", "按地区统计销售额", "查找最近的高价值订单"];

interface QueryInputProps {
  question: string;
  isLoading: boolean;
  loadingMessage: string | null;
  onQuestionChange: (question: string) => void;
  onSubmit: () => void;
}

export function QueryInput({
  question,
  isLoading,
  loadingMessage,
  onQuestionChange,
  onSubmit
}: QueryInputProps): JSX.Element {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const canSubmit = question.trim().length > 0 && !isLoading;

  return (
    <section className="surface querySection" aria-labelledby="queryTitle">
      <div className="sectionHeader">
        <div>
          <h1 id="queryTitle">生成 SQL</h1>
          <p>用自然语言描述你需要的数据</p>
        </div>
      </div>
      <textarea
        ref={inputRef}
        className="queryTextarea"
        aria-label="用自然语言描述你需要的数据"
        value={question}
        placeholder="例如：列出最近 30 天每个地区的订单金额"
        disabled={isLoading}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            if (canSubmit) {
              onSubmit();
            }
          }
        }}
      />
      <div className="queryFooter">
        <div className="exampleButtons" aria-label="示例问题">
          {EXAMPLES.map((example) => (
            <button
              className="exampleButton"
              key={example}
              type="button"
              disabled={isLoading}
              onClick={() => onQuestionChange(example)}
            >
              {example}
            </button>
          ))}
        </div>
        <div className="submitGroup">
          {loadingMessage ? <span className="loadingText">{loadingMessage}</span> : null}
          <button className="primaryButton" type="button" disabled={!canSubmit} onClick={onSubmit}>
            生成并验证
          </button>
        </div>
      </div>
    </section>
  );
}
