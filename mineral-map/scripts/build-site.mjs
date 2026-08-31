/**
 * Build the frontend and assemble a clean, copy-ready deployable folder.
 *
 * Usage:
 *   npm run build:site                          # root-relative build (own subdomain/domain root)
 *   npm run build:site -- --base /minerals/     # subpath deployment (works in PowerShell, cmd, and bash)
 *   npm run build:site -- --open                # open the output folder afterwards
 *
 * The base path must start and end with "/" (e.g. "/other/minerals/") and must
 * exactly match the folder the site is served from. Alternatively set the
 * DEPLOY_BASE_PATH environment variable (bash-style: DEPLOY_BASE_PATH=/x/ npm run build:site).
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

const args = process.argv.slice(2)
const baseFlagIndex = args.indexOf('--base')
let basePath = process.env.DEPLOY_BASE_PATH || ''
if (baseFlagIndex !== -1) {
  basePath = args[baseFlagIndex + 1] ?? ''
  if (!basePath || basePath.startsWith('--')) {
    console.error('Error: --base requires a value, e.g. npm run build:site -- --base /minerals/')
    process.exit(1)
  }
}
if (basePath && (!basePath.startsWith('/') || !basePath.endsWith('/'))) {
  console.error(`Error: base path "${basePath}" must start and end with "/", e.g. "/other/minerals/"`)
  process.exit(1)
}
if (basePath) console.log(`Deploying under base path: ${basePath}`)

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
if (basePath) {
  // Pass the base path as a CLI flag so this works identically in PowerShell,
  // cmd, and bash without shell-specific environment syntax.
  // tsc -b first keeps the same type-checking as the normal `npm run build`.
  run('npx', ['tsc', '-b'])
  run('npx', ['vite', 'build', '--base', basePath])
} else {
  run('npm', ['run', 'build'])
}

if (existsSync(siteDir)) rmSync(siteDir, { recursive: true, force: true })
mkdirSync(siteDir, { recursive: true })

cpSync(distDir, siteDir, { recursive: true })

writeFileSync(
  resolve(siteDir, 'README.txt'),
  `Static build of the IMA Mineral Map frontend.\n` +
    `Deploy: copy the CONTENTS of this folder to your web server / Pages repo.\n` +
    `Rebuild: cd mineral-map && npm install && npm run build:site\n`,
)

console.log(`\nDone. Deployable site ready at: ${siteDir}`)
console.log('Copy the folder contents into your website repo and commit.')
