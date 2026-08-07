import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { parse } from 'csv-parse/sync'

const appRoot = resolve(import.meta.dirname, '..')
const nodesPath = resolve(appRoot, 'public/data/mineral-map-nodes.json')
const webExportNodesPath = resolve(appRoot, '../web_export/mineral-map-nodes.json')
const sourcePath = resolve(appRoot, '../IMA_data_with_mindat.csv')
const classificationsPath = resolve(appRoot, '../mindat_export/classifications')

const [nodeText, sourceText, classesText, subclassesText, familiesText, danaGroupsText, danaSubgroupsText] = await Promise.all([
  readFile(nodesPath, 'utf8'),
  readFile(sourcePath, 'utf8'),
  readFile(resolve(classificationsPath, 'nickel_strunz_classes.json'), 'utf8'),
  readFile(resolve(classificationsPath, 'nickel_strunz_subclasses.json'), 'utf8'),
  readFile(resolve(classificationsPath, 'nickel_strunz_families.json'), 'utf8'),
  readFile(resolve(classificationsPath, 'dana8_groups.json'), 'utf8'),
  readFile(resolve(classificationsPath, 'dana8_subgroups.json'), 'utf8'),
])

const payload = JSON.parse(nodeText)
const classes = JSON.parse(classesText)
const subclasses = JSON.parse(subclassesText)
const families = JSON.parse(familiesText)
const danaGroups = JSON.parse(danaGroupsText)
const danaSubgroups = JSON.parse(danaSubgroupsText)
const sourceRows = parse(sourceText, {
  bom: true,
  columns: true,
  relax_quotes: true,
  skip_empty_lines: true,
})

const classCode = (value) => String(value).padStart(2, '0')
const simplifyClassName = (title) => title.split('(', 1)[0].trim().toLocaleLowerCase()
const classNames = new Map(classes.results.flat().map((entry) => [classCode(entry.id), simplifyClassName(entry.title)]))
const subclassNames = new Map(subclasses.results.map((entry) => [`${classCode(entry.strunz1)}.${entry.strunz2.toUpperCase()}`, entry.title2]))
const divisionNames = new Map(families.results.map((entry) => [`${classCode(entry.strunz1)}.${entry.strunz2.toUpperCase()}.${entry.strunz3.toUpperCase()}`, entry.title3]))
const danaClassIndex = new Map(danaGroups.results.map((entry, index) => [entry.id.toLowerCase(), index]))
const danaGroupNames = new Map(danaGroups.results.map((entry) => [entry.id.toLowerCase(), entry.title]))
const danaTypesByClass = new Map()
for (const entry of danaSubgroups.results) {
  const danaClass = entry.dana1.toLowerCase()
  const types = danaTypesByClass.get(danaClass) ?? []
  types.push(entry.dana2.toLowerCase())
  danaTypesByClass.set(danaClass, types)
}

if (payload.nodes.length !== sourceRows.length) {
  throw new Error(`Node/source row count mismatch: ${payload.nodes.length} nodes, ${sourceRows.length} CSV rows.`)
}

const classificationFor = (row) => {
  const rawClass = row['Mindat Strunz 10 Class']?.trim()
  if (!rawClass || rawClass === '0') return undefined
  const classNumber = Number(rawClass)
  if (!Number.isInteger(classNumber) || classNumber < 1 || classNumber > 10) {
    throw new Error(`Invalid Mindat Strunz class for ${row['Mineral Name']}: ${rawClass}`)
  }
  const value = { class: classCode(classNumber) }
  for (const [key, column] of Object.entries({ subclass: 'Mindat Strunz 10 Subclass', division: 'Mindat Strunz 10 Division', group: 'Mindat Strunz 10 Group' })) {
    const field = row[column]?.trim()
    if (field && field !== '0') value[key] = field.toUpperCase()
  }
  const className = classNames.get(value.class)
  if (!className) throw new Error(`No Mindat Strunz class name for ${row['Mineral Name']}: ${value.class}`)
  value.names = { class: className }
  if (value.subclass) {
    const subclassName = subclassNames.get(`${value.class}.${value.subclass}`)
    if (!subclassName) throw new Error(`No Mindat Strunz subclass name for ${row['Mineral Name']}: ${value.class}.${value.subclass}`)
    value.names.subclass = subclassName
  }
  if (value.division) {
    if (!value.subclass) throw new Error(`Mindat Strunz division has no subclass for ${row['Mineral Name']}`)
    const divisionName = divisionNames.get(`${value.class}.${value.subclass}.${value.division}`)
    if (!divisionName) throw new Error(`No Mindat Strunz division name for ${row['Mineral Name']}: ${value.class}.${value.subclass}.${value.division}`)
    value.names.division = divisionName
  }
  return value
}

