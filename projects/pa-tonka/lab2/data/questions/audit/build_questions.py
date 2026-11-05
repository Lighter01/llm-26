"""Build the reviewed question set, extracting every quote from the corpus.

Run from the project root with PyYAML. No source files or dependencies are changed.
The YAML contains only the raw v1 fields; source coordinates belong to the audit.
"""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / 'data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8'
TARGET = ROOT / 'data/questions/questions_codex.yaml'
MAP = [json.loads(line) for line in (CORPUS / 'source_map.jsonl').read_text().splitlines()]
BOOKS = {}
for name in ('xphb.md', 'xdmg.md', 'xmm.md'):
    full = (CORPUS / name).read_text(encoding='utf-8')
    assert full.startswith('---\n')
    body = full.split('\n---\n', 1)[1].removeprefix('\n')
    assert body.startswith('# ')
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    BOOKS[name] = (body, lines, offsets)


def alternative(name, start, end, leaf=None):
    body = BOOKS[name][0]
    candidates = [s for s in MAP if s['file'] == name
                  and s['start_char'] <= start and end <= s['end_char']]
    assert candidates, (name, start, end)
    section = max(candidates, key=lambda s: len(s['heading_path']))
    if leaf is not None and section['heading_path'][-1] != leaf:
        return None
    return {'file': name, 'heading_path': section['heading_path'], 'quote': body[start:end]}


def text(name, fragment, leaf=None):
    """Extract all exact occurrences, with their deepest containing paths."""
    body = BOOKS[name][0]
    found = []
    offset = 0
    while (start := body.find(fragment, offset)) != -1:
        item = alternative(name, start, start + len(fragment), leaf)
        if item is not None:
            found.append(item)
        offset = start + 1
    assert found, (name, leaf, fragment)
    return found


def lines(name, first, last=None, leaf=None):
    """Extract continuous complete lines, excluding only the final LF."""
    body, source_lines, offsets = BOOKS[name]
    found = []
    for index, line in enumerate(source_lines):
        if line.removesuffix('\n') != first:
            continue
        final = index
        if last is not None:
            final = next(i for i in range(index, len(source_lines))
                         if source_lines[i].removesuffix('\n') == last)
        end = offsets[final + 1] - (1 if source_lines[final].endswith('\n') else 0)
        item = alternative(name, offsets[index], end, leaf)
        if item is not None:
            found.append(item)
    assert found, (name, leaf, first, last)
    return found


def fact(statement, *alternatives):
    flattened = [a for group in alternatives for a in group]
    seen = set()
    result = []
    for alt in flattened:
        key = (alt['file'], tuple(alt['heading_path']), alt['quote'])
        if key not in seen:
            result.append(alt)
            seen.add(key)
    return {'fact': statement, 'alternatives': result}


PHB = 'xphb.md'
DMG = 'xdmg.md'
MM = 'xmm.md'

