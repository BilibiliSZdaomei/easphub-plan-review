export const roleNames: Record<string, string> = {
  PLANNER: '计划员',
  REVIEWER: '复审员',
  ADMIN: '管理员',
}

export function canReview(roles: string[]) {
  return roles.includes('REVIEWER') || roles.includes('ADMIN')
}

export function canPlan(roles: string[]) {
  return roles.includes('PLANNER') || canReview(roles)
}
