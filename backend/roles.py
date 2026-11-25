"""Warehouse-scoped account roles, ordered by the business operations they include."""
ROLE_NAMES = {'PLANNER':'计划员', 'REVIEWER':'复审员', 'ADMIN':'管理员'}
LEVEL = {'PLANNER':1, 'REVIEWER':2, 'ADMIN':3}


def account_role(user):
    """Accept historical multi-role rows, never promoting an obsolete technical grant."""
    return max((key for key in user.roles if key in LEVEL), key=LEVEL.get, default=None)


def has_role(user, minimum):
    return LEVEL.get(account_role(user), 0) >= LEVEL[minimum]
