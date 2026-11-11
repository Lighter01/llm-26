"""Balanced 5etools inline grammar. No upstream imports or network lookups."""

import re

from ..common.model import ExportError, require

ABILITIES = dict(
    zip(
        ('str', 'dex', 'con', 'int', 'wis', 'cha'),
        ('Strength', 'Dexterity', 'Constitution', 'Intelligence', 'Wisdom', 'Charisma'),
    )
)
ENTITY_TAGS = frozenset(
    (
        'spell',
        'creature',
        'item',
        'variantrule',
        'skill',
        'sense',
        'action',
        'condition',
        'status',
        'race',
        'background',
        'class',
        'feat',
        'optfeature',
        'itemProperty',
        'itemMastery',
        'language',
        'hazard',
        'disease',
        'trap',
        'object',
        'reward',
        'facility',
        'table',
    )
)


def split_pipes(value: str) -> list[str]:
    result, start, depth = [], 0, 0
    for i, char in enumerate(value):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif char == '|' and depth == 0:
            result.append(value[start:i])
            start = i + 1
    result.append(value[start:])
    return result


def escape(value: str) -> str:
    value = value.replace('\\', '\\\\').replace('<', '&lt;').replace('>', '&gt;')
    for char in ('*', '_', '[', ']'):
        value = value.replace(char, '\\' + char)
    return value


