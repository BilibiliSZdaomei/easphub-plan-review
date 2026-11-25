import {getLanguage, systemText, systemMessage} from './i18n'

// Only generated recommendations and validation messages use these patterns.
// Captured quantities, material numbers and reviewer comments remain verbatim.
const quantityRules: [string, string][] = [
  ['必填，请填写非负数量，无则填 0',' is required. Enter a non-negative quantity, or 0 for none.'],
  ['缺失，请补齐来源数据',' is missing. Complete the source data.'],
  ['不能为负数',' cannot be negative.'],
  ['不符合订货步长',' must be a multiple of the order increment.'],
  ['应填写非负数',' must be a non-negative number.'],
]
export function planMessage(message: string): string {
  if (!message || getLanguage() !== 'en') return message
  const exact = systemText(message)
  if (exact !== message) return exact
  const returned = '上轮要求修改 · '
  if (message.startsWith(returned)) return 'Changes requested in the last review · '+message.slice(returned.length)
  if (message.includes('；')) return message.split('；').map(planMessage).join('; ')
  const advice = /^(备货多，建议减少|备货少，建议增加)([\d,.]+)(.*)$/.exec(message)
  if (advice) {
    const action = advice[1] === '备货多，建议减少' ? 'Excess stock. Reduce by' : 'Low stock. Increase by'
    return [action, advice[2], advice[3]].filter(Boolean).join(' ')
  }
  for (const [ending,english] of quantityRules) {
    if (message.endsWith(ending)) return systemText(message.slice(0,-ending.length))+english
  }
  const separator = message.indexOf('：')
  if (separator > 0) {
    const first = message.slice(0,separator), rest = message.slice(separator+1)
    const translated = systemText(rest)
    if (translated !== rest) return systemText(first)+': '+translated
  }
  return systemMessage(message)
}

const enumColumns = new Set(['status','decision','delay_replenishment','is_key_model','override'])
const sizeFlags = new Set(['高单价大体积','高单价','大体积','大金额','高金额','高价值','大金额、大体积','高单价、大体积'])
export function tableDisplay(key:string, value:unknown):string {
  const text = String(value ?? '')
  if (key==='size') return sizeFlags.has(text) ? systemText(text) : text
  if (key==='attention' || key==='advice' || key==='turnover_warning') return planMessage(text)
  return enumColumns.has(key) ? systemText(text) : text
}
