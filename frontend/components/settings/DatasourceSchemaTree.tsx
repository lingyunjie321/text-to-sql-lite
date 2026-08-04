import { useMemo } from "react";
import { Table2 } from "lucide-react";

import type { MetadataSchema } from "@/lib/datasource-profiles";

interface Props {
  schemas: readonly MetadataSchema[];
  selectedTables: readonly string[];
  onToggle: (qualifiedName: string) => void;
}

export function DatasourceSchemaTree({ schemas, selectedTables, onToggle }: Props) {
  const selected = useMemo(() => new Set(selectedTables), [selectedTables]);
  return (
    <div className="max-h-96 space-y-3 overflow-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4">
      {schemas.map((schema) => (
        <details key={schema.name} open>
          <summary className="cursor-pointer text-sm font-semibold text-[var(--color-text-primary)]">
            {schema.name}
          </summary>
          <div className="mt-2 space-y-2 pl-3">
            {schema.relations.map((relation) => {
              const qualifiedName = `${schema.name}.${relation.name}`;
              return (
                <details
                  key={qualifiedName}
                  className="rounded-md border border-[var(--color-border)] bg-white px-3 py-2"
                >
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={`允许查询 ${qualifiedName}`}
                      checked={selected.has(qualifiedName)}
                      onChange={() => onToggle(qualifiedName)}
                      onClick={(event) => event.stopPropagation()}
                    />
                    <Table2 className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" />
                    <span className="font-medium text-[var(--color-text-secondary)]">
                      {relation.name}
                    </span>
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      {relation.kind === "view" ? "视图" : "表"}
                    </span>
                  </summary>
                  {relation.columns.length > 0 ? (
                    <ul className="mt-2 space-y-1 border-t border-[var(--color-border)] pt-2 pl-7 text-xs text-[var(--color-text-tertiary)]">
                      {relation.columns.map((column) => (
                        <li key={column.name}>
                          {column.name} · {column.data_type}
                          {relation.primary_key.includes(column.name) ? " · PK" : ""}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </details>
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}
