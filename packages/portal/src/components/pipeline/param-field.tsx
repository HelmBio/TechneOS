"use client";

import { useEffect, useState, type ReactElement } from "react";

type Schema = Record<string, unknown>;

/**
 * Number/integer input that keeps its own text state so partial entries like
 * "0.", "-", or "1e" stay visible while typing (coercing every keystroke would
 * collapse "0." → 0 and strip the decimal). Emits a typed number when the text
 * parses, the raw string while it doesn't, and null when empty.
 */
function NumericParamInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  placeholder?: string;
  className: string;
}): ReactElement {
  const [text, setText] = useState(value == null ? "" : String(value));

  // Resync from the parent only when the value changes to something the current
  // text doesn't already represent (e.g. a default applied on expose) — so we
  // never clobber an in-progress entry like "0.".
  useEffect(() => {
    const current = text === "" ? null : Number(text);
    const matches = value === current || (value == null && text === "");
    if (!matches) setText(value == null ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      type="text"
      inputMode="decimal"
      value={text}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        if (raw === "") return onChange(null);
        const n = Number(raw);
        onChange(raw.trim() !== "" && Number.isFinite(n) ? n : raw);
      }}
      placeholder={placeholder}
      className={className}
    />
  );
}

/** Coerce a text input to the JSON type the schema declares ("" → null). */
export function coerceScalar(raw: string, type: unknown): unknown {
  if (raw === "") return null;
  if (type === "integer" || type === "number") {
    const n = Number(raw);
    return raw.trim() !== "" && Number.isFinite(n) ? n : raw;
  }
  return raw;
}

/** True when a parameter value should count as "not provided". */
export function isEmptyParam(v: unknown): boolean {
  return v == null || v === "" || (Array.isArray(v) && v.length === 0);
}

/**
 * The value control for a single schema parameter, chosen from the property's
 * schema: boolean select, array-of-enum multi-pick, single-enum select, or a
 * typed text input. Operates on **typed** JSON values (number/boolean/array/
 * string), so callers store the parsed value directly — no stringify/parse.
 *
 * Shared by the run dialog and the pipeline-version bindings editor so both
 * forms render identical widgets. Layout/labels live in the callers; this is
 * only the control. Pass `compact` for the denser bindings-editor styling.
 */
export function SchemaParamControl({
  propDef,
  value,
  onChange,
  placeholder,
  compact = false,
}: {
  propDef: Schema;
  value: unknown;
  onChange: (v: unknown) => void;
  placeholder?: string;
  compact?: boolean;
}): ReactElement {
  const type = propDef.type;
  const box = compact
    ? "rounded-md border border-gray-300 px-2 py-1 text-xs"
    : "rounded-md border border-gray-300 px-3 py-2 text-sm";
  const enumOpts = Array.isArray(propDef.enum) ? (propDef.enum as unknown[]) : [];
  const itemEnum = (propDef.items as { enum?: unknown[] } | undefined)?.enum;
  const multiEnumOpts =
    type === "array" && Array.isArray(itemEnum) ? (itemEnum as unknown[]) : [];

  if (type === "boolean") {
    return (
      <select
        value={value === true ? "true" : value === false ? "false" : ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : e.target.value === "true")
        }
        className={box}
      >
        <option value="">(unset)</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  if (multiEnumOpts.length > 0) {
    const selected = Array.isArray(value) ? (value as unknown[]) : [];
    return (
      <div className="flex flex-wrap gap-1.5">
        {multiEnumOpts.map((o) => {
          const sel = selected.some((x) => String(x) === String(o));
          return (
            <button
              type="button"
              key={String(o)}
              onClick={() =>
                onChange(
                  sel
                    ? selected.filter((x) => String(x) !== String(o))
                    : [...selected, o],
                )
              }
              className={`rounded-full border px-2 py-0.5 font-medium transition-colors ${
                compact ? "text-[11px]" : "text-xs"
              } ${
                sel
                  ? "border-blue-400 bg-blue-100 text-blue-700"
                  : "border-gray-300 bg-white text-gray-600 hover:bg-gray-100"
              }`}
            >
              {String(o)}
            </button>
          );
        })}
      </div>
    );
  }

  if (enumOpts.length > 0) {
    return (
      <select
        value={value == null ? "" : String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onChange(null);
          const match = enumOpts.find((o) => String(o) === raw);
          onChange(match === undefined ? raw : match);
        }}
        className={box}
      >
        <option value="">(unset)</option>
        {enumOpts.map((o) => (
          <option key={String(o)} value={String(o)}>
            {String(o)}
          </option>
        ))}
      </select>
    );
  }

  if (type === "number" || type === "integer") {
    return (
      <NumericParamInput
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={`w-full ${box}`}
      />
    );
  }

  return (
    <input
      type="text"
      value={value == null ? "" : String(value)}
      onChange={(e) => onChange(coerceScalar(e.target.value, type))}
      placeholder={placeholder}
      className={`w-full ${box}`}
    />
  );
}