medium_water = lines(PHB, '**Water Needs per Day**', '| Medium | 1 gallon |')
large_water = lines(PHB, '**Water Needs per Day**', '| Large | 4 gallons |')
dehydration_gain = text(PHB, "A creature that drinks less than half the required water for a day gains 1 Exhaustion level at the day's end.")
dehydration_removal = text(PHB, "Exhaustion caused by dehydration can't be removed until the creature drinks the full amount of water required for a day.")
rest_removal = (
    text(PHB, '***Removing Exhaustion Levels.*** Finishing a Long Rest removes 1 of your Exhaustion levels. When your Exhaustion level reaches 0, the condition ends.')
    + lines(PHB, '***Benefits of the Rest.*** To start a Long Rest, you must have at least 1 Hit Point. When you finish the rest, you gain the following benefits:',
            '- **Exhaustion Reduced:** If you have the Exhaustion condition, its level decreases by 1.', leaf='Long Rest')
)
incapacitated = (
    text(PHB, '***Incapacitated or Dead.*** Your Concentration ends if you have the Incapacitated condition or you die.')
    + lines(PHB, '### Incapacitated', '***No Concentration.*** Your Concentration is broken.')
)
hoard_table = lines(DMG, '**Random Treasure Hoard**', '| 5–10 | 8d10 × 100 (4,400) GP | 1d3 |')
hoard_expanded = lines(DMG, '#### Challenge 5-10', '| 1–100 | Magic Items: Type: Random By Level; Amount: 1d3 |', leaf='Challenge 5-10')
rarity_table = lines(DMG, '**Magic Item Rarities**', '| 55–91 | 31–81 | 12–34 | — | Uncommon |')
rarity_expanded = lines(DMG, '##### By Level - Levels 5-10', '| 31–81 | Choose 1: From Matching: Rarity: uncommon |')
ankheg_speed = lines(MM, '> **Ankheg**', '> **Speed:** 30 ft., Burrow 10 ft.')
ankheg_tunneler = lines(MM, '> **Tunneler.** The ankheg can burrow through solid rock at half its Burrow Speed and leaves a 10-foot-diameter tunnel in its wake.')
acid_absorption = lines(MM, '> **Acid Absorption.** Whenever the golem is subjected to Acid damage, it takes no damage and instead regains a number of Hit Points equal to the Acid damage dealt.', leaf='Clay Golem')
berserk = lines(MM, '> **Berserk.** Whenever the golem starts its turn Bloodied, roll 1d6. On a 6, the golem goes berserk. On each of its turns while berserk, the golem attacks the nearest creature it can see. If no creature is near enough to move to and attack, the golem attacks an object. Once the golem goes berserk, it continues to be berserk until it is destroyed or it is no longer Bloodied.', leaf='Clay Golem')
drone = lines(MM, "> **Drone.** *Constitution Saving Throw:* DC 12, each creature in a 30-foot Emanation originating from the chasme (demons automatically succeed on this save). *Failure:* The target has the Unconscious condition and repeats the save at the end of each of its turns. The target succeeds automatically after 10 minutes or if it takes damage or a creature within 5 feet of it takes an action to empty a flask of Holy Water on it. *Success:* The target is immune to this chasme's Drone for 24 hours.")
antennae = lines(MM, '> **Antennae.** The rust monster targets one nonmagical metal object—armor or a weapon—worn or carried by a creature within 5 feet of itself. *Dexterity Saving Throw:* DC 11, the creature with the object. *Failure:* The object takes a -1 penalty to the AC it offers (armor) or to its attack rolls (weapon). Armor is destroyed if the penalty reduces its AC to 10, and a weapon is destroyed if its penalty reaches -5. The penalty can be removed by casting the *Mending* spell on the armor or weapon.')
troll_regen = lines(MM, "> **Regeneration.** The troll regains 15 Hit Points at the start of each of its turns. If the troll takes Acid or Fire damage, this trait doesn't function on the troll's next turn. The troll dies only if it starts its turn with 0 Hit Points and doesn't regenerate.")
limb_regen = lines(MM, "> **Regeneration.** The limb regains 5 Hit Points at the start of each of its turns. If the limb takes Acid or Fire damage, this trait doesn't function on the limb's next turn. The limb dies only if it starts its turn with 0 Hit Points and doesn't regenerate.")
vortex = lines(MM, "> **Vortex.** *Constitution Saving Throw:* DC 14, one Large or smaller creature in the stalker's space. *Failure:* 7 (1d8 + 3) Thunder damage, and the target has the Grappled condition (escape DC 13). Until the grapple ends, the target can't cast spells with a Verbal component and takes 7 (2d6) Thunder damage at the start of each of the stalker's turns.")
purple_poison = lines(DMG, 'A creature subjected to Purple Worm Poison makes a DC 21 Constitution saving throw, taking 35 (10d6) Poison damage on a failed save or half as much damage on a successful one.')
plate_price = (
    lines(PHB, '### Plate Armor', '**Price:** 1500 GP')
    + lines(PHB, '| Plate Armor | 18 | Str 15 | Disadvantage | 65 lb. | 1,500 GP |')
    + lines(PHB, 'To make an item, you need raw materials worth half its purchase cost (round down). For example, you need 750 GP of raw materials to make Plate Armor, which sells for 1,500 GP. The DM determines whether appropriate raw materials are available.')
    + lines(DMG, "If a magic item incorporates an item that has a purchase cost in the Player's Handbook (such as a weapon or a suit of armor), add that item's cost to the magic item's value. For example, +1 Armor (Plate Armor) has a value of 5,500 GP, which is the sum of a Rare magic item's value (4,000 GP) and the cost of Plate Armor (1,500 GP).")
    + lines(DMG, "If a magic item incorporates an item that has a purchase cost (such as a weapon or a suit of armor), you must also pay that entire cost or craft that item using the rules in the Player's Handbook. For example, to make +1 Armor (Plate Armor), you must pay 3,500 GP or pay 2,000 GP and craft the armor.")
)
rare_armor = (
    lines(DMG, '#### +1 Armor', '- Plate Armor (+1 Plate Armor)')
    + lines(DMG, "If a magic item incorporates an item that has a purchase cost in the Player's Handbook (such as a weapon or a suit of armor), add that item's cost to the magic item's value. For example, +1 Armor (Plate Armor) has a value of 5,500 GP, which is the sum of a Rare magic item's value (4,000 GP) and the cost of Plate Armor (1,500 GP).")
)
questions = []


