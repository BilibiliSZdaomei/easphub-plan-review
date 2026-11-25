const validationSuffixes: ReadonlyArray<readonly [string, string]> = [
  ['的公式没有计算结果，请重算并保存', 'has no cached formula result. Recalculate and save the file.'],
  ['必填，请填写非负数量，无则填 0', 'is required. Enter a non-negative quantity, or 0 for none.'],
  ['缺失，请补齐来源数据', 'is missing. Complete the source data.'],
  ['不是有效数字', 'must be a valid number.'],
  ['必须大于零', 'must be greater than zero.'],
  ['超出范围', 'is out of range.'],
  ['不能为负数', 'cannot be negative.'],
  ['应填写非负数', 'must be non-negative.'],
  ['不符合订货步长', 'does not match the order increment.'],
  ['数值过长', 'is too long.'],
  ['数值无效', 'has an invalid value.'],
  ['请填是或否', 'must be Yes or No.'],
  ['格式无效', 'has an invalid format.'],
]

/** Formats backend diagnostics while retaining source identifiers exactly as entered. */
export function adminMessage(text:string, lookup:(text:string)=>string):string|undefined {
  const malformed = /^第 (\d+) 行格式有误，请核对分隔符或引号$/.exec(text)
  if(malformed) return `Row ${malformed[1]} has an invalid delimiter or quotation mark.`
  const materialNumber = /^第 (\d+) 行 · 物料号为空、过长或重复 · (.*)$/.exec(text)
  if(materialNumber) return `Row ${materialNumber[1]} · Material number missing, too long or duplicated · ${materialNumber[2]}`
  const row = /^第 (\d+) 行 (.*?) · (.+)$/.exec(text)
  if(row) return `Row ${row[1]} · ${row[2]} · ${adminMessage(row[3],lookup) ?? lookup(row[3])}`
  const material = /^物料 (.*?) · (.+)$/.exec(text)
  if(material) return `Material ${material[1]} · ${adminMessage(material[2],lookup) ?? lookup(material[2])}`
  const duplicateHeader = /^表头重复 · (.*)$/.exec(text)
  if(duplicateHeader) return `Duplicate header · ${duplicateHeader[1]}`
  const keywords = /^(small|manual|maintenance|no_stock|dangerous)(需要1至100个关键词|包含空白或过长关键词)$/.exec(text)
  if(keywords) return keywords[2].startsWith('需要') ? `${keywords[1]} requires 1–100 keywords.` : `${keywords[1]} contains an empty or overly long keyword.`
  const missingBase = /^基础快照未包含物料：(.*)$/.exec(text)
  if(missingBase) return `Materials missing from the base snapshot: ${missingBase[1]}`
  const uom = /^计量单位不同，请先按标准单位转换：(.*)$/.exec(text)
  if(uom) return `Convert the quantity to the standard unit first: ${uom[1]}`
  const net = /^审核前净额无效：(.*)$/.exec(text)
  if(net) return `Invalid pre-review net supply: ${net[1]}`
  const component = /^分项模式缺少有效的(.+?)：(.*)$/.exec(text)
  if(component) return `Missing valid ${lookup(component[1])} for component calculation: ${component[2]}`
  for(const [suffix,english] of validationSuffixes){
    if(!text.endsWith(suffix))continue
    const field=text.slice(0,-suffix.length), label=lookup(field)
    if(label!==field)return label+' '+english
  }
  return undefined
}
