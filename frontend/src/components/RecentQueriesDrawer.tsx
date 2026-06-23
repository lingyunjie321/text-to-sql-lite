import type { QueryRunView } from "../adapters/queryRunAdapter";

export interface RecentQueryItem {
  id: string;
  question: string;
  view: QueryRunView;
}

interface RecentQueriesDrawerProps {
  open: boolean;
  items: RecentQueryItem[];
  onClose: () => void;
  onSelect: (item: RecentQueryItem) => void;
}

export function RecentQueriesDrawer({
  open,
  items,
  onClose,
  onSelect
}: RecentQueriesDrawerProps): JSX.Element | null {
  if (!open) {
    return null;
  }

  return (
    <div className="drawerBackdrop" role="presentation" onClick={onClose}>
      <aside
        className="recentDrawer"
        aria-label="历史记录"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawerHeader">
          <h2>历史记录</h2>
          <button className="textButton" type="button" onClick={onClose}>
            关闭
          </button>
        </div>
        {items.length === 0 ? (
          <p className="drawerEmpty">还没有生成记录。</p>
        ) : (
          <ul className="recentList">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  className="recentItem"
                  type="button"
                  onClick={() => {
                    onSelect(item);
                    onClose();
                  }}
                >
                  <span>{item.question}</span>
                  <small>{item.view.statusText}</small>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
