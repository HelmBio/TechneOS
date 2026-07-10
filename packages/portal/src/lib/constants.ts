export const TOOL_CATEGORIES = [
  "docking",
  "scoring",
  "admet",
  "ml",
  "general",
  "molecular-dynamics",
  "quantum-chemistry",
  "cheminformatics",
  "bioinformatics",
  "machine-learning",
  "data-processing",
  "other",
] as const;

export type ToolCategory = (typeof TOOL_CATEGORIES)[number];