def question(qid, wording, answer, *facts):
    questions.append({'id': qid, 'question': wording, 'reference_answer': answer,
                      'answerable': not qid.startswith('insufficient_'), 'evidence': list(facts)})


question('phb_01',
    "How does the Sorcerer's Subtle Spell Metamagic change a spell's component requirements, what is its normal Sorcery Point cost, and which Material components must still be provided?",
    'Subtle Spell normally costs 1 Sorcery Point and lets the Sorcerer cast without Verbal, Somatic, or Material components. Material components are still required if the spell consumes them or specifies a cost for them.',
    fact('The normal cost of using Subtle Spell is 1 Sorcery Point.',
         lines(PHB, '#### Subtle Spell', '*Cost: 1 Sorcery Point*'),
         lines(PHB, 'When you cast a spell, you can spend 1 Sorcery Point to cast it without any Verbal, Somatic, or Material components, except Material components that are consumed by the spell or that have a cost specified in the spell.')),
    fact('Subtle Spell removes Verbal, Somatic, and Material components except consumed Material components or those with a specified cost.',
         lines(PHB, 'When you cast a spell, you can spend 1 Sorcery Point to cast it without any Verbal, Somatic, or Material components, except Material components that are consumed by the spell or that have a cost specified in the spell.')))

question('phb_02',
    'A Medium adventurer starts with no Exhaustion and drinks only one-quarter gallon of water during a day. How many Exhaustion levels do they gain at the end of that day, and how many remain after they subsequently drink their full daily water requirement and finish a Long Rest? Assume no additional Exhaustion is gained and no special features or magic change these rules.',
    'They gain 1 Exhaustion level: a Medium creature needs 1 gallon per day, and one-quarter gallon is less than half that amount. Drinking the full daily requirement allows the dehydration level to be removed; it does not remove the level by itself. The subsequent Long Rest removes 1 level, leaving 0.',
    fact('A Medium creature requires 1 gallon of water per day.', medium_water),
    fact("Drinking less than half the daily water requirement causes 1 Exhaustion level at the day's end.", dehydration_gain),
    fact('A Long Rest normally reduces Exhaustion by 1 level.', rest_removal),
    fact('Exhaustion caused by dehydration cannot be removed until the creature drinks its full daily water requirement.', dehydration_removal))

