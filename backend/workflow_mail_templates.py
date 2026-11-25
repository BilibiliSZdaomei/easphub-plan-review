"""Plain-text mail for plan workflow events. All fields come from the event snapshot."""
from typing import NamedTuple
from urllib.parse import urlsplit


SENDER_NAME = 'EASPhub 计划审核'


class EventCopy(NamedTuple):
    subject: str
    chinese: str
    english: str


EVENT_COPY = {
    'SUBMITTED': EventCopy(
        '待领取复审 / Ready for review',
        '计划已提交。请在平台领取后开始复审。',
        'The plan is ready for review. Claim it in the workspace to begin.',
    ),
    'RESUBMITTED': EventCopy(
        '修改后重新提交 / Resubmitted for review',
        '计划员已重新提交修改后的版本。请领取新版本并复审。',
        'The planner has resubmitted the revised plan. Claim the new version to review it.',
    ),
    'CLAIMED': EventCopy(
        '复审已领取 / Review claimed',
        '这份计划已有复审员领取，其他复审员无需处理。',
        'A reviewer has claimed this plan. Other reviewers have no action to take.',
    ),
    'TRANSFERRED': EventCopy(
        '复审已转交给你 / Review assigned to you',
        '这份计划已转交给你。请接着审核剩余物料，并给出整单结论。',
        'The review has been transferred to you. Review the remaining lines and decide the outcome for the whole plan.',
    ),
    'RETURNED': EventCopy(
        '整单退回修改 / Changes requested',
        '复审员已退回整份计划。请查看复审结果，修改后重新提交。',
        'The reviewer has returned the whole plan. Check the review decisions, revise the plan and resubmit it.',
    ),
    'APPROVED': EventCopy(
        '整单通过 / Plan approved',
        '整份计划已通过。计划员可按核准数量安排补货。',
        'The whole plan is approved. The planner can arrange replenishment using the approved quantities.',
    ),
    'REJECTED': EventCopy(
        '整单不批准 / Plan rejected',
        '复审员已整单不批准，本版所有物料均不执行。可打开计划查看复审结果。',
        'The whole plan was rejected. No lines in this version should be fulfilled. Open the plan to see the review decisions.',
    ),
}

COUNTRIES = {
    'NL': 'Netherlands', 'UK': 'United Kingdom', 'DE': 'Germany', 'IT': 'Italy',
    'FR': 'France', 'ES': 'Spain', 'PL': 'Poland', 'CH': 'Switzerland',
    'SE': 'Sweden', 'UZ': 'Uzbekistan',
}


def _one_line(value):
    # Plan titles and display names are user-entered text.
    text = ''.join(char if char.isprintable() else ' ' for char in str(value or ''))
    return ' '.join(text.split()) or '—'


def _plan_link(url):
    if not isinstance(url, str) or not url or any(c.isspace() or not c.isprintable() or c == '\\' for c in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme in ('http', 'https') and parsed.hostname and parsed.username is None and parsed.password is None:
            return url
    except ValueError:
        pass
    return None


def render_workflow_mail(event, *, plan_number, plan_title, market, warehouse_name,
                         warehouse_code, period, line_count, actor_name, plan_url=None):
    if event not in EVENT_COPY:
        raise ValueError(f'Unknown plan mail event: {event!r}')
    if type(line_count) is not int or line_count < 0:
        raise ValueError('Plan mail requires a nonnegative line count')
    copy = EVENT_COPY[event]
    number = _one_line(plan_number)
    market = _one_line(market).upper()
    if market == 'GB':
        market = 'UK'
    country = f'{COUNTRIES[market]} ({market})' if market in COUNTRIES else market
    warehouse = _one_line(warehouse_name)
    code = _one_line(warehouse_code)
    if code != '—' and code != warehouse:
        warehouse = f'{warehouse} ({code})'
    body = [
        copy.chinese, copy.english, '',
        f'计划 / Plan: {_one_line(plan_title)}',
        f'计划编号 / Plan ID: {number}',
        f'国家 / Country: {country}',
        f'仓库 / Warehouse: {warehouse}',
        f'周期 / Period: {_one_line(period)}',
        f'物料行数 / Lines: {line_count}',
        f'操作人 / Action by: {_one_line(actor_name)}',
    ]
    link = _plan_link(plan_url)
    if link:
        body.extend(('', f'查看计划 / Open plan: {link}'))
    return {
        'sender_name': SENDER_NAME,
        'subject': f'{number} · {copy.subject}',
        'text': '\n'.join(body),
    }


def render_payload(payload, plan_url=None):
    """Render only whitelisted summary fields, never line items or free-text review notes."""
    return render_workflow_mail(
        payload['kind'], plan_number=payload['plan_number'], plan_title=payload['plan_title'],
        market=payload['market'], warehouse_name=payload['warehouse_name'],
        warehouse_code=payload['warehouse_code'], period=payload['period'],
        line_count=payload['row_count'], actor_name=payload['actor_name'], plan_url=plan_url,
    )
