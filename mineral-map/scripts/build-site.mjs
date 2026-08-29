/**
 * Build the frontend and assemble a clean, copy-ready deployable folder.
 *
 * Usage:
 *   npm run build:site            # root-relative build (own subdomain/domain root)
 *   DEPLOY_BASE_PATH=/minerals/ npm run build:site   # subpath deployment
 *   npm run build:site -- --open  # open the output folder afterwards
 *
 * Output: ../mineral-map-site/ (repo root, gitignored)
 */
import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const appRoot = resolve(import.meta.dirname, '..')
const repoRoot = resolve(appRoot, '..')
const distDir = resolve(appRoot, 'dist')
const siteDir = resolve(repoRoot, 'mineral-map-site')

const run = (command, args) => {
  const result = sync_spawn(command, args)
  if (result.status !== 0) {
    console.error(result.stdout?.toString() ?? '')
    console.error(result.stderr?.toString() ?? '')
    process.exit(result.status ?? 1)
  }
}

const sync_spawn = (command, args) =>
  spawnSync(command, args, { stdio: 'inherit', shell: true, cwd: appRoot })

console.log('Building frontend...')
run('npm', ['run', 'build'])

if (existsSync(siteDir)) rmSync(siteDir, { recursive: true, force: true })
mkdirSync(siteDir, { recursive: true })

// dist/ already contains assets/ + data/ + index.html + favicon.svg — a
// complete, self-contained static site. Copy it wholesale.
cpSync(distDir, siteDir, { recursive: true })

// Cloudflare Pages style: no server config needed — every file is static.
// Add a minimal README so whoever opens the folder knows what it is.
writeFileSync(
  resolve(siteDir, 'README.txt'),
  `Static build of the IMA Mineral Map frontend.\n` +
    `Deploy: copy the CONTENTS of this folder to your web server / Pages repo.\n` +
    `Rebuild: cd mineral-map && npm install && npm run build:site\n`,
)

console.log(`\nDone. Deployable site ready at: ${siteDir}`)
console.log('Copy the folder contents into your website repo and commit.')
