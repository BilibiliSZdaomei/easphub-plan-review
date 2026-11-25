"""Validated account avatars using the pinned Draftbit Personas generator."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

SOURCE = 'draftbit-personas'
REVISION = '7b5234c44b3cef49d483b1462398bc9ea07bfa12'

# Upstream permits palette colours and custom six-digit hex, without a leading '#'.
Color = Annotated[str, StringConstraints(strict=True, min_length=6, max_length=6,
                                         pattern=r'^[0-9a-fA-F]{6}$', to_upper=True)]


class PersonasStyles(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Keys and names match upstream src/data/config.json and its shareable style object.
    skin: Literal['Skin'] = 'Skin'
    head: Literal['Head'] = 'Head'
    hair: Literal['Bald', 'Hat', 'Balding', 'Bigcurls', 'Bobbangs', 'Bobcut', 'Buncurls', 'Buzzcut',
                  'Curlybun', 'Hightopcurly', 'Long', 'Pigtails', 'Shortcombover', 'Beanie', 'Bunundercut',
                  'Extralong', 'Fade', 'Mohawk', 'Shortcomboverchops', 'Sidebuzz', 'Straightbun']
    facialHair: Literal['BeardMustache', 'Mustache', 'None', 'Goatee', 'Shadow', 'Soulpatch', 'Walrus']
    body: Literal['Oval', 'Round', 'Square', 'Checkered', 'Hoodie', 'Stripes']
    eyes: Literal['Glasses', 'Happy', 'Open', 'Sleepy', 'Sunglasses', 'Wink', 'Closed', 'Hearts', 'Dizzy', 'Sideeye']
    mouth: Literal['Bigsmile', 'Frown', 'Lips', 'Pacifier', 'Smile', 'Smirk', 'Surprise', 'Grin', 'Tongue', 'Whistle', 'Laugh']
    nose: Literal['Mediumround', 'Smallround', 'Wrinkles', 'Pointed', 'Button']
    accessories: Literal['None', 'Earring', 'Earrings']
    skinColor: Color
    hairColor: Color
    facialHairColor: Color
    bodyColor: Color
    accessoriesColor: Color
    bgColor: Color


class PresetChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    avatar_preset: Literal['blank', 'plan', 'parts', 'order']


class CustomChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    avatar_config: PersonasStyles
