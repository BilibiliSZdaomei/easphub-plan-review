// A bare SMTP address. Preserve the local part, normalise the DNS domain.
export function emailAddress(value:string):string {
  const address=value.trim()
  if(!address||address.length>254||/[^\x20-\x7e]/.test(value))return ''
  const pieces=address.split('@')
  if(pieces.length!==2)return ''
  const [local,domain]=pieces
  if(local.length>64||local.split('.').some(atom=>!/^[A-Z0-9!#$%&'*+\/=?^`_{}|~-]+$/i.test(atom)))return ''
  const labels=domain.split('.')
  if(labels.length<2||labels.some(label=>!/^[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?$/i.test(label)))return ''
  return local+'@'+domain.toLowerCase()
}
