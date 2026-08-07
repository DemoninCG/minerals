export type MineralNode = {
  id: number
  name: string
  formula: string
  formulaHtml?: string
  symbol: string
  mindatStrunz?: {
    class: string
    subclass?: string
    division?: string
    group?: string
    names: {
      class: string
      subclass?: string
      division?: string
    }
  }
  mindatDana?: {
    class: string
    type?: string
    group?: string
    number?: string
    groupName: string
    classIndex: number
    typeIndex?: number
    typeCount?: number
  }
  yearFirstPublished: string
  mindatHardnessMinimum?: number
  mindatHardnessMaximum?: number
  imaStatus: string
  strunz: {
    code: string
    name: string
  }
  structure: {
    group: string
    crystalSystem: string
    spaceGroups: string
  }
  coordinates: [number, number, number]
  composition: {
    anionGroups: CompositionEntry[]
    cations: CompositionEntry[]
    extraAnions: CompositionEntry[]
    hydration: number
    structuralWater: number
  }
}

export type CompositionEntry = {
  label: string
  fraction: number
}

export type Neighbor = {
  targetId: number
  rank: number
  distance: number
  category: string
  components: Record<string, { raw: number; weighted: number }>
}

export type NodePayload = {
  schemaVersion: string
  coordinateSystem: string
  nodes: MineralNode[]
}

export type NeighborPayload = {
  schemaVersion: string
  neighborCount: number
  neighborsBySourceId: Neighbor[][]
}

export type MetadataPayload = {
  nodeCount: number
  componentWeights: Record<string, number>
  relationshipCategories: Record<string, string>
}
