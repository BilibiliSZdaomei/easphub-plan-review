import {useEffect, useId, useState, type KeyboardEvent} from 'react'
import {Check, ChevronRight, Shuffle} from 'lucide-react'
import {tr} from './i18n'
import {
  avatarSrc, colorPalettes, equalConfig, presetConfigs, randomConfig, styleOptions,
  type AvatarConfig, type ColorKey, type StyleKey,
} from './personas'
import './avatar-editor.css'

type TextPair = readonly [zh:string,en:string]
type Category = {id:string; label:TextPair; style?:StyleKey; color?:ColorKey}
const categories:readonly Category[] = [
  {id:'hair', label:['发型','Hair'], style:'hair', color:'hairColor'},
  {id:'skin', label:['肤色','Skin'], color:'skinColor'},
  {id:'eyes', label:['眼睛','Eyes'], style:'eyes'},
  {id:'nose', label:['鼻子','Nose'], style:'nose'},
  {id:'mouth', label:['嘴型','Mouth'], style:'mouth'},
  {id:'facialHair', label:['胡须','Facial hair'], style:'facialHair', color:'facialHairColor'},
  {id:'body', label:['服装','Clothing'], style:'body', color:'bodyColor'},
  {id:'accessories', label:['配饰','Accessories'], style:'accessories', color:'accessoriesColor'},
  {id:'background', label:['背景','Background'], color:'bgColor'},
  {id:'presets', label:['预设搭配','Presets']},
]
const styles:Record<string,TextPair> = {
  Bald:['光头','Bald'], Hat:['宽檐帽','Brimmed hat'], Balding:['稀疏短发','Balding'], Bigcurls:['大卷发','Big curls'],
  Bobbangs:['齐刘海短发','Bob with bangs'], Bobcut:['波波头','Bob'], Buncurls:['卷发丸子头','Curly bun with fringe'],
  Buzzcut:['寸头','Buzz cut'], Curlybun:['高卷髻','High curly bun'], Hightopcurly:['高顶卷发','High-top curls'],
  Long:['长发','Long hair'], Pigtails:['双马尾','Pigtails'], Shortcombover:['侧分短发','Short side part'],
  Beanie:['针织帽','Beanie'], Bunundercut:['铲边发髻','Undercut bun'], Extralong:['超长发','Extra-long hair'],
  Fade:['渐层短发','Fade'], Mohawk:['莫霍克头','Mohawk'], Shortcomboverchops:['侧分长鬓角','Side part with sideburns'],
  Sidebuzz:['侧边寸头','Side buzz'], Straightbun:['直发髻','Straight bun'],
  BeardMustache:['络腮胡','Beard and moustache'], Mustache:['小胡子','Moustache'], None:['无','None'],
  Goatee:['山羊胡','Goatee'], Shadow:['胡茬','Stubble'], Soulpatch:['唇下胡','Soul patch'], Walrus:['海象胡','Walrus moustache'],
  Oval:['椭圆轮廓','Oval cut'], Round:['圆形轮廓','Round cut'], Square:['方形轮廓','Square cut'],
  Checkered:['格纹','Checks'], Hoodie:['连帽衫','Hoodie'], Stripes:['条纹','Stripes'],
  Glasses:['眼镜','Glasses'], Happy:['笑眼','Happy'], Open:['睁眼','Open'], Sleepy:['困倦','Sleepy'],
  Sunglasses:['墨镜','Sunglasses'], Wink:['眨眼','Wink'], Closed:['闭眼','Closed'],
  Hearts:['爱心眼','Hearts'], Dizzy:['眩晕','Dizzy'], Sideeye:['侧目','Side-eye'],
  Bigsmile:['灿笑','Big smile'], Frown:['撇嘴','Frown'], Lips:['唇形','Lips'], Pacifier:['奶嘴','Pacifier'],
  Smile:['微笑','Smile'], Smirk:['抿嘴笑','Smirk'], Surprise:['惊讶','Surprised'], Grin:['咧嘴笑','Grin'],
  Tongue:['吐舌','Tongue'], Whistle:['吹口哨','Whistling'], Laugh:['大笑','Laugh'],
  Mediumround:['中圆鼻','Round nose'], Smallround:['小圆鼻','Small round nose'], Wrinkles:['皱鼻','Wrinkled nose'],
  Pointed:['尖鼻','Pointed nose'], Button:['纽扣鼻','Button nose'],
  Earring:['单耳环','Single earring'], Earrings:['双耳环','Earrings'],
}
const presetNames={plan:['紫色眼镜','Violet glasses'],parts:['绿色卷发','Green curls'],order:['米色短发','Beige bob']} as const
const presetIds=Object.keys(presetNames) as (keyof typeof presetNames)[]

type EditorProps = {value:AvatarConfig|null;onChange:(config:AvatarConfig)=>void;disabled?:boolean}
function Choice({name,label,image,selected,onChange,focusPart}:{
  name:string;label:string;image:string;selected:boolean;onChange:()=>void;focusPart?:StyleKey
}) {
  return <label className="av-choice">
    <input type="radio" name={name} aria-label={label} checked={selected} onChange={onChange}/>
    <span className="av-choice-card">
      <span className="av-choice-preview" data-feature={focusPart}>
        <img src={image} alt="" width={48} height={48} draggable={false}/>
      </span>
      <span className="av-choice-label">{label}</span>
      {selected&&<Check className="av-choice-check" size={11} aria-hidden="true"/>}
    </span>
  </label>
}

