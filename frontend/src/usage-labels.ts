import {tr} from './i18n'

export const usagePages = {
  home:['工作台','Dashboard'],
  plans:['计划列表','Plan list'],
  detail:['计划明细','Plan details'],
  history:['历史记录','History'],
  data:['数据中心','Data centre'],
  rules:['审核标准','Review standards'],
  accounts:['人员与权限','People and permissions'],
  inbox:['通知中心','Notifications'],
  profile:['个人账户','My account'],
  usage:['使用统计','Usage insights'],
} as const

export const usageTargets = {
  navigation:['页面导航','Navigation'],
  button:['按钮','Button'],
  input:['输入框','Input'],
  select:['选择选项','Select an option'],
  table:['表格','Table'],
  filter:['筛选','Filter'],
  dialog:['弹窗','Dialog'],
  create:['新建','Create'],
  import:['导入','Import'],
  export:['导出','Export'],
  save:['保存','Save'],
  submit:['提交','Submit'],
  approve:['批准','Approve'],
  reject:['不批准','Decline'],
  return:['退回修改','Return for changes'],
  undo:['撤销','Undo'],
  redo:['重做','Redo'],
  transfer:['转交','Transfer'],
  account:['账户操作','Account controls'],
  other:['其他位置','Other areas'],
} as const

export type UsagePage = keyof typeof usagePages
export type UsageTarget = keyof typeof usageTargets

export function usagePageLabel(key:UsagePage) {
  const label=usagePages[key]
  return label?tr(label[0],label[1]):tr('其他页面','Other pages')
}

export function usageTargetLabel(key:UsageTarget) {
  const label=usageTargets[key]
  return label?tr(label[0],label[1]):tr('其他操作','Other actions')
}
