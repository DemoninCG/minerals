import { Canvas, type ThreeEvent, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls } from '@react-three/drei'
import { ArrowRight, GitCompareArrows, Search, X, ZoomIn } from 'lucide-react'
import { useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import './App.css'
import type { MetadataPayload, MineralNode, Neighbor, NeighborPayload, NodePayload } from './types'

const STRUNZ_COLORS: Record<string, string> = {
  '01': '#e0a63f',
  '02': '#cc5b3e',
  '03': '#47a6a2',
  '04': '#7c8f48',
  '05': '#e77f67',
  '06': '#9b6a92',
  '07': '#5d82be',
  '08': '#b9587a',
  '09': '#4d9b63',
  '10': '#b57d3d',
}

const NICKEL_HUES: Record<string, number> = {
  '01': 43, '02': 12, '03': 178, '04': 84, '05': 8,
  '06': 306, '07': 214, '08': 340, '09': 139, '10': 30,
}

type ColorMode = 'dana' | 'strunzMindat' | 'element' | 'year' | 'hardness'
type LinkMode = 'off' | 'selected' | 'all'
type ColorDomain = { year?: [number, number]; hardness?: [number, number] }

const FALLBACK_COLOR = '#afb3a8'
const GRADIENT_STEPS = 64
const SCENE_SCALE = 10
const INITIAL_CAMERA_POSITION: [number, number, number] = [10, 5, 15]
const INITIAL_CAMERA_DISTANCE = Math.hypot(...INITIAL_CAMERA_POSITION)
const MIN_NODE_ZOOM_SCALE = 0.05
const NODE_RADIUS = 0.1
const SELECTED_NODE_RADIUS = 0.16

const COMPONENT_LABELS: Record<string, string> = {
  anion_group: 'Oxyanion groups',
  cations: 'Cations',
  extra_anions: 'Residual anions',
  hydration: 'Hydration',
  structural_water: 'Structural water',
  structure: 'Structure',
}

const elementFromLabel = (label: string) => label.split('^', 1)[0]

const scaleCoordinates = ([x, y, z]: MineralNode['coordinates']): MineralNode['coordinates'] => [
  x * SCENE_SCALE,
  y * SCENE_SCALE,
  z * SCENE_SCALE,
]

const nodeScaleForCamera = (coordinates: MineralNode['coordinates'], camera: THREE.Camera) => (
  Math.min(1, Math.max(MIN_NODE_ZOOM_SCALE, camera.position.distanceTo(new THREE.Vector3(...coordinates)) / INITIAL_CAMERA_DISTANCE))
)

const nodeElements = (node: MineralNode) => {
  const elements = new Set<string>()
  for (const entry of [...node.composition.cations, ...node.composition.extraAnions]) {
    elements.add(elementFromLabel(entry.label))
  }
  for (const entry of node.composition.anionGroups) elements.add(entry.label.split('-O', 1)[0])
  if (node.composition.anionGroups.length) elements.add('O')
  if (node.composition.hydration || node.composition.structuralWater) {
    elements.add('H')
    elements.add('O')
  }
  return elements
}

const mindatSubclassLightness = (subclass?: string) => {
  const index = subclass?.charCodeAt(0) ?? -1
  return index >= 65 && index <= 74 ? 34 + (index - 65) * 3.5 : 50
}

const danaTypeLightness = (typeIndex?: number, typeCount?: number) => {
  if (typeIndex === undefined || !typeCount || typeCount <= 1) return 47
  return 34 + (typeIndex / (typeCount - 1)) * 25
}

const publicationYear = (value: string) => {
  const year = Number(value)
  return /^\d{4}$/.test(value.trim()) && Number.isInteger(year) && year >= 1500 && year <= new Date().getFullYear() ? year : undefined
}

const averageHardness = (node: MineralNode) => {
  const minimum = node.mindatHardnessMinimum
  const maximum = node.mindatHardnessMaximum
  return minimum !== undefined && maximum !== undefined && minimum >= 0 && maximum <= 10 && minimum <= maximum
    ? (minimum + maximum) / 2
    : undefined
}

const domainFor = (values: number[]): [number, number] | undefined => {
  if (!values.length) return undefined
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  return [minimum, maximum]
}

const interpolateColor = (from: string, to: string, amount: number) => {
  const start = Number.parseInt(from.slice(1), 16)
  const end = Number.parseInt(to.slice(1), 16)
  const channel = (shift: number) => Math.round(((start >> shift) & 255) + ((((end >> shift) & 255) - ((start >> shift) & 255)) * amount))
  return `#${[16, 8, 0].map((shift) => channel(shift).toString(16).padStart(2, '0')).join('')}`
}

const gradientColor = (value: number | undefined, domain: [number, number] | undefined, colors: [string, string, string], transform = (ratio: number) => ratio) => {
  if (value === undefined || !domain) return FALLBACK_COLOR
  const ratio = domain[0] === domain[1] ? 0.5 : Math.min(1, Math.max(0, (value - domain[0]) / (domain[1] - domain[0])))
  const steppedRatio = Math.round(transform(ratio) * (GRADIENT_STEPS - 1)) / (GRADIENT_STEPS - 1)
  return steppedRatio <= 0.5
    ? interpolateColor(colors[0], colors[1], steppedRatio * 2)
    : interpolateColor(colors[1], colors[2], (steppedRatio - 0.5) * 2)
}

function nodeColor(node: MineralNode, mode: ColorMode, selectedElement: string, domain: ColorDomain) {
  if (mode === 'element') return nodeElements(node).has(selectedElement) ? '#d26145' : '#aeb3a6'
  if (mode === 'year') return gradientColor(publicationYear(node.yearFirstPublished), domain.year, ['#3778c2', '#39a96b', '#f6d743'], (ratio) => ratio ** 7)
  if (mode === 'hardness') return gradientColor(averageHardness(node), domain.hardness, ['#3979c9', '#873eaa', '#d63d4b'])
  if (mode === 'dana') {
    const classification = node.mindatDana
    if (!classification) return FALLBACK_COLOR
    return `hsl(${(classification.classIndex / 79) * 360}, 58%, ${danaTypeLightness(classification.typeIndex, classification.typeCount)}%)`
  }
  const classification = node.mindatStrunz
  if (!classification) return FALLBACK_COLOR
  if (!classification.subclass) return STRUNZ_COLORS[classification.class] ?? FALLBACK_COLOR
  return `hsl(${NICKEL_HUES[classification.class] ?? 80}, 55%, ${mindatSubclassLightness(classification.subclass)}%)`
}

type MapPointsProps = {
  nodes: MineralNode[]
  selectedId: number | null
  colorMode: ColorMode
  selectedElement: string
  colorDomain: ColorDomain
  onSelect: (id: number) => void
}

function MapPoints({ nodes, selectedId, colorMode, selectedElement, colorDomain, onSelect }: MapPointsProps) {
  const colorBatches = useMemo(() => {
    const groups = new Map<string, MineralNode[]>()
    for (const node of nodes) {
      const color = nodeColor(node, colorMode, selectedElement, colorDomain)
      const batch = groups.get(color)
      if (batch) batch.push(node)
      else groups.set(color, [node])
    }
    return [...groups.entries()]
  }, [colorDomain, colorMode, nodes, selectedElement])

  const selectedNode = selectedId === null ? null : nodes[selectedId]

  return (
    <>
      {colorBatches.map(([color, batch]) => (
        <ColorBatch key={color} nodes={batch} color={color} onSelect={onSelect} />
      ))}
      {selectedNode && <SelectedNode node={selectedNode} />}
    </>
  )
}

function ColorBatch({ nodes, color, onSelect }: { nodes: MineralNode[]; color: string; onSelect: (id: number) => void }) {
  const { camera } = useThree()
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const lastCameraPosition = useRef(new THREE.Vector3())

  const updateInstanceMatrices = () => {
    const mesh = meshRef.current
    if (!mesh) return
    nodes.forEach((node, index) => {
      dummy.position.fromArray(node.coordinates)
      dummy.scale.setScalar(nodeScaleForCamera(node.coordinates, camera))
      dummy.updateMatrix()
      mesh.setMatrixAt(index, dummy.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
  }

  useLayoutEffect(() => {
    updateInstanceMatrices()
  }, [camera, dummy, nodes])

  useFrame(() => {
    if (camera.position.distanceToSquared(lastCameraPosition.current) < 0.0001) return
    lastCameraPosition.current.copy(camera.position)
    updateInstanceMatrices()
  })

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, nodes.length]}
      onClick={(event: ThreeEvent<MouseEvent>) => {
        event.stopPropagation()
        if (event.delta > 4 || event.instanceId === undefined) return
        onSelect(nodes[event.instanceId].id)
      }}
    >
      <sphereGeometry args={[NODE_RADIUS, 10, 10]} />
      <meshBasicMaterial color={color} />
    </instancedMesh>
  )
}

function SelectedNode({ node }: { node: MineralNode }) {
  const { camera } = useThree()
  const meshRef = useRef<THREE.Mesh>(null)

  useFrame(() => {
    meshRef.current?.scale.setScalar(nodeScaleForCamera(node.coordinates, camera))
  })

  return (
    <mesh ref={meshRef} position={node.coordinates} renderOrder={1}>
      <sphereGeometry args={[SELECTED_NODE_RADIUS, 20, 20]} />
      <meshBasicMaterial color="#fff3b0" />
    </mesh>
  )
}

function FocusSelection({ node, controlsRef }: { node: MineralNode | null; controlsRef: RefObject<OrbitControlsImpl | null> }) {
  const { camera } = useThree()
  const desiredCamera = useRef(new THREE.Vector3())
  const desiredTarget = useRef(new THREE.Vector3())
  const isFocusing = useRef(false)

  useEffect(() => {
    if (!node) return
    const controls = controlsRef.current
    const currentTarget = controls?.target ?? new THREE.Vector3()
    const direction = camera.position.clone().sub(currentTarget).normalize()
    desiredTarget.current.fromArray(node.coordinates)
    desiredCamera.current.copy(desiredTarget.current).addScaledVector(direction, 3.6)
    isFocusing.current = true
  }, [camera, controlsRef, node])

  useFrame((_, delta) => {
    if (!node || !controlsRef.current || !isFocusing.current) return
    const blend = 1 - Math.exp(-8 * delta)
    camera.position.lerp(desiredCamera.current, blend)
    controlsRef.current.target.lerp(desiredTarget.current, blend)
    controlsRef.current.update()
    if (
      camera.position.distanceToSquared(desiredCamera.current) < 0.00001
      && controlsRef.current.target.distanceToSquared(desiredTarget.current) < 0.00001
    ) {
      isFocusing.current = false
    }
  })
  return null
}

function NeighborLinks({ source, neighbors, nodes, colorMode, selectedElement, colorDomain }: { source: MineralNode; neighbors: Neighbor[]; nodes: MineralNode[]; colorMode: ColorMode; selectedElement: string; colorDomain: ColorDomain }) {
  return (
    <>
      {neighbors.map((neighbor) => {
        const target = nodes[neighbor.targetId]
        if (!target) return null
        return (
          <Line
            key={neighbor.targetId}
            points={[source.coordinates, target.coordinates]}
            color={nodeColor(target, colorMode, selectedElement, colorDomain)}
            transparent
            opacity={0.76}
            lineWidth={1.5}
            depthTest
            depthWrite={false}
            renderOrder={2}
          />
        )
      })}
    </>
  )
}

function GlobalNeighborLinks({ nodes, neighborsBySourceId, neighborLimit }: { nodes: MineralNode[]; neighborsBySourceId: Neighbor[][]; neighborLimit: number }) {
  const positions = useMemo(() => {
    const seen = new Set<string>()
    const values: number[] = []
    neighborsBySourceId.forEach((neighbors, sourceId) => {
      const source = nodes[sourceId]
      if (!source) return
      neighbors.forEach((neighbor) => {
        if (neighbor.rank > neighborLimit) return
        const target = nodes[neighbor.targetId]
        if (!target) return
        const edgeKey = sourceId < neighbor.targetId ? `${sourceId}:${neighbor.targetId}` : `${neighbor.targetId}:${sourceId}`
        if (seen.has(edgeKey)) return
        seen.add(edgeKey)
        values.push(...source.coordinates, ...target.coordinates)
      })
    })
    return new Float32Array(values)
  }, [neighborLimit, neighborsBySourceId, nodes])

  const geometry = useMemo(() => {
    const lineGeometry = new THREE.BufferGeometry()
    lineGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    return lineGeometry
  }, [positions])

  useEffect(() => () => geometry.dispose(), [geometry])

  return (
    <lineSegments geometry={geometry} renderOrder={-1}>
      <lineBasicMaterial color="#687d70" transparent opacity={0.2} depthTest depthWrite={false} />
    </lineSegments>
  )
}

function CompositionList({ entries }: { entries: MineralNode['composition']['cations'] }) {
  if (!entries.length) return <span className="muted">None</span>
  return (
    <span>
      {entries.map((entry) => `${entry.label} ${Math.round(entry.fraction * 100)}%`).join(', ')}
    </span>
  )
}

function MindatStrunzDescription({ classification }: { classification?: MineralNode['mindatStrunz'] }) {
  if (!classification) return <>Not classified by Mindat</>
  const code = [classification.class, classification.subclass, classification.division, classification.group].filter(Boolean).join('.')
  const names = [classification.names.class, classification.names.subclass, classification.names.division].filter(Boolean)

  return <><span>{code}</span>{names.length > 0 && <span className="mindat-strunz-names" dangerouslySetInnerHTML={{ __html: names.join(' - ') }} />}</>
}

function MindatDanaDescription({ classification }: { classification?: MineralNode['mindatDana'] }) {
  if (!classification) return <>Not classified by Mindat</>
  return <><span>{[classification.class, classification.type, classification.group, classification.number].filter(Boolean).join('.')}</span><span className="mindat-strunz-names" dangerouslySetInnerHTML={{ __html: classification.groupName }} /></>
}

function formatProfileChanges(sourceEntries: MineralNode['composition']['cations'], targetEntries: MineralNode['composition']['cations']) {
  const source = new Map(sourceEntries.map((entry) => [entry.label, entry.fraction]))
  const target = new Map(targetEntries.map((entry) => [entry.label, entry.fraction]))
  return [...new Set([...source.keys(), ...target.keys()])]
    .map((label) => ({ label, source: source.get(label) ?? 0, target: target.get(label) ?? 0 }))
    .filter((entry) => Math.abs(entry.source - entry.target) > 0.005)
    .sort((left, right) => Math.abs(right.source - right.target) - Math.abs(left.source - left.target))
}

function componentDifferenceText(source: MineralNode, target: MineralNode, component: string) {
  if (component === 'hydration' || component === 'structural_water') {
    const sourceAmount = component === 'hydration' ? source.composition.hydration : source.composition.structuralWater
    const targetAmount = component === 'hydration' ? target.composition.hydration : target.composition.structuralWater
    return sourceAmount === targetAmount ? 'No difference detected.' : `${sourceAmount || 'none'} → ${targetAmount || 'none'} formula water.`
  }
  if (component === 'structure') {
    if (source.structure.group === target.structure.group) return `Both are in the ${source.structure.group} structural group.`
    return `${source.structure.group || 'No named group'} → ${target.structure.group || 'no named group'}.`
  }
  const entries = component === 'anion_group'
    ? [source.composition.anionGroups, target.composition.anionGroups]
    : component === 'cations'
      ? [source.composition.cations, target.composition.cations]
      : [source.composition.extraAnions, target.composition.extraAnions]
  const changes = formatProfileChanges(entries[0], entries[1])
  if (!changes.length) return 'No normalized profile difference detected.'
  const visible = changes.slice(0, 3).map((change) => `${change.label} ${Math.round(change.source * 100)}% → ${Math.round(change.target * 100)}%`)
  return `${visible.join('; ')}${changes.length > 3 ? `; +${changes.length - 3} more` : ''}.`
}

function RelationshipInspector({ source, target, neighbor, categoryDescription, onClear, onSelectTarget }: { source: MineralNode; target: MineralNode; neighbor: Neighbor; categoryDescription?: string; onClear: () => void; onSelectTarget: () => void }) {
  const total = neighbor.distance || 1
  const components = Object.entries(neighbor.components)
    .filter(([component]) => COMPONENT_LABELS[component])
    .sort(([left], [right]) => (neighbor.components[right].weighted - neighbor.components[left].weighted))

  return (
    <section className="relationship-section">
      <div className="relationship-heading">
        <div>
          <h3><GitCompareArrows size={15} /> Relationship inspector</h3>
          <p>{source.name} <ArrowRight size={12} /> <strong>{target.name}</strong></p>
        </div>
        <button className="text-button" type="button" onClick={onClear}>Close</button>
      </div>
      <div className="relationship-summary">
        <span className="relationship-category">{neighbor.category.replaceAll('_', ' ')}</span>
        <strong>{neighbor.distance.toFixed(3)}</strong>
      </div>
      <p className="relationship-description">{categoryDescription ?? 'Exact k-NN relationship classified from the additive component profile.'}</p>
      <p className="relationship-note">Exact additive dissimilarity. The six weighted components below sum to the displayed score.</p>
      <div className="component-bars">
        {components.map(([component, value]) => {
          const share = value.weighted / total
          return (
            <div className="component-bar" key={component}>
              <div><span>{COMPONENT_LABELS[component]}</span><b>{value.weighted.toFixed(3)}</b></div>
              <div className="bar-track"><i style={{ width: `${Math.max(share * 100, value.weighted > 0 ? 2 : 0)}%` }} /></div>
              <small>{componentDifferenceText(source, target, component)}</small>
            </div>
          )
        })}
      </div>
      <button className="inspect-target" type="button" onClick={onSelectTarget}>View {target.name}</button>
    </section>
  )
}

function App() {
  const [nodes, setNodes] = useState<MineralNode[]>([])
  const [metadata, setMetadata] = useState<MetadataPayload | null>(null)
  const [neighbors, setNeighbors] = useState<NeighborPayload | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [inspectedTargetId, setInspectedTargetId] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [linkMode, setLinkMode] = useState<LinkMode>('selected')
  const [neighborLimit, setNeighborLimit] = useState(3)
  const [colorMode, setColorMode] = useState<ColorMode>('strunzMindat')
  const [selectedElement, setSelectedElement] = useState('Fe')
  const [loadError, setLoadError] = useState<string | null>(null)
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase())

  useEffect(() => {
    Promise.all([
      fetch('/data/mineral-map-nodes.json').then((response) => response.json() as Promise<NodePayload>),
      fetch('/data/mineral-map-metadata.json').then((response) => response.json() as Promise<MetadataPayload>),
    ])
      .then(([nodeData, metadataData]) => {
        setNodes(nodeData.nodes.map((node) => ({ ...node, coordinates: scaleCoordinates(node.coordinates) })))
        setMetadata(metadataData)
      })
      .catch(() => setLoadError('Unable to load the mineral-map data files.'))
  }, [])

  useEffect(() => {
    if ((selectedId === null && linkMode !== 'all') || neighbors) return
    fetch('/data/mineral-map-neighbors.json')
      .then((response) => response.json() as Promise<NeighborPayload>)
      .then(setNeighbors)
      .catch(() => setLoadError('Unable to load mineral neighbour data.'))
  }, [linkMode, neighbors, selectedId])

  const selectedNode = selectedId === null ? null : nodes[selectedId] ?? null
  const selectedNeighbors = selectedId === null ? [] : neighbors?.neighborsBySourceId[selectedId] ?? []
  const inspectedNeighbor = inspectedTargetId === null ? null : selectedNeighbors.find((neighbor) => neighbor.targetId === inspectedTargetId) ?? null
  const inspectedTarget = inspectedNeighbor ? nodes[inspectedNeighbor.targetId] : null
  const availableElements = useMemo(() => [...new Set(nodes.flatMap((node) => [...nodeElements(node)]))].sort(), [nodes])
  const mindatClassifiedCount = useMemo(() => nodes.filter((node) => node.mindatStrunz).length, [nodes])
  const danaClassifiedCount = useMemo(() => nodes.filter((node) => node.mindatDana).length, [nodes])
  const colorDomain = useMemo<ColorDomain>(() => ({
    year: domainFor(nodes.map((node) => publicationYear(node.yearFirstPublished)).filter((year): year is number => year !== undefined)),
    hardness: domainFor(nodes.map(averageHardness).filter((hardness): hardness is number => hardness !== undefined)),
  }), [nodes])
  const searchResults = deferredQuery
    ? nodes.filter((node) => `${node.name} ${node.formula} ${node.symbol}`.toLocaleLowerCase().includes(deferredQuery)).slice(0, 8)
    : []

  const selectMineral = (id: number) => {
    setSelectedId(id)
    setInspectedTargetId(null)
    setQuery('')
  }

  const controlsRef = useRef<OrbitControlsImpl | null>(null)

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>
            <h1>IMA Mineral Map</h1>
            <p>{metadata ? `${metadata.nodeCount.toLocaleString()} approved species` : 'Loading composition space...'}</p>
          </div>
        </div>
        <div className="search-wrap">
          <Search size={17} aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a mineral"
            aria-label="Find a mineral"
          />
          {searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((node) => (
                <button type="button" key={node.id} onClick={() => selectMineral(node.id)}>
                  <strong>{node.name}</strong>
                  <span dangerouslySetInnerHTML={{ __html: node.formulaHtml || node.formula }} />
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="map-controls">
          <select className="color-select" value={colorMode} onChange={(event) => setColorMode(event.target.value as ColorMode)} aria-label="Node color mode">
            <option value="strunzMindat">Strunz–Mindat</option>
            <option value="dana">Dana 8</option>
            <option value="element">By element</option>
            <option value="year">Year first published</option>
            <option value="hardness">Hardness</option>
          </select>
          {colorMode === 'element' && <select className="element-select" value={selectedElement} onChange={(event) => setSelectedElement(event.target.value)} aria-label="Element to highlight">{availableElements.map((element) => <option key={element}>{element}</option>)}</select>}
        </div>
        <div className="link-controls">
          <select className="link-select" value={linkMode} onChange={(event) => setLinkMode(event.target.value as LinkMode)} aria-label="Neighbour link display">
            <option value="off">No links</option>
            <option value="selected">Selected links</option>
            <option value="all">All k-NN links</option>
          </select>
          <label className="neighbor-limit">k
            <select value={neighborLimit} onChange={(event) => setNeighborLimit(Number(event.target.value))} aria-label="Nearest-neighbour count">
              {Array.from({ length: 10 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </div>
      </header>

      <section className="map-layout">
        <div className="scene-panel">
          <Canvas camera={{ position: INITIAL_CAMERA_POSITION, fov: 46 }} dpr={[1, 2]} onPointerMissed={() => setSelectedId(null)}>
            <color attach="background" args={['#101512']} />
            <ambientLight intensity={1.7} />
            <group>
              <MapPoints nodes={nodes} selectedId={selectedId} colorMode={colorMode} selectedElement={selectedElement} colorDomain={colorDomain} onSelect={selectMineral} />
              {linkMode === 'all' && neighbors && <GlobalNeighborLinks nodes={nodes} neighborsBySourceId={neighbors.neighborsBySourceId} neighborLimit={neighborLimit} />}
              {linkMode === 'selected' && selectedNode && <NeighborLinks source={selectedNode} neighbors={selectedNeighbors.filter((neighbor) => neighbor.rank <= neighborLimit)} nodes={nodes} colorMode={colorMode} selectedElement={selectedElement} colorDomain={colorDomain} />}
            </group>
            <FocusSelection node={selectedNode} controlsRef={controlsRef} />
            <OrbitControls ref={controlsRef} makeDefault enablePan enableDamping dampingFactor={0.08} />
          </Canvas>
          <div className="map-overlay map-key">
            <ZoomIn size={15} />
            <span>Drag to rotate · scroll to zoom · right-drag to pan</span>
          </div>
          <div className="map-overlay map-status">{nodes.length ? `${nodes.length.toLocaleString()} nodes · ${colorMode === 'strunzMindat' ? `${mindatClassifiedCount.toLocaleString()} Strunz–Mindat classified` : colorMode === 'dana' ? `${danaClassifiedCount.toLocaleString()} Dana classified` : colorMode === 'year' ? 'publication year gradient' : colorMode === 'hardness' ? 'average hardness gradient' : `${selectedElement}-bearing highlighted`}` : 'Loading nodes'}</div>
        </div>

        <aside className="detail-panel">
          {loadError && <p className="error-message">{loadError}</p>}
          {selectedNode ? (
            <>
              <div className="panel-heading">
                <div>
                  <h2>{selectedNode.name}</h2>
                  <p className="formula" dangerouslySetInnerHTML={{ __html: selectedNode.formulaHtml || selectedNode.formula }} />
                </div>
                <button className="icon-button" type="button" onClick={() => setSelectedId(null)} aria-label="Clear selection" title="Clear selection">
                  <X size={19} />
                </button>
              </div>

              <dl className="fact-grid">
                <div className="strunz-mindat-fact"><dt>Strunz–Mindat</dt><dd><MindatStrunzDescription classification={selectedNode.mindatStrunz} /></dd></div>
                <div className="strunz-mindat-fact"><dt>Dana 8</dt><dd><MindatDanaDescription classification={selectedNode.mindatDana} /></dd></div>
                <div><dt>Structure</dt><dd>{selectedNode.structure.group}</dd></div>
                <div><dt>Crystal system</dt><dd>{selectedNode.structure.crystalSystem}</dd></div>
                <div><dt>IMA symbol</dt><dd>{selectedNode.symbol || '—'}</dd></div>
                <div><dt>Published</dt><dd>{selectedNode.yearFirstPublished || '—'}</dd></div>
                <div><dt>Hardness</dt><dd>{averageHardness(selectedNode)?.toFixed(2) ?? '—'}</dd></div>
              </dl>

              <section className="composition-section">
                <h3>Composition Profile</h3>
                <div className="profile-row"><span>Anion groups</span><CompositionList entries={selectedNode.composition.anionGroups} /></div>
                <div className="profile-row"><span>Cations</span><CompositionList entries={selectedNode.composition.cations} /></div>
                <div className="profile-row"><span>Residual anions</span><CompositionList entries={selectedNode.composition.extraAnions} /></div>
                <div className="profile-row"><span>Hydration</span><b>{selectedNode.composition.hydration || 'None'}</b></div>
                <div className="profile-row"><span>Structural water</span><b>{selectedNode.composition.structuralWater || 'None'}</b></div>
              </section>

              <section className="neighbor-section">
                <h3>Nearest Compositional Analogues</h3>
                {!neighbors && <p className="muted">Loading exact neighbour links…</p>}
                {selectedNeighbors.map((neighbor) => {
                  const target = nodes[neighbor.targetId]
                  if (!target) return null
                  return (
                    <button className={`neighbor-item ${inspectedTargetId === target.id ? 'active' : ''}`} type="button" key={neighbor.targetId} onClick={() => setInspectedTargetId(target.id)}>
                      <span className="rank">{neighbor.rank}</span>
                      <span className="neighbor-name"><strong>{target.name}</strong><small>{neighbor.category.replaceAll('_', ' ')}</small></span>
                      <span className="distance">{neighbor.distance.toFixed(3)}</span>
                    </button>
                  )
                })}
              </section>
              {inspectedNeighbor && inspectedTarget && (
                <RelationshipInspector
                  source={selectedNode}
                  target={inspectedTarget}
                  neighbor={inspectedNeighbor}
                  categoryDescription={metadata?.relationshipCategories[inspectedNeighbor.category]}
                  onClear={() => setInspectedTargetId(null)}
                  onSelectTarget={() => selectMineral(inspectedTarget.id)}
                />
              )}
            </>
          ) : (
            <div className="empty-selection">
              <div className="empty-mark">◌</div>
              <h2>Explore composition space</h2>
              <p>Select a mineral point or search by name to inspect its composition and exact nearest analogues.</p>
              {colorMode === 'strunzMindat' && <p className="color-note">Broad hues show Mindat Strunz classes; ordered shades distinguish subclasses. Grey minerals have no Mindat Strunz classification.</p>}
              {colorMode === 'dana' && <p className="color-note">Broad hues show Dana classes; ordered shades distinguish Dana types. Grey minerals have no Dana classification.</p>}
              {colorMode === 'element' && <p className="color-note">{selectedElement}-bearing minerals are highlighted; all other nodes are grey.</p>}
              {colorMode === 'year' && <p className="color-note">Blue marks the earliest first-published minerals, transitioning through green to yellow for the latest. The scale is weighted toward recent years to make modern publication dates easier to distinguish. Grey minerals have missing or infeasible years.</p>}
              {colorMode === 'hardness' && <p className="color-note">Blue through purple to red shows the average of Mindat's minimum and maximum hardness values. Grey minerals have missing or infeasible hardness ranges.</p>}
              {colorMode === 'strunzMindat' && <div className="legend">
                {Object.entries(STRUNZ_COLORS).map(([code, color]) => <span key={code}><i style={{ background: color }} />{code}</span>)}
              </div>}
              {colorMode === 'year' && colorDomain.year && <div className="gradient-legend"><span>{colorDomain.year[0]}</span><i className="year-gradient" /><span>{colorDomain.year[1]}</span></div>}
              {colorMode === 'hardness' && colorDomain.hardness && <div className="gradient-legend"><span>{colorDomain.hardness[0].toFixed(1)}</span><i className="hardness-gradient" /><span>{colorDomain.hardness[1].toFixed(1)}</span></div>}
            </div>
          )}
        </aside>
      </section>
    </main>
  )
}

export default App
