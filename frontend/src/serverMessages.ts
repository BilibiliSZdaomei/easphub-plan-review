/** Format server validation messages for display. Captured material numbers and file headers stay verbatim. */
export function englishServerMessage(value: string, lookup: (fragment: string) => string): string | undefined {
  if (value.startsWith('参数检查未通过：')) {
    return 'Check the rule parameters: ' + value.slice('参数检查未通过：'.length).split('；').map(lookup).join('; ')
  }
  for (const [prefix, english] of Object.entries(rawContext)) {
    if (value.startsWith(prefix)) return english + value.slice(prefix.length)
  }
  for (const [prefix, english] of Object.entries(fieldLists)) {
    if (value.startsWith(prefix)) return english + value.slice(prefix.length).split('、').map(lookup).join(', ')
  }
  if (value.startsWith('更换率：')) return 'Replacement rate: ' + lookup(value.slice('更换率：'.length))
}

const rawContext: Record<string, string> = {
  '服务处理失败，请联系管理员并提供请求编号 ': 'The request failed. Contact your administrator and provide request ID ',
  '未在选定快照找到物料：': 'Material missing from the selected snapshot: ',
  '新快照缺少物料：': 'Material missing from the new snapshot: ',
  '同一计划不能重复添加物料：': 'Duplicate material in this plan: ',
  '仓库编码重复：': 'Duplicate warehouse code: ',
  '仓库编码已属于其他市场：': 'Warehouse code already belongs to another market: ',
}
const fieldLists: Record<string, string> = {
  '审核原表缺少列：': 'Missing review workbook columns: ',
  '这些字段由审核标准维护 · ': 'Fields controlled by the review standard: ',
}
