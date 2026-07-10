"use client";

export interface GrowingTableProps {
  items: {
    properties: Record<string, Record<string, unknown>>;
    required?: string[];
  };
  value: Record<string, unknown>[];
  onChange: (value: Record<string, unknown>[]) => void;
  label: string;
  required?: boolean;
  description?: string;
}

export default function GrowingTable({
  items,
  value,
  onChange,
  label,
  required = false,
  description,
}: GrowingTableProps) {
  const itemRequired = items.required || [];
  const colKeys = Object.keys(items.properties);
  const arr = value;

  const addRow = () => {
    const newRow: Record<string, unknown> = {};
    for (const [k, p] of Object.entries(items.properties)) {
      if (p.default !== undefined) {
        newRow[k] = p.default;
      }
    }
    onChange([...arr, newRow]);
  };

  const removeRow = (idx: number) => {
    onChange(arr.filter((_, i) => i !== idx));
  };

  const updateRow = (idx: number, field: string, val: unknown) => {
    const updated = arr.map((row, i) =>
      i === idx ? { ...row, [field]: val } : row,
    );
    onChange(updated);
  };

  if (colKeys.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">
          {label}
          {description && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              — {description}
            </span>
          )}
          {required ? <span className="text-red-500 ml-1">*</span> : null}
        </span>
        <button
          type="button"
          onClick={addRow}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          + Add
        </button>
      </div>
      {arr.length === 0 ? (
        <p className="text-xs text-gray-400 italic">No items added.</p>
      ) : (
        <div className="space-y-2">
          {arr.map((row, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3"
            >
              {colKeys.map((col) => {
                const subProp = items.properties[col];
                const subLabel = (subProp.title as string) || col;
                const subRequired = itemRequired.includes(col);

                if (subProp.enum) {
                  return (
                    <label key={col} className="block flex-1 min-w-0">
                      <span className="block text-xs font-medium text-gray-600 mb-0.5">
                        {subLabel}
                      </span>
                      <select
                        value={(row?.[col] as string) || ""}
                        onChange={(e) => updateRow(idx, col, e.target.value)}
                        className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none bg-white"
                      >
                        <option value="">Select...</option>
                        {(subProp.enum as string[]).map((opt: string) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                }

                if (subProp.type === "number" || subProp.type === "integer") {
                  return (
                    <label key={col} className="block flex-1 min-w-0">
                      <span className="block text-xs font-medium text-gray-600 mb-0.5">
                        {subLabel}
                        {subRequired ? " *" : ""}
                      </span>
                      <input
                        type="number"
                        value={(row?.[col] as number | undefined) ?? ""}
                        onChange={(e) =>
                          updateRow(
                            idx,
                            col,
                            e.target.value ? Number(e.target.value) : null,
                          )
                        }
                        className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                      />
                    </label>
                  );
                }

                if (subProp.type === "boolean") {
                  return (
                    <label
                      key={col}
                      className="flex items-center gap-1.5 flex-1 min-w-0"
                    >
                      <input
                        type="checkbox"
                        checked={!!(row?.[col] as boolean | undefined)}
                        onChange={(e) => updateRow(idx, col, e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-xs font-medium text-gray-600">
                        {subLabel}
                      </span>
                    </label>
                  );
                }

                return (
                  <label key={col} className="block flex-1 min-w-0">
                    <span className="block text-xs font-medium text-gray-600 mb-0.5">
                      {subLabel}
                      {subRequired ? " *" : ""}
                    </span>
                    <input
                      type="text"
                      value={(row?.[col] as string) || ""}
                      onChange={(e) => updateRow(idx, col, e.target.value)}
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </label>
                );
              })}
              <button
                type="button"
                onClick={() => removeRow(idx)}
                className="mt-4 shrink-0 text-red-400 hover:text-red-600 text-sm leading-none"
                title="Remove"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