class InlineRenderer:
    def __init__(self, context=None):
        self.context = context or (lambda: {})

    def __call__(self, value, *, plain=False, _italic=False) -> str:
        require(
            isinstance(value, (str, int, float)) and not isinstance(value, bool),
            'INLINE_VALUE',
            'Expected text or a number',
            **self.context(),
        )
        text = str(value)
        require(
            '{#' not in text,
            'ACTIVE_REFERENCE',
            'Unresolved structural reference',
            **self.context(),
        )
        result, i = [], 0
        literal = (lambda x: x) if plain else escape
        while i < len(text):
            start = text.find('{@', i)
            if start < 0:
                result.append(literal(text[i:]))
                break
            result.append(literal(text[i:start]))
            end, depth = start + 2, 1
            while end < len(text) and depth:
                depth += (text[end] == '{') - (text[end] == '}')
                end += 1
            require(depth == 0, 'UNCLOSED_TAG', text[start : start + 120], **self.context())
            tag, _, arg = text[start + 2 : end - 1].partition(' ')
            result.append(self.tag(tag, arg, plain=plain, _italic=_italic))
            i = end
        return ''.join(result)

    def tag(self, tag: str, arg: str, *, plain: bool, _italic=False) -> str:
        args = split_pipes(arg)

        def render(value, *, italic=_italic):
            return self(value, plain=plain, _italic=italic)

        def label(i=0, *, italic=_italic):
            return render(args[i], italic=italic)

        def styled(text, marker):
            return text if plain or marker == '*' and _italic else marker + text + marker

        if tag in ('b', 'bold', 'i', 'italic', 's', 'strike', 'note'):
            marker = '**' if tag in ('b', 'bold') else '~~' if tag in ('s', 'strike') else '*'
            return styled(render(arg, italic=_italic or marker == '*'), marker)
        if tag in ENTITY_TAGS:
            index = 2 if len(args) > 2 and args[2] else 0
            if tag == 'spell':
                # Nested explicit italics share this emphasis instead of becoming bold.
                return styled(label(index, italic=True), '*')
            return label(index)
        if tag in ('deity', 'card'):
            return label(3 if len(args) > 3 and args[3] else 0)
        if tag in ('book', 'adventure', 'area', 'filter', '5etools', '5etoolsImg', 'tip'):
            # Image/download and navigation tags retain their visible label only.
            return label()
        if tag == 'link':
            require(len(args) >= 2, 'INVALID_LINK', arg, **self.context())
            url = args[1]
            require(
                bool(re.match(r'^https?://[^\s<>]+$', url)), 'INVALID_LINK', url, **self.context()
            )
            if plain:
                return label()
            return f'[{label()}]({url.replace("(", "%28").replace(")", "%29")})'
        if tag in ('scaledice', 'scaledamage'):
            return render(self.scaled_display(args))
        if tag in ('dice', 'damage', 'autodice'):
            value = args[1] if len(args) > 1 and args[1] else args[0]
            value = value.replace('summonSpellLevel', "the spell's level").replace(';', '/')
            return render(value)
        if tag in ('hit', 'd20', 'initiative'):
            if len(args) > 1 and args[1]:
                return label(1)
            try:
                return f'{int(args[0]):+d}'
            except ValueError:
                return label()
        if tag in ('dc', 'dcYourSpellSave', 'hitYourSpellAttack'):
            if tag == 'dc':
                return 'DC ' + label(1 if len(args) > 1 and args[1] else 0)
            return (
                label()
                if arg
                else (
                    'your spell save DC'
                    if tag == 'dcYourSpellSave'
                    else 'your spell attack modifier'
                )
            )
        if tag == 'recharge':
            try:
                lower = int(args[0] or 6)
            except ValueError as error:
                raise ExportError('INVALID_RECHARGE', arg, **self.context()) from error
            return f'(Recharge {lower}' + ('–6)' if lower < 6 else ')')
        if tag == 'chance':
            return label(1) if len(args) > 1 and args[1] else label() + ' percent'
        if tag in ('atk', 'atkr'):
            kinds = {
                'm': 'Melee',
                'r': 'Ranged',
                'mw': 'Melee Weapon',
                'rw': 'Ranged Weapon',
                'ms': 'Melee Spell',
                'rs': 'Ranged Spell',
                'g': 'Magical',
                'a': 'Area',
            }
            codes = arg.split(',')
            require(all(code in kinds for code in codes), 'UNKNOWN_ATTACK', arg, **self.context())
            text = ' or '.join(kinds[code] for code in codes) + (
                ' Attack Roll:' if tag == 'atkr' else ' Attack:'
            )
            return styled(text, '*')
        if tag == 'actSave':
            require(arg in ABILITIES, 'UNKNOWN_ABILITY', arg, **self.context())
            return styled(ABILITIES[arg] + ' Saving Throw:', '*')
        if tag in (
            'h',
            'm',
            'hom',
            'actSaveFail',
            'actSaveSuccess',
            'actSaveSuccessOrFail',
            'actSaveFailBy',
            'actTrigger',
            'actResponse',
        ):
            text = {
                'h': 'Hit:',
                'm': 'Miss:',
                'hom': 'Hit or Miss:',
                'actSaveFail': 'Failure:',
                'actSaveSuccess': 'Success:',
                'actSaveSuccessOrFail': 'Failure or Success:',
                'actSaveFailBy': f'Failure by {arg} or More:',
                'actTrigger': 'Trigger:',
                'actResponse': 'Response—' if 'd' in arg else 'Response:',
            }[tag]
            if tag == 'actSaveFail' and arg:
                ordinals = {'1': 'First', '2': 'Second', '3': 'Third', '4': 'Fourth', '5': 'Fifth'}
                text = ordinals.get(arg, arg) + ' Failure:'
            return styled(text, '*') + (' ' if tag in ('h', 'm', 'hom') else '')
        raise ExportError(
            'UNKNOWN_TAG', f'Unsupported tag {tag!r}', tag=tag, argument=arg[:120], **self.context()
        )

    def scaled_display(self, args):
        """Validate native base/progression/increment/mode/display, then select display."""
        require(
            3 <= len(args) <= 5 and all(value.strip() for value in args[:3]),
            'INVALID_SCALED_TAG',
            'Expected base roll, level progression, increment, optional mode and display text',
            **self.context(),
        )
        require(
            len(args) < 4 or args[3] in ('', 'psi'),
            'INVALID_SCALED_TAG',
            'Unsupported scaling mode',
            **self.context(),
        )
        levels = set()
        for part in re.sub(r'\s', '', args[1]).split(','):
            require(
                re.fullmatch(r'[0-9]+(?:-[0-9]+)?', part),
                'INVALID_SCALED_TAG',
                'Invalid level progression',
                **self.context(),
            )
            low, _, high = part.partition('-')
            try:
                low, high = int(low), int(high or low)
            except ValueError as error:
                raise ExportError(
                    'INVALID_SCALED_TAG', 'Invalid level', **self.context()
                ) from error
            require(
                1 <= low <= high <= 9,
                'INVALID_SCALED_TAG',
                'Scaling levels must be ordered ranges within 1–9',
                **self.context(),
            )
            levels.update(range(low, high + 1))
        require(
            len(levels) >= 2,
            'INVALID_SCALED_TAG',
            'Scaling requires at least two distinct levels',
            **self.context(),
        )
        return args[4] if len(args) == 5 and args[4] else args[2]