question('phb_03',
    'For a creature affected by Confusion, what does a result of 1 on the behavior d10 require it to do with its action and movement, and how is its movement direction chosen?',
    'For that turn, the creature takes no action and uses all its movement to move. Roll 1d4 to choose the direction: 1 is north, 2 east, 3 south, and 4 west.',
    fact('A Confusion behavior roll of 1 means taking no action and using all movement to move.',
         lines(PHB, '| 1d10 | Behavior for the Turn |', "| 1 | The target doesn't take an action, and it uses all its movement to move. Roll 1d4 for the direction: **1**, north; **2**, east; **3**, south; or **4**, west. |", leaf='Confusion')),
    fact('For a Confusion behavior roll of 1, a separate 1d4 determines direction: 1 north, 2 east, 3 south, and 4 west.',
         lines(PHB, '| 1d10 | Behavior for the Turn |', "| 1 | The target doesn't take an action, and it uses all its movement to move. Roll 1d4 for the direction: **1**, north; **2**, east; **3**, south; or **4**, west. |", leaf='Confusion')))

question('phb_04',
    'What bonus can consulting an accurate nonfiction Book grant to an Intelligence check, and which skills and subject matter qualify?',
    "It grants a +5 bonus to Intelligence checks using Arcana, History, Nature, or Religion, provided the check concerns the topic of the accurate nonfiction Book being consulted.",
    fact('Consulting an accurate nonfiction Book grants +5 to Intelligence (Arcana, History, Nature, or Religion) checks about its topic.',
         lines(PHB, '### Book (25 GP)', "A Book contains fiction or nonfiction. If you consult an accurate nonfiction Book about its topic, you gain a +5 bonus to Intelligence (Arcana, History, Nature, or Religion) checks you make about that topic.")))

question('phb_05',
    'A spellcaster maintaining Concentration takes 23 damage from one source. What saving throw and DC are required to keep Concentration? If the caster subsequently becomes Incapacitated, can another successful save preserve Concentration? Assume no special feature changes the normal rules.',
    'The damage requires a DC 11 Constitution saving throw: half of 23 rounded down is 11, which is higher than 10. Becoming Incapacitated ends Concentration automatically; another saving throw cannot preserve it.',
    fact('Damage requires a Constitution save to maintain Concentration, with DC equal to the higher of 10 and half the damage rounded down, capped at 30.',
         lines(PHB, '***Damage.*** If you take damage, you must succeed on a Constitution saving throw to maintain Concentration. The DC equals 10 or half the damage taken (round down), whichever number is higher, up to a maximum DC of 30.')),
    fact('The Incapacitated condition breaks Concentration automatically.', incapacitated))

question('dmg_01',
    'How often does a Bastion turn occur by default, and what happens to orders when its owner is away on that turn? Can communicating with the hirelings through Sending change that outcome?',
    'A Bastion turn occurs every 7 in-game days by default. If the owner is absent, the Bastion acts as though it received the Maintain order for the whole Bastion. This default does not apply if the owner can communicate with the hirelings through Sending or similar magic.',
    fact('A Bastion turn occurs every 7 days of in-game time by default.',
         lines(DMG, 'By default, a Bastion turn occurs every 7 days of in-game time. Here are common examples of players taking one or more Bastion turns:')),
    fact('An absent owner causes the whole Bastion to default to Maintain unless the owner can communicate with its hirelings using Sending or similar magic.',
         lines(DMG, "The Maintain order is unusual; it is issued to the whole Bastion rather than to one or more special facilities. If a character isn't in their Bastion on a given Bastion turn, the Bastion acts as though it were issued the Maintain order on that turn unless the owner can communicate with the Bastion hirelings using the *Sending* spell or similar magic.")))

