// The list health cell renders these fields. A changed issue must invalidate
// the memoized list even when no other client status field has changed.
const ISSUE_FIELDS = [
  "code", "severity", "title", "message", "suggested_resolution", "required_role",
];

export function sameClientHealthIssues(a, b) {
  const left = Array.isArray(a) ? a : [];
  const right = Array.isArray(b) ? b : [];
  if (left.length !== right.length) return false;
  return left.every((issue, index) =>
    ISSUE_FIELDS.every((field) =>
      (issue?.[field] ?? null) === (right[index]?.[field] ?? null),
    ),
  );
}
