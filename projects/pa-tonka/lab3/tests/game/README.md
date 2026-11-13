# Проверки игровой логики

`test_catalog.py` — синтетические разрешённые источники, string/object/choose monster types, fractional/object CR, legendary link, base→specific item variant, item group→generic variant, фильтрация 2014, отсутствующие ссылки, corrupt manifest и воспроизводимость. Реальная компиляция pinned snapshot проверяется административной командой отдельно.

`test_encounters.py` — XP по правилам 2024 года без множителей, включённые L/M/H границы, high/above_high, party validation, exact count/required/filter constraints и distinct search_exhausted. `test_loot.py` — границы всех CR bands, homogeneous count, минимальные/максимальные броски hoard и реальные item/rarity/source, обязательные параметры и невалидный CR. `fixtures.py` — независимые маленькие сущности и управляемый RNG.

Any-habitat регрессии проверяют совместимость Mage с конкретной средой и сохранение остальных фильтров/обязательного состава; evaluator проверяет это независимо от runtime matcher.
