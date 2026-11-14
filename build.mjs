import {buildSync} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
buildSync({entryPoints:['xtext-entry.js'],bundle:true,platform:'browser',format:'iife',minify:true,outfile:'vendor/xtext.js',legalComments:'eof'});
const licenses=[];
function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else if(e.isFile()&&/^(license|notice)/i.test(e.name))licenses.push(p+'\n'+fs.readFileSync(p,'utf8'));}}
walk('node_modules');fs.writeFileSync('vendor/THIRD_PARTY_LICENSES.txt',licenses.join('\n\n'));
