import { AlertTriangle } from "lucide-react";

import { Button } from "../ui/Button";

interface ModelProfileDeleteDialogProps {
  profileName: string;
  open: boolean;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

export function ModelProfileDeleteDialog({
  profileName,
  open,
  submitting,
  onCancel,
  onConfirm,
}: ModelProfileDeleteDialogProps) {
  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-profile-delete-title"
      className="rounded-lg border border-red-200 bg-red-50 p-5"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-error)]"
          aria-hidden="true"
        />
        <div>
          <h3
            id="model-profile-delete-title"
            className="font-medium text-[var(--color-text-primary)]"
          >
            删除模型 Profile
          </h3>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            确定要删除“{profileName}”吗？此操作不可撤销。
          </p>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={submitting}
          onClick={onCancel}
        >
          取消
        </Button>
        <Button
          type="button"
          variant="danger"
          size="sm"
          loading={submitting}
          onClick={() => void onConfirm()}
        >
          确认删除
        </Button>
      </div>
    </div>
  );
}