function ColourPicker({value,onChange,colors,name,active}:{value:string;onChange:(color:string)=>void;colors:readonly string[];name:string;active:boolean}){
  const [draft,setDraft]=useState('#'+value)
  useEffect(()=>setDraft('#'+value),[value,active])
  const valid=/^#?[\da-f]{6}$/i.test(draft)
  function select(color:string){setDraft('#'+color);onChange(color)}
  function type(text:string){
    setDraft(text)
    if(/^#?[\da-f]{6}$/i.test(text))onChange(text.replace('#','').toUpperCase())
  }
  return <fieldset className="av-colors"><legend>{tr('颜色','Colour')}</legend>
    <div className="av-swatches">
      {colors.map(color=><label key={color} className="av-swatch" title={'#'+color}>
        <input type="radio" name={name} aria-label={'#'+color} checked={active&&value===color} onChange={()=>select(color)}/>
        <span style={{backgroundColor:'#'+color}}/>
      </label>)}
    </div>
    <div className="av-custom">
      <span>{tr('自定义颜色','Custom colour')}</span>
      <label className="av-color-input" title={tr('打开取色器','Open colour picker')}>
        <span aria-hidden="true" style={{backgroundColor:'#'+value}}/>
        <input type="color" value={'#'+value} aria-label={tr('打开取色器','Open colour picker')} onChange={e=>select(e.target.value.slice(1).toUpperCase())}/>
      </label>
      <input className="av-hex" type="text" aria-label={tr('十六进制色值','Hex colour')} aria-invalid={!valid}
        value={draft} required pattern="#?[0-9A-Fa-f]{6}" placeholder="#RRGGBB" maxLength={7} spellCheck={false}
        onChange={e=>type(e.target.value)} onBlur={()=>{if(valid)setDraft('#'+value)}}/>
    </div>
    {!valid&&<small className="av-color-error">{tr('请输入六位十六进制色值，例如 #FFCC22。','Enter a six-digit hex colour, e.g. #FFCC22.')}</small>}
  </fieldset>
}

export default function AvatarEditor({value:choice,onChange,disabled=false}:EditorProps){
  const value=choice??presetConfigs.plan
  const [category,setCategory]=useState(categories[0])
  const id=useId()
  const {style,color}=category
  const activeLabel=tr(...category.label)
  function navigate(e:KeyboardEvent<HTMLButtonElement>,index:number){
    const end=categories.length-1
    const next=e.key==='ArrowDown'?(index+1)%(end+1):e.key==='ArrowUp'?(index+end)%(end+1):e.key==='Home'?0:e.key==='End'?end:null
    if(next===null)return
    e.preventDefault();setCategory(categories[next]);document.getElementById(id+'-tab-'+categories[next].id)?.focus()
  }
  return <fieldset className="avatar-editor" disabled={disabled} aria-label={tr('头像部件','Avatar features')}>
    <div className="av-editor-shell">
      <div className="av-category-tabs" role="tablist" aria-label={tr('头像类别','Avatar categories')} aria-orientation="vertical">
        {categories.map((c,i)=><button type="button" role="tab" key={c.id} id={id+'-tab-'+c.id}
          aria-selected={c.id===category.id} tabIndex={c.id===category.id?0:-1} aria-controls={id+'-panel'}
          onKeyDown={e=>navigate(e,i)} onClick={()=>setCategory(c)}>
          {tr(...c.label)}<ChevronRight size={13} aria-hidden="true"/>
        </button>)}
      </div>
      <div className="av-editor-main" id={id+'-panel'} role="tabpanel" aria-label={activeLabel}>
        <div className="av-editor-toolbar">
          <h3>{activeLabel}</h3>
          <select aria-label={tr('头像类别','Avatar categories')} value={category.id}
            onChange={e=>{const next=categories.find(c=>c.id===e.target.value);if(next)setCategory(next)}}>
            {categories.map(c=><option key={c.id} value={c.id}>{tr(...c.label)}</option>)}
          </select>
          <button className="av-shuffle" type="button" onClick={()=>onChange(randomConfig())}>
            <Shuffle size={15} aria-hidden="true"/>{tr('随机搭配','Shuffle')}
          </button>
        </div>
        {category.id==='presets'&&<div className="av-choices av-presets" role="radiogroup" aria-label={activeLabel}>
          {presetIds.map(key=><Choice key={key} name={id+'-preset'} label={tr(presetNames[key][0],presetNames[key][1])} image={avatarSrc(presetConfigs[key])}
            selected={choice!==null&&equalConfig(value,presetConfigs[key])} onChange={()=>onChange({...presetConfigs[key]})}/>)}
        </div>}
        {style&&<div className="av-choices" role="radiogroup" aria-label={activeLabel} key={style}>
          {styleOptions[style].map(option=><Choice key={option} name={id+'-'+style} label={styles[option]?tr(...styles[option]):option}
            image={avatarSrc({...value,[style]:option})} focusPart={style} selected={choice!==null&&value[style]===option}
            onChange={()=>onChange({...value,[style]:option})}/>)}
        </div>}
        {color&&<ColourPicker key={color} name={id+'-'+color} active={choice!==null} value={value[color]} colors={colorPalettes[color]}
          onChange={next=>onChange({...value,[color]:next})}/>}
      </div>
    </div>
  </fieldset>
}
