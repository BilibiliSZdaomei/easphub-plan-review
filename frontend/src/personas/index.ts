import catalog from './catalog.json'
import layers from './layers.json'

// Personas by Draftbit, MIT, commit 7b5234c44b3cef49d483b1462398bc9ea07bfa12.
// catalog.json is src/data/config.json. layers.json contains the 63 templates selected
// by src/components/SvgLoader.res. Its geometry is unchanged; fragment IDs are scoped,
// the embedded XML declaration and the Hat template's unmatched closing tag removed.
// Distributed licence: public/assets/personas-7b5234c44b3c/LICENSE.txt.
export const styleOptions = {
  hair: catalog.hairStyles,
  facialHair: catalog.facialHairStyles,
  body: catalog.bodyStyles,
  eyes: catalog.eyeStyles,
  mouth: catalog.mouthStyles,
  nose: catalog.noseStyles,
  accessories: catalog.accessoryStyles,
} as const

export const colorPalettes = {
  skinColor: catalog.skinColors,
  hairColor: catalog.hairColors,
  facialHairColor: catalog.facialHairColors,
  bodyColor: catalog.bodyColors,
  accessoriesColor: catalog.accessoryColors,
  bgColor: catalog.bgColors,
} as const

export type StyleKey = keyof typeof styleOptions
export type ColorKey = keyof typeof colorPalettes
export type AvatarConfig = Record<StyleKey | ColorKey,string>
export type AvatarPreset = 'plan' | 'parts' | 'order'

// These starting points are the shared platform's approved avatar-preview-config.json.
// Colours for invisible layers initialise the controls when the user enables the layer.
const plan: AvatarConfig = {
  hair:'Shortcombover', facialHair:'None', body:'Round', eyes:'Glasses', mouth:'Smile',
  nose:'Smallround', accessories:'None', skinColor:'E6AA8A', hairColor:'423E46',
  facialHairColor:'423E46', bodyColor:'8C7EAC', accessoriesColor:'F3B63A', bgColor:'E5E0F3',
}
export const presetConfigs: Record<AvatarPreset,AvatarConfig> = {
  plan,
  parts: {...plan, hair:'Curlybun', body:'Square', eyes:'Wink', nose:'Mediumround',
    bgColor:'DFE8E3', skinColor:'C88970', hairColor:'3E3537', facialHairColor:'3E3537', bodyColor:'7C958C'},
  order: {...plan, hair:'Bobcut', body:'Oval', eyes:'Sideeye', mouth:'Bigsmile',
    bgColor:'EAE2DD', skinColor:'E6B498', hairColor:'51403E', facialHairColor:'51403E', bodyColor:'A98F84'},
}

const styleKeys=Object.keys(styleOptions) as StyleKey[]
const colorKeys=Object.keys(colorPalettes) as ColorKey[]
const keys=[...styleKeys,...colorKeys]
export function equalConfig(a:AvatarConfig,b:AvatarConfig):boolean {
  return keys.every(key=>a[key]===b[key])
}

function pick(options:readonly string[]):string {
  return options[Math.floor(Math.random()*options.length)]
}

export function randomConfig():AvatarConfig {
  const result={...plan}
  for(const key of styleKeys)result[key]=pick(styleOptions[key])
  // The original generator gives an accessory-free portrait an additional 60% weighting.
  if(Math.random()<0.6)result.accessories='None'
  for(const key of colorKeys)result[key]=pick(colorPalettes[key])
  return result
}

const artwork: Readonly<Record<string,string>> = layers
const cache=new Map<string,string>()
const maxCached=128
function layer(name:string,color:string):string {
  return name==='None'?'':artwork[name].replaceAll('__COLOR__','#'+color)
}

export function avatarSrc(config:AvatarConfig):string {
  const validated={...plan}
  for(const key of styleKeys){
    if(styleOptions[key].includes(config[key]))validated[key]=config[key]
  }
  for(const key of colorKeys){
    if(typeof config[key]==='string' && /^[0-9a-f]{6}$/i.test(config[key]))validated[key]=config[key].toUpperCase()
  }
  const id=keys.map(key=>validated[key]).join('|')
  const saved=cache.get(id)
  if(saved)return saved

  // Same paint order as the original Worker's composeSvg, on its native 64x64 viewBox.
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'+[
    layer('Background',validated.bgColor),
    layer('Skin',validated.skinColor),
    layer(validated.hair,validated.hairColor),
    layer(validated.body,validated.bodyColor),
    layer(validated.mouth,'000000'),
    layer(validated.facialHair,validated.facialHairColor),
    layer(validated.nose,validated.skinColor),
    layer(validated.eyes,'000000'),
    layer(validated.accessories,validated.accessoriesColor),
  ].join('')+'</svg>'
  const uri='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg)
  if(cache.size>=maxCached)cache.delete(cache.keys().next().value!)
  cache.set(id,uri)
  return uri
}