question('dmg_02',
    'A 10-foot-square area of thin ice is carrying 400 pounds. Can any possible tolerance roll let it hold that weight? If a creature with Constitution 14 falls through and can breathe normally, how long before the frigid water starts requiring saves, and what save is required each minute afterward? The creature has no Cold Resistance, Cold Immunity, or natural adaptation to icy water.',
    'The ice breaks: its tolerance is 3d10 × 10 pounds, at most 300 pounds. Creatures on the broken ice fall into frigid water. With Constitution 14, the frigid-water rule allows 14 minutes before saves begin; each additional minute requires a DC 10 Constitution saving throw, with 1 Exhaustion level on a failure.',
    fact('Thin ice has a tolerance of 3d10 × 10 pounds per 10-foot square and breaks when the weight exceeds that tolerance.',
         text(DMG, 'Thin ice has a weight tolerance of 3d10 × 10 pounds per 10-foot-square area. Whenever the total weight on an area of thin ice exceeds its tolerance, the ice in that area breaks.')),
    fact('Creatures on broken thin ice fall through into frigid water.',
         text(DMG, 'All creatures on broken ice fall through. Below the ice is frigid water.')),
    fact('A creature can remain immersed in frigid water without ill effects for minutes equal to its Constitution score.',
         text(DMG, 'A creature can be immersed in frigid water for a number of minutes equal to its Constitution score before suffering any ill effects.')),
    fact('Each additional minute in frigid water requires a DC 10 Constitution save or causes 1 Exhaustion level; Cold Resistance, Cold Immunity, or natural adaptation grants automatic success.',
         text(DMG, 'Each additional minute spent in frigid water requires the creature to succeed on a DC 10 Constitution saving throw or gain 1 Exhaustion level. Creatures with Resistance or Immunity to Cold damage automatically succeed on the save, as do creatures that are naturally adapted to living in ice-cold water.')))

question('dmg_03',
    'When a conflict arises because a bearer acts against a sentient magic item\'s alignment or purpose, what saving throw does the bearer make and how is its DC calculated?',
    "The bearer makes a Charisma saving throw with a DC of 12 plus the sentient item's Charisma modifier.",
    fact("A conflict with a sentient item calls for a Charisma saving throw with DC 12 plus the item's Charisma modifier.",
         text(DMG, "When the bearer of a sentient item acts in a manner opposed to the item's alignment or purpose, conflict can arise. When such a conflict occurs, the item's bearer makes a Charisma saving throw (DC 12 plus the item's Charisma modifier).")))

question('dmg_04',
    'An adventurer finds an unfamiliar computer from another world or time period. What check and DC can identify it, and does success necessarily mean the adventurer can activate or operate it?',
    'Identifying the computer requires a DC 20 Intelligence (Investigation) check because it is complex alien technology. Success does not necessarily establish the ability to use it: the DM may require a separate Intelligence (Investigation) check to activate or operate it.',
    fact('Identifying complex alien technology such as a computer requires a DC 20 Intelligence (Investigation) check.',
         text(DMG, "When adventurers find a piece of technology that isn't from their world or time period, they can deduce what it is with a successful Intelligence (Investigation) check, with the DC depending on the complexity of the item: DC 10 for a relatively simple item like a calculator or a lighter, or DC 20 for a complex item such as a computer, a chainsaw, or a hovercraft.")),
    fact('The DM may require a separate Intelligence (Investigation) check to determine whether a character can activate or operate alien technology.',
         text(DMG, 'You may require a separate Intelligence (Investigation) check to determine whether a character can activate or operate the technology; a character who has observed the item in use or has operated a similar item either has Advantage on the check or succeeds on the check automatically (your choice).')))

question('dmg_05',
    'For a single, unmodified roll on Random Treasure Hoard for CR 5–10, what are the monetary treasure formula, its listed average, and the number of magic items? If a magic item\'s rarity is rolled using the levels 5–10 column of Magic Item Rarities, what is the percentage chance of Uncommon?',
    'The hoard contains 8d10 × 100 GP, with a listed average of 4,400 GP, and 1d3 magic items. For characters of levels 5–10, an Uncommon item occurs on 31–81 inclusive on d100, a 51% chance.',
    fact('A CR 5–10 Random Treasure Hoard has monetary treasure of 8d10 × 100 GP.', hoard_table, hoard_expanded),
    fact('The listed average monetary treasure for a CR 5–10 Random Treasure Hoard is 4,400 GP.', hoard_table),
    fact('A CR 5–10 Random Treasure Hoard contains 1d3 magic items.', hoard_table, hoard_expanded),
    fact('At character levels 5–10, the random rarity roll gives Uncommon on d100 results 31–81 inclusive.', rarity_table, rarity_expanded))