const danaFor = (row) => {
  const rawClass = row['Mindat Dana 8 Class']?.trim()
  if (!rawClass || rawClass === '0') return undefined
  const normalize = (value) => value?.trim().toLowerCase()
  const danaClass = normalize(rawClass)
  const classIndex = danaClassIndex.get(danaClass)
  if (classIndex === undefined) throw new Error(`Invalid Mindat Dana class for ${row['Mineral Name']}: ${rawClass}`)
  const groupName = danaGroupNames.get(danaClass)
  if (!groupName) throw new Error(`No Mindat Dana group name for ${row['Mineral Name']}: ${rawClass}`)
  const value = { class: rawClass, groupName, classIndex }
  for (const [key, column] of Object.entries({ type: 'Mindat Dana 8 Type', group: 'Mindat Dana 8 Group', number: 'Mindat Dana 8 Number' })) {
    const field = row[column]?.trim()
    if (field && field !== '0') value[key] = field
  }
  if (value.type) {
    const types = danaTypesByClass.get(danaClass) ?? []
    const typeIndex = types.indexOf(normalize(value.type))
    if (typeIndex !== -1) {
      value.typeIndex = typeIndex
      value.typeCount = types.length
    }
  }
  return value
}

const hardnessFor = (row) => {
  const parseHardness = (column) => {
    const value = Number(row[column]?.trim())
    return Number.isFinite(value) && value >= 0 && value <= 10 ? value : undefined
  }
  const minimum = parseHardness('Mindat Hardness Minimum')
  const maximum = parseHardness('Mindat Hardness Maximum')
  return minimum !== undefined && maximum !== undefined && minimum <= maximum ? { minimum, maximum } : undefined
}

let classified = 0
let danaClassified = 0
let hardnessAvailable = 0
payload.nodes.forEach((node, index) => {
  const row = sourceRows[index]
  if (node.name !== row['Mineral Name']) {
    throw new Error(`Mineral order mismatch at row ${index}: ${node.name} versus ${row['Mineral Name']}.`)
  }
  const classification = classificationFor(row)
  const dana = danaFor(row)
  const hardness = hardnessFor(row)
  const formulaHtml = row['Valence Chemistry (HTML)']?.trim()
  if (classification) {
    node.mindatStrunz = classification
    classified += 1
  } else {
    delete node.mindatStrunz
  }
  if (dana) {
    node.mindatDana = dana
    danaClassified += 1
  } else {
    delete node.mindatDana
  }
  if (hardness) {
    node.mindatHardnessMinimum = hardness.minimum
    node.mindatHardnessMaximum = hardness.maximum
    hardnessAvailable += 1
  } else {
    delete node.mindatHardnessMinimum
    delete node.mindatHardnessMaximum
  }
  delete node.nickelStrunz
  if (formulaHtml) node.formulaHtml = formulaHtml
  else delete node.formulaHtml
})

const output = `${JSON.stringify(payload)}\n`
await Promise.all([
  writeFile(nodesPath, output, 'utf8'),
  writeFile(webExportNodesPath, output, 'utf8'),
])
console.log(`Added Strunz–Mindat classifications to ${classified.toLocaleString()}, Dana classifications to ${danaClassified.toLocaleString()}, and hardness ranges to ${hardnessAvailable.toLocaleString()} of ${payload.nodes.length.toLocaleString()} nodes, then synchronized the web export.`)