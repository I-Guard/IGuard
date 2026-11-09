import type { Role } from "../types/api";

export const ROLE_RANK: Record<Role, number> = { VIEWER: 1, OPERATOR: 2, ADMIN: 3 };

export function hasRole(roles: Role[], minimum: Role): boolean {
  return roles.some((r) => ROLE_RANK[r] >= ROLE_RANK[minimum]);
}