question('mm_01',
    'What is an ankheg\'s Burrow Speed, what speed can it use to burrow through solid rock, and what diameter of tunnel does that tunneling leave?',
    'Its Burrow Speed is 10 feet. Tunneler lets it burrow through solid rock at half that speed, or 5 feet, leaving a tunnel 10 feet in diameter.',
    fact('An ankheg has a Burrow Speed of 10 feet.', ankheg_speed),
    fact('Tunneler lets an ankheg burrow through solid rock at half its Burrow Speed.', ankheg_tunneler),
    fact('An ankheg leaves a 10-foot-diameter tunnel when using Tunneler.', ankheg_tunneler))

question('mm_02',
    'What happens when a clay golem is subjected to Acid damage, what condition and die roll trigger Berserk at the start of its turn, and when does Berserk end?',
    'Acid damage deals no damage to the golem; it instead restores HP equal to the Acid damage dealt. Whenever the golem starts its turn Bloodied, roll 1d6: on a 6 it goes berserk. It remains berserk until destroyed or no longer Bloodied.',
    fact('Acid Absorption replaces Acid damage to a clay golem with healing equal to the Acid damage dealt.', acid_absorption),
    fact('A clay golem that starts its turn Bloodied goes berserk on a result of 6 on 1d6.', berserk),
    fact('A berserk clay golem remains berserk until destroyed or no longer Bloodied.', berserk))

question('mm_03',
    'How can an ally use Holy Water to end the Unconscious effect of a chasme\'s Drone, and how long is the affected creature protected against that chasme\'s Drone after succeeding on its save?',
    "A creature within 5 feet of the affected target can take an action to empty a flask of Holy Water on it, making the target automatically succeed on its save. A successful save grants immunity to that particular chasme's Drone for 24 hours.",
    fact('A creature within 5 feet can take an action to empty a flask of Holy Water on a Drone target, causing that target to succeed automatically on its save.', drone),
    fact("Success on the save grants immunity to that chasme's Drone for 24 hours.", drone))

question('mm_04',
    'A rust monster uses Antennae on a nonmagical metal weapon carried by a creature within 5 feet. What save is required, what weapon penalty follows a failed save, at what penalty is the weapon destroyed, and what spell removes the penalty?',
    'The carrier makes a DC 11 Dexterity saving throw. On failure, the weapon takes a -1 penalty to its attack rolls. The weapon is destroyed when the penalty reaches -5. Casting Mending on the weapon removes the penalty.',
    fact('Antennae calls for a DC 11 Dexterity saving throw from the creature carrying the targeted nonmagical metal weapon within 5 feet.', antennae),
    fact('On a failed Antennae save, a weapon takes a -1 penalty to its attack rolls.', antennae),
    fact('A weapon is destroyed if its Antennae penalty reaches -5.', antennae),
    fact('Casting Mending on the weapon removes its Antennae penalty.', antennae))

question('mm_05',
    'Compare a Troll and a Troll Limb: how many Hit Points does each regain at the start of its turn, and what happens to that creature\'s next-turn Regeneration if it takes Acid or Fire damage?',
    "A Troll regains 15 HP at the start of its turn, while a Troll Limb regains 5 HP. If either creature takes Acid or Fire damage, its own Regeneration does not function on its next turn.",
    fact('A Troll normally regains 15 Hit Points at the start of each of its turns.', troll_regen),
    fact('Acid or Fire damage prevents the Troll\'s Regeneration from functioning on its next turn.', troll_regen),
    fact('A Troll Limb normally regains 5 Hit Points at the start of each of its turns.', limb_regen),
    fact('Acid or Fire damage prevents the Troll Limb\'s Regeneration from functioning on its next turn.', limb_regen))

