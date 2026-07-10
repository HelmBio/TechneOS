/**
 * Client-side RBAC permission checker.
 * Validates a list of permissions (from the user's JWT) against a required resource/action/scope.
 */

const SCOPE_HIERARCHY = ["own", "team", "org", "platform"] as const;

function scopeIncludes(granted: string, required: string): boolean {
  if (granted === "*" || required === "*") return true;
  const gLevel = SCOPE_HIERARCHY.indexOf(granted as typeof SCOPE_HIERARCHY[number]);
  const rLevel = SCOPE_HIERARCHY.indexOf(required as typeof SCOPE_HIERARCHY[number]);
  if (gLevel === -1 || rLevel === -1) return granted === required;
  return gLevel >= rLevel;
}

export function hasPermission(
  permissions: string[],
  resource: string,
  action: string,
  scope: string
): boolean {
  for (const perm of permissions) {
    const [pRes, pAct, pScope] = perm.split(":");
    if (
      (pRes === "*" || pRes === resource) &&
      (pAct === "*" || pAct === action) &&
      scopeIncludes(pScope, scope)
    ) {
      return true;
    }
  }
  return false;
}
