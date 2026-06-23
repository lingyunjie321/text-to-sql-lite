import type { DialectName } from "../api/types";

export interface DataSourceOption {
  id: string;
  label: string;
  dialect: DialectName;
}

interface AppHeaderProps {
  dataSources: DataSourceOption[];
  selectedDataSourceId: string;
  onSelectDataSource: (id: string) => void;
  onOpenHistory: () => void;
}

export function AppHeader({
  dataSources,
  selectedDataSourceId,
  onSelectDataSource,
  onOpenHistory
}: AppHeaderProps): JSX.Element {
  return (
    <header className="appHeader">
      <div className="productName">SQL Agent</div>
      <div className="headerControls">
        <label className="visuallyHidden" htmlFor="dataSource">
          当前数据源
        </label>
        <select
          id="dataSource"
          className="dataSourceSelect"
          value={selectedDataSourceId}
          onChange={(event) => onSelectDataSource(event.target.value)}
        >
          {dataSources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.label}
            </option>
          ))}
        </select>
        <button className="textButton" type="button" onClick={onOpenHistory}>
          历史记录
        </button>
      </div>
    </header>
  );
}
