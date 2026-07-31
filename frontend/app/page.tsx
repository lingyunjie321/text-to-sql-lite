import { Suspense } from "react";
import { Workbench } from "@/components/workbench/Workbench";

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[60vh] items-center justify-center">
          <div className="text-sm text-[var(--color-text-tertiary)]">
            加载中...
          </div>
        </div>
      }
    >
      <Workbench />
    </Suspense>
  );
}
