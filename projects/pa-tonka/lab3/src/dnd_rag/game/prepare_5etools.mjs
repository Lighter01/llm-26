import fs from 'node:fs';
import path from 'node:path';
import {openUpstreamRuntime} from '../ingestion/book_assembly/runtime/upstream_runtime.mjs';
const [source, output] = process.argv.slice(2);
if (!source || !output) throw new Error('Expected source root and output JSON path');
const runtime = await openUpstreamRuntime(path.resolve(source));
try {
  const monsters = (await DataUtil.loadJSON('data/bestiary/bestiary-xmm.json')).monster;
  const legendary_groups = (await DataUtil.loadJSON('data/bestiary/legendarygroups.json')).legendaryGroup;
  const {item: allItems} = await Renderer.item.pGetSiteUnresolvedRefItems();
  const allowed = new Set(['XPHB','XDMG','XMM']);
  const fields = ['name','source','page','rarity','type','baseItem','genericVariant','_variantName','_baseSource','_baseName','_category','entries','additionalEntries','_fullEntries'];
  const items = allItems.filter(i => allowed.has(i.source) && (!i._baseSource || allowed.has(i._baseSource)))
    .map(i => Object.fromEntries(fields.filter(k => i[k] !== undefined).map(k => [k,i[k]])));
  const item_groups = (await DataUtil.loadJSON('data/items.json')).itemGroup.filter(i => allowed.has(i.source));
  const loot = await DataUtil.loadJSON('data/loot.json');
  const tables = (await DataUtil.loadJSON('data/generated/gendata-tables.json')).table;
  const budgets = tables.filter(t => t.source === 'XDMG' && t.caption === 'XP Budget per Character');
  if (budgets.length !== 1) throw new Error('Expected one XDMG XP budget table');
  fs.writeFileSync(output, JSON.stringify({monsters,legendary_groups,items,item_groups,loot,budgets:budgets[0],xp_by_cr:Parser.XP_CHART_ALT,inputs:runtime.loadedFiles}));
} finally {runtime.close();}