question('multi_01',
    'A Medium creature in an invisible stalker\'s space fails its save against Vortex while entirely inside the sphere of an active Silence spell. What ability and DC does Vortex use, and how much initial damage does this creature take? Assume no effect overrides its immunities.',
    'Vortex uses a DC 14 Constitution saving throw. Its failed-save initial damage is normally 7 (1d8 + 3) Thunder damage, but the creature takes 0: being entirely within Silence gives it Immunity to Thunder damage.',
    fact('Vortex calls for a DC 14 Constitution saving throw.', vortex),
    fact('The initial damage on a failed Vortex save is 7 (1d8 + 3) Thunder damage.', vortex),
    fact('A creature entirely within the sphere of Silence has Immunity to Thunder damage.',
         lines(PHB, 'For the duration, no sound can be created within or pass through a 20-foot-radius Sphere centered on a point you choose within range. Any creature or object entirely inside the Sphere has Immunity to Thunder damage, and creatures have the Deafened condition while entirely inside it. Casting a spell that includes a Verbal component is impossible there.')))

question('multi_02',
    'Assume Purple Worm Poison has been successfully delivered to a clay golem. What saving throw and normal failed-save damage does the poison specify, and how much of that Poison damage can the golem actually take on a failure?',
    'Purple Worm Poison specifies a DC 21 Constitution saving throw and normally deals 35 (10d6) Poison damage on a failure. The clay golem takes 0 Poison damage even on a failed save because its stat block gives it Immunity to Poison damage.',
    fact('Purple Worm Poison calls for a DC 21 Constitution saving throw.', purple_poison),
    fact('Purple Worm Poison normally deals 35 (10d6) Poison damage on a failed save.', purple_poison),
    fact('A clay golem has Immunity to Poison damage.',
         lines(MM, '> **Immunities:** Acid; Poison; Psychic', leaf='Clay Golem')))

question('multi_03',
    'Using the standard encounter XP-budget procedure, does an encounter consisting only of two Mages (CR 6 each) fit the Moderate budget for four level 6 characters? Give the party budget, the encounter\'s XP total, and how far it is under or over budget.',
    'No. The Moderate budget is 1,000 XP per level 6 character, so four characters have 4,000 XP. Each CR 6 Mage is worth 2,300 XP; two total 4,600 XP, exceeding the Moderate budget by 600 XP.',
    fact('The Moderate encounter budget for a level 6 character is 1,000 XP.',
         lines(DMG, '**XP Budget per Character**', '| 6 | 600 | 1,000 | 1,400 |')),
    fact('The encounter XP budget is the per-character table entry multiplied by the number of characters.',
         lines(DMG, "***Step 2: Determine Your XP Budget.*** Using the XP Budget per Character table, cross-reference the party's level with the desired encounter difficulty. Multiply the number in the table by the number of characters in the party to get your XP budget for the encounter.")),
    fact('Each of the stated CR 6 Mages is worth 2,300 XP.',
         lines(MM, '> **CR:** 6 (XP 2,300; PB +3)', leaf='Mage'),
         lines(MM, '**Experience Points by Challenge Rating**', '| 6 | 2,300 |')))

question('multi_04',
    'One qualified crafter first makes Plate Armor from raw materials and then crafts it into +1 Plate Armor. How many 8-hour workdays are needed in total under the standard rules? Assume all required proficiencies, tools, and materials are available, there are no assistants, and the mundane armor is completed before work on the magic-item stage begins.',
    'The total is 200 workdays of 8 hours each. Plate Armor has a purchase price of 1,500 GP, so the nonmagical stage takes 1,500 / 10 = 150 workdays. +1 Armor is Rare, so its magic-item stage takes another 50 workdays.',
    fact('Plate Armor has a purchase price of 1,500 GP.', plate_price),
    fact('Nonmagical crafting takes purchase price in GP divided by 10, rounded up, in 8-hour workdays.',
         text(PHB, 'To determine how many days (working 8 hours a day) it takes to make an item, divide its purchase cost in GP by 10 (round a fraction up to a day).')),
    fact('+1 Plate Armor is a Rare magic item.', rare_armor),
    fact('Crafting a Rare nonconsumable magic item takes 50 days.',
         lines(DMG, '**Magic Item Crafting Time and Cost**', '\\*The time and cost are halved for a consumable item other than a Spell Scroll, whose crafting time and cost are given in the Player\'s Handbook.')),
    fact('Each day of magic-item crafting requires 8 hours of work.',
         lines(DMG, "***Work per Day.*** For each day of crafting, you must work for 8 hours. If an item requires multiple days, those days needn't be consecutive.")))

question('multi_05',
    'Four ordinary Medium adventurers and one captive ankheg must each receive their full daily water requirement. What is the ankheg\'s size, how much water do all five creatures need in total, and can a single Alchemy Jug supply it between consecutive dawns if its fresh-water allowance is unused and it produces only fresh water?',
    'The ankheg is Large. Each Medium adventurer needs 1 gallon per day and the Large ankheg needs 4 gallons, for 4 × 1 + 4 = 8 gallons total. Yes: an Alchemy Jug can produce up to 8 gallons of fresh water and cannot produce more after reaching that maximum until the next dawn.',
    fact('An ankheg is Large.', lines(MM, '> **Ankheg**', '> *Large Monstrosity, Unaligned*')),
    fact('A Medium creature requires 1 gallon of water per day.', medium_water),
    fact('A Large creature requires 4 gallons of water per day.', large_water),
    fact('An Alchemy Jug can produce at most 8 gallons of fresh water before reaching its maximum.',
         lines(DMG, '**Alchemy Jug Liquids**', '| Water, fresh | 8 gallons |')),
    fact('After producing a liquid, an Alchemy Jug cannot produce a different liquid or more of a liquid that has reached its maximum until the next dawn.',
         lines(DMG, "Once the jug starts producing a liquid, it can't produce a different one, or more of one that has reached its maximum, until the next dawn.")))

question('insufficient_01',
    'What are Demogorgon\'s exact Armor Class, Hit Points, and Legendary Actions in the supplied rulebooks?',
    'The supplied books do not provide enough information to give these statistics. They mention Demogorgon in lore, but contain no Demogorgon stat block establishing his Armor Class, Hit Points, or Legendary Actions. Those details must not be invented or substituted from a different creature.')

question('insufficient_02',
    'My Fighter attacks a clay golem with a Longsword. What is the exact probability that the attack hits, including the effects of any Advantage or Disadvantage?',
    'The supplied information is insufficient to calculate an exact probability. The books do not specify this Fighter\'s attack bonus, whether Advantage or Disadvantage applies, or any other relevant modifiers and effects in this encounter. The target\'s standard statistics alone cannot determine the probability.')

question('insufficient_03',
    'My character has just issued the Maintain order to their Bastion. Which Bastion event actually occurs this turn, and what are the results of any follow-up random rolls?',
    'The supplied books describe possible Bastion events and their resolution, but do not provide the actual event roll for this turn or any follow-up rolls. Without those results, the event and its random details cannot be determined; no particular event or roll result should be invented.')


class Quoted(str):
    pass


class Literal(str):
    pass


class Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


Dumper.add_representer(Quoted, lambda dumper, value: dumper.represent_scalar('tag:yaml.org,2002:str', value, style='"'))
Dumper.add_representer(Literal, lambda dumper, value: dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|'))


def styled(value, field=None):
    if isinstance(value, dict):
        return {key: styled(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [styled(item, field) for item in value]
    if isinstance(value, str):
        return Literal(value) if field in ('quote', 'reference_answer') else Quoted(value)
    return value


if __name__ == '__main__':
    document = {'schema_version': 1, 'questions': questions}
    serialized = yaml.dump(styled(document), Dumper=Dumper, allow_unicode=True,
                           sort_keys=False, default_flow_style=False, width=1000)
    assert yaml.safe_load(serialized) == document
    TARGET.write_text(serialized, encoding='utf-8')
    print(f'Wrote {len(questions)} questions to {TARGET.relative_to(ROOT)}')
    print(f'{sum(len(q["evidence"]) for q in questions)} facts; '
          f'{sum(len(f["alternatives"]) for q in questions for f in q["evidence"])} alternatives')
